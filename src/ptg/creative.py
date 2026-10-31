"""Free-text stunts: what the interaction grid (interactions.py) has no row for. The interpreter proposes a stat, a
difficulty, effects and the props being used; this module checks the props exist, clamps the effects, rolls, and
applies the result.

A stunt wastes nothing. It still rolls, but what it would use up is used up, and its flair paid, only if it changed
something: hurt, stunned or calmed the monster, got you away, turned something up. One that can't change anything
at all (no effect survives the clamp: talking a beast down, a trick with no one to play it on) isn't made: it's told
as an attempt, with why it came to nothing, and costs nothing, not even a turn in a fight.

What it uses up is only what it's done with: what the interpreter says it uses up (`consumes`), and the thing its
own words throw, pour, hand over or eat ("splash the vial on the altar"), never a word that merely turns up ("throw
sand at the rat's eyes" uses up no Pizza Rat). Never your gear, a key, what someone's waiting for, or a curse that
won't let go; gold, as much as is said ("offer 30 gold"), or, said of no amount, a few coins.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass

from . import dice, interactions, inventory, loot, npcs, powers
from .combat import defeat, discover, flee, fortune, provoked
from .content import Content
from .events import Event
from .intent import DC, Intent
from .interactions import ATTEMPT, forms
from .models import GameState
from .scene import FIXTURE_NAMES, FIXTURE_TAGS, RoomView
from .text import a, bare, cap, the

MONSTER_EFFECTS = {"damage_small", "damage_medium", "damage_large", "stun", "pacify", "escape", "evade"}
ONCE_PER_ROOM = {"find_item", "find_gold", "heal_small"}
OFFENSIVE = {"damage_small", "damage_medium", "damage_large", "stun", "pacify"}
HOSTILE = {"damage_small", "damage_medium", "damage_large", "stun"}  # done to a calm creature, it fights back
SELF_HARM = {"hurt_self_small", "hurt_self_medium"}
CREATIVE_DAMAGE = {"damage_small": "1d4", "damage_medium": "2d6", "damage_large": "3d6"}
UPGRADE = {"damage_small": "damage_medium", "damage_medium": "damage_large", "damage_large": "damage_large"}
DISTRACTIONS = {"food", "shiny"}  # what a beast can be calmed with, if it's weak to it; any other weakness dazes it
STOPWORDS = {"the", "a", "an", "of", "my", "your", "some", "to", "with", "on", "in", "at", "and"}
# Doing one of these with a thing you carry leaves you without it, if the stunt comes to anything. (Not dropping or
# leaving it: that's inventory.drop, and it stays where you leave it.)
SPENDING = {"throw", "toss", "hurl", "fling", "lob", "give", "offer", "bribe", "feed", "trade", "pay", "drink", "eat",
            "pour", "splash", "spill", "smash", "shatter", "burn", "ignite", "scatter", "sprinkle", "sacrifice", "empty",
            "dump", "lure", "bait"}
SPENDABLE = {"consumable", "trinket"}  # never your gear, and never a key: a run could hang on it
# What shows a stunt changed something: and so used up what it used, and earned its flair.
CHANGES = {"hit", "stun", "pacify", "defeat", "flee", "dodge_ready", "secret", "find", "heal", "victory", "ghost_rest"}


@dataclass
class Prop:
    name: str
    kind: str  # "feature", "item", "floor", "gold" or "fixture"
    key: str
    tags: list[str]


def available_props(state: GameState, content: Content) -> list[Prop]:
    room, player = state.room, state.player
    props = [Prop(bare(f.name), "feature", str(i), content.feature_tags(f.name))
             for i, f in room.visible_features() if not f.used]  # a prop that's done its stunt is spent
    if room.fixture and f"prop:{room.fixture}" not in room.creative_uses:  # the chest to hurl, the fountain to dunk in
        props.append(Prop(FIXTURE_NAMES[room.fixture], "fixture", room.fixture, FIXTURE_TAGS[room.fixture]))
    for key in dict.fromkeys([*player.gear, *player.inventory]):
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


def spends(summary: str) -> bool:
    """Whether an attempt's words hand over, throw, feed, drink or pour something: "bribe the orc with stale bread"."""
    return any(forms(word) & SPENDING for word in re.findall(r"[a-z]+", summary.lower()))


def _spendable(content: Content, prop: Prop) -> bool:
    return prop.kind == "gold" or prop.kind in ("item", "floor") and content.item(prop.key).kind in SPENDABLE


def _held(state: GameState, content: Content, prop: Prop) -> str:
    """Why a stunt won't use up something, though it's named as what's used up: a key or what someone's waiting for
    (npcs.needed), or, yours, a curse that won't let go. "" if it would."""
    if prop.kind not in ("item", "floor"):
        return ""
    if npcs.needed(state, content, prop.key):
        where = "it stays in your pack" if prop.kind == "item" else "you leave it where it is"
        return f"You'll be needing {the(prop.name)}: {where}."
    return inventory.keeps(state, content, prop.key) if prop.kind == "item" else ""


def spent(state: GameState, content: Content, intent: Intent, props_here: list[Prop]) -> list[Prop]:
    """What a stunt would use up if it comes to anything: what the interpreter says it uses up, and the thing its own
    words throw, pour, hand over or eat (interactions.spent_by), but only what can be: not gear, keys, what someone's
    waiting for, or a curse."""
    consumed = [p for p in match_props(intent.consumes, props_here) if _spendable(content, p)]
    for key in interactions.spent_by(RoomView(state, content), intent.summary, SPENDING):
        prop = next((p for p in props_here if p.key == key and p.kind in ("item", "gold")), None)
        if prop and _spendable(content, prop) and prop not in consumed:
            consumed.append(prop)
    return [p for p in consumed if not _held(state, content, p)]


def gold_said(state: GameState, intent: Intent) -> int:
    """How much gold a stunt hands over: what it says ("offer 30 gold"), as much as you have; or, said of no amount,
    a few coins (5 a floor)."""
    words = re.findall(r"[a-z0-9]+", intent.summary.lower())
    said = intent.amount or interactions.amount_said(words)
    return min(state.player.gold, said or 5 * state.floor)


def clamp_intent(state: GameState, content: Content, intent: Intent, props: list[Prop] | None = None) -> Intent:
    """Keep the interpreter honest: drop effects that can't apply here and cap how strong they can be."""
    return _clamp(state, content, intent, props)[0]


def _clamp(state: GameState, content: Content, intent: Intent, props: list[Prop] | None = None) -> tuple[Intent, str]:
    """The clamped intent, and why the first effect dropped was ("there's no one here to do it to"), for a stunt that
    comes to nothing."""
    props = props or []
    room = state.room
    monster = room.monster if room.monster and room.monster.hp > 0 else None
    monster_def = content.monster(monster.key) if monster else None
    weak = set(monster_def.weak) if monster_def else set()
    tags = {t for p in props for t in p.tags}
    distracting = bool(tags & DISTRACTIONS & weak)
    dazing = bool(tags & weak) and not distracting  # a beast startled by what it can't stand, rather than won over
    difficulty = intent.difficulty
    effects: list[str] = []
    why = ""
    for effect in intent.success_effects:
        if effect in SELF_HARM or effect == "nothing":
            continue
        if effect in MONSTER_EFFECTS and not monster:
            why = why or "there's no one here to do it to"
            continue
        if effect in ("escape", "evade") and not state.in_combat:
            why = why or "there's nothing here to get away from"
            continue
        uses = room.creative_uses.count(effect)
        if effect in ONCE_PER_ROOM and uses >= (2 if "scavenger" in state.player.perks else 1):
            why = why or "this room has nothing more of that kind to give"
            continue
        if effect == "pacify":
            if not monster.hostile:
                why = why or f"{the(monster.name)} isn't fighting you"
                continue
            if monster_def.boss:
                effect = "stun"
            elif not (monster_def.intelligent or distracting):
                if not dazing:
                    why = why or f"{the(monster.name)} doesn't understand a word of it"
                    continue
                effect = "stun"  # (it can't be won over, but what it's weak to throws it off its stride)
            elif monster.hostile and difficulty in ("easy", "medium") and not distracting:
                difficulty = "hard"
        if effect == "damage_large" and difficulty not in ("hard", "absurd"):
            effect = "damage_medium"
        if effect.startswith("damage_") and difficulty == "easy":
            effect = "damage_small"
        if effect == "heal_small" and difficulty == "easy":
            difficulty = "medium"
        if effect == "pacify" and set(effects) & HOSTILE or effect in HOSTILE and "pacify" in effects:
            continue  # (hurting it and talking it down at once: whichever was said first)
        if effect not in effects:
            effects.append(effect)
    failure = [e for e in intent.failure_effects if e in SELF_HARM][:1]
    stat = intent.stat if intent.stat != "none" else "wits"
    clamped = intent.model_copy(update={"success_effects": effects[:2], "failure_effects": failure,
                                        "difficulty": difficulty, "stat": stat})
    return clamped, why


def perform_creative(state: GameState, content: Content, intent: Intent, rng: random.Random) -> tuple[Intent, list[Event], bool]:
    """Returns the clamped intent, the events, and whether it took a turn."""
    player, room = state.player, state.room
    props_here = available_props(state, content)
    props = match_props(intent.uses, props_here)
    named = [p for p in match_props(intent.consumes, props_here) if p.kind in ("item", "floor")]
    # Never a key, nor what a character's waiting for, nor a curse, whatever the interpreter says: a run could hang on
    # it. An attempt said to use one up isn't made at all, so it costs no turn and earns nothing (a bribe you won't let
    # go of buys nothing, and could otherwise be offered fight after fight). Only said to be used, it's kept.
    held = next((why for why in (_held(state, content, p) for p in named) if why), "")
    if held:
        return intent, [Event("info", held)], False
    consumed = spent(state, content, intent, props_here)
    props += [p for p in consumed if p not in props]  # anything used up was obviously used
    gold = gold_said(state, intent)
    intent, why = _clamp(state, content, intent, props)
    summary = ATTEMPT.sub("", intent.summary) or "try something unexpected"  # "You attempt to attempt to..." no more

    if intent.difficulty == "trivial" or not intent.success_effects:  # it can't change anything: it isn't made
        said = f"You try to {summary}, but {why}." if why else f"You try to {summary}. Nothing much comes of it."
        return intent, [Event("creative", said, data={"nothing": True})], False

    monster = room.monster if room.monster and room.monster.hp > 0 else None
    monster_def = content.monster(monster.key) if monster else None
    events: list[Event] = []
    if monster and not monster.hostile and HOSTILE & set(intent.success_effects):
        monster.hostile = True  # a stunt against a creature that wasn't fighting: it is now
        events.append(provoked(monster, content))
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
    bonuses += powers.roll_bonuses(state, content, "talk" if "pacify" in intent.success_effects else "creative")
    advantage = 1 if weak_hits or ("pacify" in intent.success_effects and "silver_tongue" in player.traits) else 0
    if weak_hits:
        intent = intent.model_copy(update={"success_effects": [UPGRADE.get(e, e) for e in intent.success_effects]})

    impossible = intent.difficulty == "absurd"
    roll = dice.check(rng, intent.stat, bonuses, DC.get(intent.difficulty, 13), advantage=advantage, impossible=impossible)
    verdict = "It works" if roll.success else "It fails"
    events.append(Event("check", f"You attempt to {summary}. {verdict}.", dice=roll,
                        data={"success": roll.success, "rerollable": could_change(state, intent),
                              "props": [p.name for p in props]}))
    if weak_hits and monster:
        tags = list(dict.fromkeys(t for _, t in weak_hits))  # (every one it plays on, not just the first: run 59)
        if roll.success:  # (told after a miss, it read as if the miss had worked: run 44)
            said = " and ".join(tags)
            events.append(Event("exploit", f"That's {the(monster.name)}'s weakness{'es' * (len(tags) > 1)}: {said}!"))
        for tag in tags:
            events += discover(state, monster, tag)
    events += fortune(state, roll)

    outcome: list[Event] = []
    for effect in intent.success_effects if roll.success else intent.failure_effects:
        target = state.room.monster
        if state.over:
            break
        if effect in MONSTER_EFFECTS and (target is None or target.hp <= 0 or not target.hostile):
            continue  # it's already dead, gone or calmed down
        outcome += _apply_effect(state, content, rng, effect, max(0, player.stat(intent.stat)))
    if any(e.kind in ("find", "secret") for e in outcome):  # not "nothing hidden here" and then a find (run 44)
        outcome = [e for e in outcome if not e.data.get("nothing")]
    events += outcome

    if roll.success and any(e.kind in CHANGES and not e.data.get("nothing") for e in outcome):
        events += _used_up(state, content, consumed, gold)
        player.bump("creative_win")
        for prop in props:
            if prop.kind == "feature":
                room.features[int(prop.key)].used = summary
            elif prop.kind == "fixture":
                room.creative_uses.append(f"prop:{prop.key}")
        room.remember(f"you tried to {summary}, and it worked")  # (what you did, not an order to do it)
        if props:
            events += interactions.flair(state)
    return intent, events, True


def could_change(state: GameState, intent: Intent) -> bool:
    """Whether a stunt that worked could change anything, and so is worth a Fate token to roll again: turning up a
    secret where nothing's hidden can't (as searching the room isn't, with nothing to find)."""
    return bool(set(intent.success_effects) - {"reveal_secret"}) or any(f.hidden for f in state.room.features)


def _used_up(state: GameState, content: Content, consumed: list[Prop], gold: int) -> list[Event]:
    """What a stunt that came to something used up: gone from your pack (or where it lay), and `gold` handed over."""
    player, room, events = state.player, state.room, []
    for prop in consumed:
        if prop.kind == "gold" and player.gold:
            paid = min(gold, player.gold)
            player.gold -= paid
            events.append(Event("spend", f"You part with {paid} gold."))
        elif prop.kind == "item" and prop.key in player.inventory:
            events.append(Event("spend", f"{cap(the(prop.name))} is used up.",
                                data=inventory.consume(state, prop.key, "spend")))
        elif prop.kind == "floor" and prop.key in room.items:
            events.append(Event("spend", f"{cap(the(prop.name))} is used up.",
                                data=inventory.consume(state, prop.key, "spend", "room")))
    return events


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
                               f"({max(monster.hp, 0)}/{monster.max_hp} HP left).", data={"damage": damage})]
        return events + (defeat(state, content, rng) if monster.hp <= 0 else [])
    if effect == "stun":
        monster.stunned = 2  # covers this turn's attack and the next, so a stun buys a free action
        monster.intent = "strike"
        player.bump("stuns")
        return [Event("stun", f"{cap(the(monster.name))} is stunned and loses its next two attacks.")]
    if effect == "pacify":  # (a character talked down is npcs.calm's: no reward, nothing lost)
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
        return [Event("info", "There turns out to be nothing hidden here.", data={"nothing": True})]
    if effect == "find_item":  # it lies there, to take or leave, like any find
        key = loot.give(rng, content, state.rares, rng.choice(loot.FINDS))
        if key is None:
            return [Event("info", "You turn up nothing worth keeping.", data={"nothing": True})]
        return [Event("find", f"You turn up {a(content.item(key).name)}.", data=inventory.lay(state, key, "find",
                                                                                            "stunt"))]
    if effect == "find_gold":
        gold = rng.randint(2, 8) * max(1, room.distance) + (4 if "scavenger" in player.perks else 0)
        player.gold += gold
        return [Event("find", f"You find {gold} gold.")]
    if effect == "heal_small":
        healed = min(dice.roll("1d4+2", rng), player.max_hp - player.hp)
        player.hp += healed
        return [Event("heal", f"You recover {healed} HP ({player.hp}/{player.max_hp}).")] if healed else []
    if effect in SELF_HARM:
        damage = dice.roll("1d4" if effect == "hurt_self_small" else "1d6+1", rng)
        player.hp = max(1, player.hp - damage)
        return [Event("hurt", f"You hurt yourself for {damage} damage ({player.hp}/{player.max_hp} HP).")]
    return []
