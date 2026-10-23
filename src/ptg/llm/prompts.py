"""Prompt text. Each turn sends a small, fresh snapshot of the game instead of an ever-growing chat history."""

from __future__ import annotations

from .. import layout
from ..content import Content
from ..creative import available_props
from ..events import Action, Event
from ..intent import EFFECT_HELP
from ..models import GameState
from ..rules import exit_notes, room_facts
from ..text import the

INTERPRETER_SYSTEM = """\
You are the rules interpreter for a text adventure. The player typed something; decide what they mean.
You do not narrate and you do not decide outcomes. Dice and rules do that. Reply with JSON only.

Choose `kind`:
- "action": the input clearly means one of the LISTED ACTIONS ("hit it", "go back", "grab the potion", "duck!").
  Put that action's id in `action_id`.
- "creative": the player attempts something not on the list that could plausibly change things: a trick, a stunt,
  using the room or an item in a new way, talking down / bribing / intimidating a monster, searching a specific spot.
  Choose `stat` (might = force, agility = speed/stealth/aim, wits = cleverness/persuasion/perception),
  a `difficulty`, and effects for success and failure.
- "flavor": harmless roleplay with no stakes (singing, posing, talking to yourself, admiring the decor).
- "question": an out-of-character question about their situation ("what am I carrying?", "where can I go?").

Difficulty: trivial (no roll needed), easy, medium, hard, absurd (impossible here: summoning dragons, using items
they don't have, instantly winning). Be fair but stingy. Effects must fit what is actually in the room and what the
attempt could realistically achieve. Most creative attacks are damage_small or stun, not damage_large.

`uses`: names of the PROPS (from the list) the attempt relies on, e.g. ["stew cauldron"]. Empty if none.
`consumes`: names of carried items or gold that the attempt uses up (thrown, drunk, spent), e.g. ["Flask of Lamp Oil"].
Only list props that really appear in the PROPS list; the player can't use things that aren't there.

Effects:
{effects}

`summary` restates the attempt as a short verb phrase with no subject, e.g. "fling the stew cauldron at the goblin".
For "action", "flavor" and "question", still fill every field: stat "none", difficulty "trivial", empty lists.
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
- When the player enters a room for the first time, describe it from the room notes and mention every listed
  feature, item, exit direction and monster, woven naturally into prose. Use the positions given.
- When the player returns to a room they know, keep it brief: don't describe it all again or list its exits.
- If a heavy blow is coming, end on the monster's wind-up so the player can react to it.
- If the player asked a question, answer it in character using only the facts and the player status.
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
You suggest ONE creative, specific, fun action a player could try right now in a text adventure.
Use only the props and monster listed.
- In combat: use a prop against the monster in a clever way (topple it, throw it, trick it, bribe it).
  Props whose tags match the monster's known weaknesses are the best choice.
- Not in combat: suggest a curious way to investigate a specific feature (pry, climb, listen, read, poke,
  look under) that might reveal a secret. Never suggest throwing or using up carried items outside a fight.
Reply with JSON: {"suggestion": "..."} where the suggestion is an imperative phrase of at most 9 words,
e.g. "Kick the brazier over onto the goblin" or "Pry up the loose stones by the altar".
No numbers, no quotes inside.
"""

LORE_SYSTEM = """\
Write a bestiary entry for a monster in a darkly funny dungeon crawler, as if scribbled by a long-dead
adventurer. Two sentences, at most 40 words. Hint at (but never state outright) what it is weak to.
Plain text only.
"""

EPITAPH_SYSTEM = """\
Write a one-line epitaph (at most 18 words) for a dungeon-crawler adventurer's tombstone. Darkly funny, specific
to what happened to them. Plain text, no quotes, no hashtags.
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


def situation(state: GameState, content: Content) -> str:
    room = state.room
    theme = content.themes[state.theme]
    lines = [f"Location: {room.name} ({theme.name}, floor {state.floor} of {state.floors_total})"]
    features = [f"{f.name} ({layout.where(f.pos)})" for _, f in room.visible_features()]
    if features:
        lines.append("Features: " + ", ".join(features))
    if room.items:
        lines.append("On the floor: " + ", ".join(content.item(k).name for k in room.items))
    if room.fixture and not room.fixture_used:
        lines.append(f"Fixture: {room.fixture}")
    lines.append(f"Exits: {exit_notes(state)}")
    if room.monster:
        monster = room.monster
        monster_def = content.monster(monster.key)
        mood = "hostile" if monster.hostile else "not hostile"
        traits = ", boss" if monster_def.boss else (", intelligent" if monster_def.intelligent else ", animal-minded")
        move = {"heavy": "winding up a HEAVY attack", "guard": "about to guard", "strike": "about to attack"}[monster.intent]
        lines.append(f"Monster: {monster.name}, {monster.hp}/{monster.max_hp} HP, {mood}{traits}, {move}")
        if monster_def.desc:
            lines.append(f"About the {monster_def.name}: {monster_def.desc}")
        known = state.known_weak.get(monster.key)
        if known:
            lines.append(f"Known weaknesses: {', '.join(known)}")
    lines.append(player_status(state, content))
    lines.append(f"PROPS: {props_line(state, content)}")
    lines.append(f"In combat: {'yes' if state.in_combat else 'no'}")
    return "\n".join(lines)


def player_status(state: GameState, content: Content) -> str:
    player = state.player
    weapon = content.item(player.weapon)
    armor = content.item(player.armor).name if player.armor else "none"
    carrying = ", ".join(content.item(k).name for k in player.inventory) or "nothing"
    return (f"Player {player.name}: level {player.level}, HP {player.hp}/{player.max_hp}, might {player.might}, "
            f"agility {player.agility}, wits {player.wits}. Weapon: {weapon.name}. Armor: {armor}. "
            f"Carrying: {carrying}. Gold: {player.gold}. Fate tokens: {player.fate}.")


def interpreter_messages(state: GameState, content: Content, raw: str, actions: list[Action]) -> tuple[str, str]:
    effects = "\n".join(f"- {name}: {help_}" for name, help_ in EFFECT_HELP.items())
    listed = "\n".join(f"{a.id}: {a.label}" for a in actions) or "(none)"
    user = f"SITUATION\n{situation(state, content)}\n\nLISTED ACTIONS\n{listed}\n\nPLAYER TYPED\n{raw}"
    return INTERPRETER_SYSTEM.format(effects=effects), user


def this_turn(state: GameState, events: list[Event], opening: bool = False) -> str:
    """Where the player was and where they are now, spelled out so the model can't mix the two up."""
    room = the(state.room.name)
    arrived = next((e for e in events if e.kind in ("enter", "descend")), None)
    if opening:
        return f"the player has just arrived at the entrance of the dungeon, in {room}."
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

    lines = [f"SETTING: {theme.name}, floor {state.floor} of {state.floors_total}. {theme.blurb}"]
    recent = state.journal[-6:]
    if recent:
        lines.append("RECENTLY (before this turn, oldest first):\n" + "\n".join(f"- {line}" for line in recent))
    lines.append(f"THIS TURN: {this_turn(state, events, opening)}")
    room_line = f"ROOM: {room.name}. Notes: {content.archetypes[room.archetype].blurb}"
    if not (arrived or opening or question):  # on arrival the facts describe it; a question gets the situation
        room_line += f" Now: {room_facts(state, content)}"
    if room.monster and content.monster(room.monster.key).desc:  # a creature the model has never heard of
        room_line += f" About the {room.monster.name}: {content.monster(room.monster.key).desc}"
    lines.append(room_line)
    if arrived and not first_visit and room.description:
        lines.append(f"How you described it last time (for flavour; the facts win): {room.description}")
    if raw:
        lines.append(f"PLAYER TYPED: {raw}")
    facts = [e.text for e in events]
    if question:
        facts.append(situation(state, content))
    lines.append("FACTS:\n" + ("\n".join(f"- {f}" for f in facts) if facts else "- Nothing changes."))
    return system, "\n\n".join(lines)
