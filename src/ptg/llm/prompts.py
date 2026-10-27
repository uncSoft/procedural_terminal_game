"""Prompt text. Each turn sends a small, fresh snapshot of the game instead of an ever-growing chat history."""

from __future__ import annotations

import re
from collections import Counter

from .. import layout, statuses
from ..content import Content
from ..creative import available_props
from ..events import Action, Event
from ..intent import EFFECT_HELP
from ..models import GameState
from ..rules import exit_notes, ghost_truth
from ..scene import RoomView
from ..text import the

INTERPRETER_SYSTEM = """\
You are the rules interpreter for a text adventure. The player typed something; decide what they mean.
You do not narrate and you do not decide outcomes. Dice and rules do that. Reply with JSON only.

Choose `kind`:
- "action": the input clearly means one of the LISTED ACTIONS ("hit it", "go back", "grab the potion", "duck!").
  Put that action's id in `action_id`. Asking a creature that's stopped fighting what it knows (where secrets or
  treasure are, what's hidden, what to watch out for) is its `ask` action; talking or chatting with a character
  (hello, what's wrong, how are you) is its listed `talk:` action, and with anyone else, flavor. Changing what they
  hold or wear (wield, wear, swap, put on, take off), putting a thing down or selling it is never "creative": it's
  the listed equip:, unequip:, drop: or sell: action for that thing, and if none is listed for it, they don't have
  it: "flavor".
- "creative": the player attempts something not on the list that could plausibly change things: a trick, a stunt,
  using the room or an item in a new way, talking down / bribing / intimidating a monster, searching a specific spot.
  Choose `stat` (might = force, agility = speed/stealth/aim, wits = cleverness/persuasion/perception),
  a `difficulty`, and effects for success and failure.
- "flavor": harmless roleplay with no stakes (singing, posing, talking to yourself, admiring the decor).
- "question": an out-of-character question about their situation ("what am I carrying?", "where can I go?").

Difficulty: trivial (no roll needed), easy, medium, hard, absurd (impossible here: summoning dragons, using items
they don't have, instantly winning). Be fair but stingy. Effects must fit what is actually in the room and what the
attempt could realistically achieve. Most creative attacks are damage_small or stun, not damage_large.

`uses`: names of the things in the SCENE the attempt relies on, e.g. ["stew cauldron"]. Empty if none.
`consumes`: names of carried items or gold that the attempt uses up, e.g. ["Flask of Lamp Oil"]: anything thrown, drunk,
eaten, poured, splashed, burned, given away or spent. Whatever the player throws or pours goes here (and in `uses`).
Only name things that really appear in the SCENE; the player can't use things that aren't there.

`verb`, `subject`, `target`, `amount`: when the input plainly does one thing with one thing ("action" or "creative"),
what's done, with what, to what. `verb` is one of: throw, give, show, pour, use, open, smash, search, equip, unequip,
drop, sell (feeding, bribing and offering are give; drinking and eating are use, on "self"). `subject` is the SCENE id
of what they use (item:..., gear:weapon, bombs, keys, gold) and `target` the SCENE id of what they use it on
(monster:..., fixture:chest, exit:north, feature:2, self, room); `amount` is how much gold, 0 if not said.
"throw the cheese at the ghoul" is throw, item:cheese_wheel, monster:ghoul; "hand Lenny 5 gold" is give, gold,
monster:lucky_lenny, 5. Leave them "" (and 0) if nothing is used, or what's named isn't in the SCENE.

Effects:
{effects}

`summary` restates the attempt as a short verb phrase with no subject, e.g. "fling the stew cauldron at the goblin".
For "action", "flavor" and "question", still fill every field: stat "none", difficulty "trivial", empty lists, and
the use as above ("" and 0 if there's none).
"""

NARRATOR_SYSTEM = """\
You are the narrator of a dungeon-crawling text adventure. Your tone: {tone}.
Write in second person, present tense, as plain prose. No markdown, no lists, no headings, no options or
questions for the player. Keep it to {length}.

The FACTS were decided by dice and rules. Narrate them faithfully:
- Never contradict the facts, and never invent items, exits, monsters, damage or outcomes they don't state.
- Don't mention dice, rolls, difficulty numbers or hit point numbers. The game shows those separately.
- If an attempt failed, make the failure vivid or funny, never a lecture.
- RECENTLY is what happened before this turn; THIS TURN says where the player is now. Treat a room as
  familiar only if THIS TURN says they have been there before.
- The screen already shows the room's things, who is here and the ways out. Don't list them, and don't give
  directions or positions. Name one only when something happens to it this turn.
- When the player enters a room for the first time, set the mood from the room notes: the light, the air, the sound.
  A fight about to begin, or a secret room, is worth a line.
- When the player returns to a room they know, keep it brief: a line on how it feels now or what has changed, not
  the room all over again.
- The SETTING and the room notes are background for a first look: don't repeat their smells and sights every turn.
- Nothing moves, opens, shuts or changes hands unless the facts say so: no doors slam behind the player, and what's
  dropped or found stays where it lies ("not picked up" means it lies there still) until the facts say the player
  takes it. What the player holds and wears changes only when the facts say so too:
  never narrate a weapon drawn, swapped or put away, or armor put on or off.
- If a heavy blow is coming, end on the monster's wind-up so the player can react to it.
- If the player asked a question, answer it in character using only the facts and the player status.
- What a character says to the player is shown beside your words, in the character's own: never quote a character
  or make up what one says. Say what they do, at most that they speak.
"""

INTRO_SYSTEM = """\
You are the Void: a slightly unhinged, fond, sarcastic voice that greets adventurers before they descend.
Write one short paragraph (3 sentences at most) welcoming a player named {name} to a descent that begins in
{dungeon}. The key feature of the game: they can ignore the numbered choices and type anything they like, and the
dungeon will react. Encourage that, with humor. Plain text, no markdown.
"""

OFFLINE_INTRO = (
    "Welcome, {name}, to {dungeon}. The numbered choices are merely suggestions, polite ones, offered by a dungeon "
    "that knows it can't stop you. Type a number if you like. Or type whatever you want to try, and see what happens."
)

SUGGEST_SYSTEM = """\
You suggest ONE fun thing a player could try right now in a text adventure, picked from the IDEAS: things that would
really work here, the best first. Choose the most fun, and say it as a vivid imperative phrase of at most 9 words
that names the same thing and what it's done to, like "Splash the holy water in the ghoul's face" for "Throw the
Vial of Holy Water at the Ghoul". Add nothing the idea doesn't do, and never name any other item.
Reply with JSON: {"idea": N, "suggestion": "..."} where N is the idea's number. No numbers or quotes inside the
suggestion.
"""

LORE_SYSTEM = """\
Write a bestiary entry for a monster in a darkly funny dungeon crawler, as if scribbled by a long-dead
adventurer. Two sentences, at most 40 words. Hint at (but never state outright) what it is weak to.
Plain text only.
"""

EPITAPH_SYSTEM = """\
Write a one-line epitaph (at most 18 words) for a dungeon-crawler adventurer: for their tombstone if they died, or,
if they won and lived, the line carved under their statue in the Hall of Legends. Darkly funny, specific to what
happened to them. Call them by name or "they", never "he" or "she". Plain text, no quotes, no hashtags.
"""

RECAP_SYSTEM = """\
Write a "Previously..." recap for a text adventure the player is resuming, in second person, 2 sentences, from
the journal entries given. Plain text, no markdown.
"""

VOID_SYSTEM = """\
You are the Void, the sardonic, oddly affectionate voice that waits at the campfire between dungeon runs.
Write ONE line (at most 25 words) greeting the player, referencing what happened on their last run.
Plain text, no quotes.
"""


def props_line(state: GameState, content: Content) -> str:
    props = available_props(state, content)
    return "; ".join(f"{p.name} ({', '.join(p.tags)})" if p.tags else p.name for p in props) or "(none)"


def situation(state: GameState, content: Content, view: RoomView | None = None) -> str:
    """The game as it stands, for a model. With the room's `view` (for the interpreter), what's here and what's the
    player's is the SCENE: typed refs, by id (scene.RoomView.lines), bombs and small keys and how many among them;
    without it, the room's features, floor and fixture, and the PROPS a stunt could use."""
    room = state.room
    theme = content.themes[state.theme]
    lines = [f"Location: {room.name} ({theme.name}, floor {state.floor} of {state.floors_total})"]
    features = [f"{f.name} ({layout.where(f.pos)})" for _, f in room.visible_features()]
    if features and view is None:
        lines.append("Features: " + ", ".join(features))
    if room.items and view is None:
        lines.append("On the floor: " + ", ".join(content.item(k).name for k in room.items))
    if room.fixture and not room.fixture_used and view is None:
        lines.append(f"Fixture: {room.fixture}")
    lines.append(f"Exits: {exit_notes(state)}")
    if room.monster:
        monster = room.monster
        monster_def = content.monster(monster.key)
        traits = ", boss" if monster_def.boss else (", intelligent" if monster_def.intelligent else ", animal-minded")
        if monster.hostile:
            move = {"heavy": "winding up a HEAVY attack", "guard": "about to guard",
                    "strike": "about to attack"}[monster.intent]
            lines.append(f"Monster: {monster.name}, {monster.hp}/{monster.max_hp} HP, hostile{traits}, {move}")
        else:  # (calmed, its intent is still "strike": it isn't about to do anything)
            lines.append(f"Monster: {monster.name}, {monster.hp}/{monster.max_hp} HP, calm{traits}, watching you")
        if monster.ghost_of:
            lines.append(ghost_truth(monster))
        elif monster_def.desc:
            lines.append(f"About {the(monster_def.name)}: {monster_def.desc}")  # (not "the Lucky Lenny")
        known = state.known_weak.get(monster.key)
        if known:
            lines.append(f"Known weaknesses: {', '.join(known)}")
    lines.append(player_status(state, content))
    if view is None:
        lines.append(f"PROPS: {props_line(state, content)}")
    else:
        lines.append("SCENE (everything here, and everything theirs, by id):\n" + "\n".join(view.lines(tags=True)))
    lines.append(f"In combat: {'yes' if state.in_combat else 'no'}")
    return "\n".join(lines)


def player_status(state: GameState, content: Content) -> str:
    player = state.player
    weapon = content.item(player.weapon)
    armor = content.item(player.armor).name if player.armor else "none"
    carrying = ", ".join(content.item(k).name + (f" ×{n}" if n > 1 else "")
                         for k, n in Counter(player.inventory).items()) or "nothing"
    return (f"Player {player.name}: level {player.level}, HP {player.hp}/{player.max_hp}, might {player.might}, "
            f"agility {player.agility}, wits {player.wits}. Weapon: {weapon.name}. Armor: {armor}. "
            f"Carrying: {carrying}. Gold: {player.gold}. Bombs: {player.bombs}. Small keys: {player.keys}. "
            f"Fate tokens: {player.fate}.{ailing(state)}")


def ailing(state: GameState) -> str:
    """What ails the player, for the narrator (" Poisoned: ..."), or ""."""
    player = state.player
    told = [f" {statuses.DEFS[k].name}: {statuses.DEFS[k].blurb}" for k in player.statuses if k in statuses.DEFS]
    return "".join(told)


def suggestion_situation(state: GameState, content: Content) -> str:
    """What the suggester sees. Outside a fight, only the room and what's in it: shown what you carry, it kept
    suggesting you throw it (a Bag of Marbles, at everything)."""
    if state.in_combat:
        return situation(state, content)
    room = state.room
    theme = content.themes[state.theme]
    lines = [f"Location: {room.name} ({theme.name}, floor {state.floor} of {state.floors_total})"]
    features = [f"{f.name} ({layout.where(f.pos)})" for _, f in room.visible_features()]
    if features:
        lines.append("Features: " + ", ".join(features))
    if room.fixture and not room.fixture_used:
        lines.append(f"Fixture: {room.fixture}")
    props = [p for p in available_props(state, content) if p.kind == "feature"]
    lines.append("PROPS: " + ("; ".join(f"{p.name} ({', '.join(p.tags)})" if p.tags else p.name for p in props)
                              or "(none)"))
    lines.append("In combat: no")
    return "\n".join(lines)


HP_LEFT = re.compile(r" \((-?\d+)/(\d+) HP left\)")
TAKES_DAMAGE = re.compile(r" takes \d+ damage")
FOR_DAMAGE = re.compile(r" for \d+ damage")
# What the screen shows as numbers: XP and souls, counts "(2/3)" "(1 now)" "(88 left)" "(27/30 HP)" "(-3 HP)", and
# gear's dice and defense "(1d8+1 & goblin-bane)" "(1d6 → 1d10)" "(+2 defense)".
TALLY = re.compile(r" \+\d+ XP, \+\d+ souls\.| \+\d+ souls\.| \((?:\d+/\d+(?: HP)?|\d+ now|\d+ left|-\d+ HP)\)"
                   r"| \((?=[^)]*(?:\d+d\d+|\+\d))[^)]*\)")


def health_word(left: int, most: int) -> str:
    return ("down" if left <= 0 else "barely standing" if left <= most / 4 else "hurt" if left <= most * 0.6
            else "still strong")


def plain(fact: str, health: bool = True) -> str:
    """A fact as the narrator gets it: how hurt someone is in words (or, with `health` off, not at all), and none of
    the numbers the screen shows: damage, tallies, counts, dice and defense. Handed "(12/20 HP left)", it turned the
    numbers into prose ("restoring your strength to a manageable forty-one") and got them wrong, and "for 7 damage"
    came back as "seven points of pain" under the damage popup."""
    def hurt(match: re.Match) -> str:
        return f" ({health_word(int(match.group(1)), int(match.group(2)))})" if health else ""

    fact = TAKES_DAMAGE.sub(" takes a hit", FOR_DAMAGE.sub("", HP_LEFT.sub(hurt, fact)))
    return TALLY.sub("", fact)


def interpreter_messages(state: GameState, content: Content, raw: str, actions: list[Action],
                         view: RoomView | None = None) -> tuple[str, str]:
    effects = "\n".join(f"- {name}: {help_}" for name, help_ in EFFECT_HELP.items())
    listed = "\n".join(f"{a.id}: {a.label}" for a in actions) or "(none)"
    scene = situation(state, content, view or RoomView(state, content))
    user = f"SITUATION\n{scene}\n\nLISTED ACTIONS\n{listed}\n\nPLAYER TYPED\n{raw}"
    return INTERPRETER_SYSTEM.format(effects=effects), user


def this_turn(state: GameState, events: list[Event], opening: bool = False) -> str:
    """Where the player was and where they are now, spelled out so the model can't mix the two up."""
    room = the(state.room.name)
    arrived = next((e for e in events if e.kind in ("enter", "descend")), None)
    if opening:
        where = f"on floor {state.floor} of the dungeon" if state.test_room else "at the entrance of the dungeon"
        return f"the player has just arrived {where}, in {room}."
    if arrived is None:
        return f"the player is in {room}."
    known = "a room they have never been in before" if arrived.data.get("first") else "a room they have been in before"
    if arrived.kind == "descend":
        return f"the player has just come down the stairs to floor {state.floor} and is in {room}, {known}."
    left = the(state.rooms[state.prev_room_id].name)
    return f"the player has just left {left} and is now in {room}, {known}."


def narrator_messages(state: GameState, content: Content, raw: str, events: list[Event],
                      tone: str, question: bool = False, opening: bool = False) -> tuple[str, str]:
    """A small snapshot, oldest first: the setting, what happened before, where the player is now, the room as it
    stands, what they did, and the facts of what came of it."""
    theme = content.themes[state.theme]
    room = state.room
    arrived = next((e for e in events if e.kind in ("enter", "descend")), None)
    first_visit = opening or bool(arrived and arrived.data.get("first"))
    length = "3 to 5 sentences" if first_visit else ("1 to 3 sentences" if state.in_combat else "2 to 4 sentences")
    system = NARRATOR_SYSTEM.format(tone=tone, length=length)

    setting = f"SETTING: {theme.name}, floor {state.floor} of {state.floors_total}."
    lines = [f"{setting} {theme.blurb}" if first_visit else setting]  # said every turn, it got repeated every turn
    recent = state.journal[-6:]
    if recent:
        lines.append("RECENTLY (before this turn, oldest first):\n" + "\n".join(f"- {plain(line)}" for line in recent))
    lines.append(f"THIS TURN: {this_turn(state, events, opening)}")
    room_line = f"ROOM: {room.name}. Notes: {content.archetypes[room.archetype].blurb}"
    if room.monster and content.monster(room.monster.key).desc:  # a creature the model has never heard of
        room_line += f" About {the(room.monster.name)}: {content.monster(room.monster.key).desc}"
    lines.append(room_line)
    if raw:
        lines.append(f"PLAYER TYPED: {raw}")
    facts = [plain(e.text) for e in events]
    if question:
        facts.append(situation(state, content))
    lines.append("FACTS:\n" + ("\n".join(f"- {f}" for f in facts) if facts else "- Nothing changes."))
    return system, "\n\n".join(lines)
