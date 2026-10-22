"""Free-text attempts. The interpreter proposes a stat, a difficulty, effects and the props being used;
this module checks the props exist, clamps the effects, rolls, and applies the result."""

from __future__ import annotations

import random
import re
from dataclasses import dataclass

from . import dice
from .combat import defeat, discover, flee, fortune
from .content import Content
from .events import Event
from .intent import DC, Intent
from .models import GameState
from .text import a, bare, cap, the

MONSTER_EFFECTS = {"damage_small", "damage_medium", "damage_large", "stun", "pacify", "escape", "evade"}
ONCE_PER_ROOM = {"find_item", "find_gold", "heal_small"}
OFFENSIVE = {"damage_small", "damage_medium", "damage_large", "stun", "pacify"}
SELF_HARM = {"hurt_self_small", "hurt_self_medium"}
CREATIVE_DAMAGE = {"damage_small": "1d4", "damage_medium": "2d6", "damage_large": "3d6"}
UPGRADE = {"damage_small": "damage_medium", "damage_medium": "damage_large", "damage_large": "damage_large"}
DISTRACTIONS = {"food", "shiny"}
STOPWORDS = {"the", "a", "an", "of", "my", "your", "some", "to", "with", "on", "in", "at", "and"}


@dataclass
class Prop:
    name: str
    kind: str  # "feature", "item", "floor" or "gold"
    key: str
    tags: list[str]


def available_props(state: GameState, content: Content) -> list[Prop]:
    room, player = state.room, state.player
    props = [Prop(bare(f.name), "feature", str(i), content.feature_tags(f.name)) for i, f in room.visible_features()]
    for key in dict.fromkeys([player.weapon, *([player.armor] if player.armor else []), *player.inventory]):
        item = content.item(key)
        props.append(Prop(item.name, "item", key, item.tags))
    for key in dict.fromkeys(room.items):
        item = content.item(key)
        props.append(Prop(item.name, "floor", key, item.tags))
    if player.gold > 0:
        props.append(Prop("gold coins", "gold", "gold", ["shiny"]))
    return props


def _words(text: str) -> set[str]:
    return {w.rstrip("s") for w in re.findall(r"[a-z]+", text.lower()) if w not in STOPWORDS}


def match_props(names: list[str], props: list[Prop]) -> list[Prop]:
    """Match the interpreter's free-form prop names against what actually exists here."""
    found: list[Prop] = []
    for name in names[:3]:
        wanted = _words(name)
        if {"gold", "coin"} & wanted:
            wanted |= {"gold", "coin"}
        best = max(props, key=lambda p: len(wanted & _words(p.name)), default=None)
        if best and wanted & _words(best.name) and best not in found:
            found.append(best)
    return found


def clamp_intent(state: GameState, content: Content, intent: Intent, props: list[Prop] | None = None) -> Intent:
    """Keep the interpreter honest: drop effects that can't apply here and cap how strong they can be."""
    props = props or []
    room = state.room
    monster = room.monster if room.monster and room.monster.hp > 0 else None
    monster_def = content.monster(monster.key) if monster else None
    distracting = monster_def is not None and any(set(p.tags) & DISTRACTIONS & set(monster_def.weak) for p in props)
    difficulty = intent.difficulty
    effects: list[str] = []
    for effect in intent.success_effects:
        if effect in SELF_HARM or effect == "nothing":
            continue
        if effect in MONSTER_EFFECTS and not monster:
            continue
        if effect in ("escape", "evade") and not state.in_combat:
            continue
        uses = room.creative_uses.count(effect)
        if effect in ONCE_PER_ROOM and uses >= (2 if "scavenger" in state.player.perks else 1):
            continue
        if effect == "pacify":
            if monster_def.boss:
                effect = "stun"
            elif not (monster_def.intelligent or distracting):
                continue
            elif monster.hostile and difficulty in ("easy", "medium") and not distracting:
                difficulty = "hard"
        if effect == "damage_large" and difficulty not in ("hard", "absurd"):
            effect = "damage_medium"
        if effect.startswith("damage_") and difficulty == "easy":
            effect = "damage_small"
        if effect == "heal_small" and difficulty == "easy":
            difficulty = "medium"
        if effect not in effects:
            effects.append(effect)
    failure = [e for e in intent.failure_effects if e in SELF_HARM][:1]
    stat = intent.stat if intent.stat != "none" else "wits"
    return intent.model_copy(update={"success_effects": effects[:2], "failure_effects": failure,
                                     "difficulty": difficulty, "stat": stat})


def perform_creative(state: GameState, content: Content, intent: Intent, rng: random.Random) -> tuple[Intent, list[Event], bool]:
    """Returns the clamped intent, the events, and whether it took a turn."""
    player, room = state.player, state.room
    props_here = available_props(state, content)
    consumed = [p for p in match_props(intent.consumes, props_here) if p.kind in ("item", "gold")]
    props = match_props(intent.uses, props_here)
    props += [p for p in consumed if p not in props]  # anything used up was obviously used
    intent = clamp_intent(state, content, intent, props)
    summary = intent.summary or "try something unexpected"
    events: list[Event] = []

    for prop in consumed:
        if prop.kind == "gold":
            spent = min(player.gold, 5 * state.floor)
            player.gold -= spent
            events.append(Event("spend", f"You part with {spent} gold."))
        elif prop.key in player.inventory:
            player.inventory.remove(prop.key)
            events.append(Event("spend", f"The {prop.name} is used up."))

    if intent.difficulty == "trivial" or not intent.success_effects:
        return intent, [Event("creative", f"You {summary}.")] + events, state.in_combat

    monster = room.monster if room.monster and room.monster.hp > 0 else None
    monster_def = content.monster(monster.key) if monster else None
    # A weakness only counts when the prop is turned on the monster, not when you hide behind it.
    offensive = bool(OFFENSIVE & set(intent.success_effects))
    weak_hits = [(p, t) for p in props for t in p.tags if offensive and monster_def and t in monster_def.weak]

    bonuses = [(intent.stat, player.stat(intent.stat))]
    for i, prop in enumerate(props[:2]):
        bonuses.append((f"✦ {prop.name}", 2 if i == 0 else 1))
    if props and "showboat" in player.traits:
        bonuses.append(("Showboat", 1))
    if "improviser" in player.perks:
        bonuses.append(("Improviser", 2))
    if "trickster" in player.traits:
        bonuses.append(("Trickster", 1))
    advantage = 1 if weak_hits or ("pacify" in intent.success_effects and "silver_tongue" in player.traits) else 0
    if weak_hits:
        intent = intent.model_copy(update={"success_effects": [UPGRADE.get(e, e) for e in intent.success_effects]})

    impossible = intent.difficulty == "absurd"
    roll = dice.check(rng, intent.stat, bonuses, DC.get(intent.difficulty, 13), advantage=advantage, impossible=impossible)
    verdict = "It works" if roll.success else "It fails"
    events.insert(0, Event("check", f"You attempt to {summary}. {verdict}.", dice=roll,
                           data={"success": roll.success, "rerollable": True, "props": [p.name for p in props]}))
    if weak_hits and monster:
        prop, tag = weak_hits[0]
        events.append(Event("exploit", f"The {prop.name} plays on {the(monster.name)}'s weakness to {tag}!"))
        events += discover(state, monster, tag)
    events += fortune(state, roll)

    if roll.success:
        player.bump("creative_win")
        if props:
            player.bump("flair")
            state.souls += 1
            if player.fate < player.max_fate():
                player.fate += 1
                events.append(Event("fate", f"Style points! The dungeon rewards flair with a Fate token "
                                            f"({player.fate}/{player.max_fate()})."))
    for effect in intent.success_effects if roll.success else intent.failure_effects:
        target = state.room.monster
        if state.over:
            break
        if effect in MONSTER_EFFECTS and (target is None or target.hp <= 0 or not target.hostile):
            continue  # it's already dead, gone or calmed down
        events += _apply_effect(state, content, rng, effect, max(0, player.stat(intent.stat)))
    return intent, events, True


def _apply_effect(state: GameState, content: Content, rng: random.Random, effect: str, bonus: int) -> list[Event]:
    room, player = state.room, state.player
    monster = room.monster
    if effect in ONCE_PER_ROOM:
        room.creative_uses.append(effect)
    if effect in CREATIVE_DAMAGE:
        damage = dice.roll(CREATIVE_DAMAGE[effect], rng) + bonus
        if "bully" in player.perks and monster.stunned:
            damage += 3
        monster.hp -= damage
        monster.hostile = True
        events = [Event("hit", f"{cap(the(monster.name))} takes {damage} damage "
                               f"({max(monster.hp, 0)}/{monster.max_hp} HP left).")]
        return events + (defeat(state, content, rng) if monster.hp <= 0 else [])
    if effect == "stun":
        monster.stunned = 2  # covers this turn's attack and the next, so a stun buys a free action
        monster.intent = "strike"
        player.bump("stuns")
        return [Event("stun", f"{cap(the(monster.name))} is stunned and loses its next two attacks.")]
    if effect == "pacify":
        monster.hostile = False
        return defeat(state, content, rng, how="pacified")
    if effect == "escape":
        return flee(state, content, rng, guaranteed=True)
    if effect == "evade":
        player.dodging = True
        player.bump("dodged")
        return [Event("dodge_ready", "You're in position to avoid the next attack.")]
    if effect == "reveal_secret":
        hidden = [f for f in room.features if f.hidden]
        room.room_searched = True
        for feature in hidden:
            feature.hidden = False
        if hidden:
            return [Event("secret", "You uncover something hidden: " + ", ".join(f.name for f in hidden) + ".")]
        return [Event("info", "There turns out to be nothing hidden here.")]
    if effect == "find_item":
        from .rules import gain_item

        key = rng.choice(["stale_bread", "stale_bread", "healing_potion", "smoke_bomb", "oil_flask"])
        return [Event("find", f"You turn up {a(content.item(key).name)}.")] + gain_item(state, content, key)
    if effect == "find_gold":
        gold = rng.randint(2, 8) * max(1, room.distance) + (4 if "scavenger" in player.perks else 0)
        player.gold += gold
        return [Event("find", f"You find {gold} gold.")]
    if effect == "heal_small":
        healed = min(dice.roll("1d4+2", rng), player.max_hp - player.hp)
        player.hp += healed
        return [Event("heal", f"You recover {healed} HP ({player.hp}/{player.max_hp}).")]
    if effect in SELF_HARM:
        damage = dice.roll("1d4" if effect == "hurt_self_small" else "1d6+1", rng)
        player.hp = max(1, player.hp - damage)
        return [Event("hurt", f"You hurt yourself for {damage} damage ({player.hp}/{player.max_hp} HP).")]
    return []
