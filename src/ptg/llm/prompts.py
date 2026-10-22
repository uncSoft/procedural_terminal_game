"""Prompt text. Each turn sends a small, fresh snapshot of the game instead of an ever-growing chat history."""

from __future__ import annotations

from ..content import Content
from ..intent import EFFECT_HELP
from ..models import GameState
from ..rules import Action, Event

INTERPRETER_SYSTEM = """\
You are the rules interpreter for a text adventure. The player typed something; decide what they mean.
You do not narrate and you do not decide outcomes. Dice and rules do that. Reply with JSON only.

Choose `kind`:
- "action": the input clearly means one of the LISTED ACTIONS ("hit it", "go back", "grab the potion", "n").
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

Effects:
{effects}

`summary` restates the attempt as a short verb phrase with no subject, e.g. "fling the stew cauldron at the goblin".
For "action", "flavor" and "question", still fill every field: stat "none", difficulty "trivial", empty effect lists.
"""

NARRATOR_SYSTEM = """\
You are the narrator of a dungeon-crawling text adventure. Your tone: {tone}.
Write in second person, present tense, as plain prose. No markdown, no lists, no headings, no options or
questions for the player. Keep it to {length}.

The FACTS were decided by dice and rules. Narrate them faithfully:
- Never contradict the facts, and never invent items, exits, monsters, damage or outcomes they don't state.
- Don't mention dice, rolls, difficulty numbers or hit point numbers. The game shows those separately.
- If an attempt failed, make the failure vivid or funny, never a lecture.
- When the player enters a room for the first time, describe it from the room notes and mention every listed
  feature, item, exit direction and monster, woven naturally into the prose.
- If the player asked a question, answer it in character using only the facts and the player status.
"""

INTRO_SYSTEM = """\
You are a slightly unhinged narrator speaking from the void before a game begins. Write one short paragraph
(4 sentences at most) welcoming a player named {name} to {dungeon}. The key feature of the game: they can ignore
the numbered choices and type anything they like, and the dungeon will react. Encourage that, with humor.
Plain text, no markdown.
"""

OFFLINE_INTRO = (
    "Welcome, {name}, to {dungeon}. The numbered choices are merely suggestions, polite ones, offered by a dungeon "
    "that knows it can't stop you. Type a number if you like. Or type whatever you want to try, and see what happens."
)


def situation(state: GameState, content: Content) -> str:
    room = state.room
    theme = content.themes[state.theme]
    lines = [f"Location: {room.name} ({theme.name})"]
    features = [f.name for _, f in room.visible_features()]
    if features:
        lines.append("Features: " + ", ".join(features))
    if room.items:
        lines.append("On the floor: " + ", ".join(content.item(k).name for k in room.items))
    lines.append("Exits: " + ", ".join(f"{d} (locked)" if e.locked else d for d, e in room.exits.items()))
    if room.monster:
        monster_def = content.monster(room.monster.key)
        mood = "hostile" if room.monster.hostile else "not hostile"
        traits = ", boss" if monster_def.boss else (", intelligent" if monster_def.intelligent else ", animal-minded")
        lines.append(f"Monster: {room.monster.name}, {room.monster.hp}/{room.monster.max_hp} HP, {mood}{traits}")
    lines.append(player_status(state, content))
    lines.append(f"In combat: {'yes' if state.in_combat else 'no'}")
    return "\n".join(lines)


def player_status(state: GameState, content: Content) -> str:
    player = state.player
    weapon = content.item(player.weapon)
    armor = content.item(player.armor).name if player.armor else "none"
    carrying = ", ".join(content.item(k).name for k in player.inventory) or "nothing"
    return (f"Player {player.name}: level {player.level}, HP {player.hp}/{player.max_hp}, might {player.might}, "
            f"agility {player.agility}, wits {player.wits}. Weapon: {weapon.name}. Armor: {armor}. "
            f"Carrying: {carrying}. Gold: {player.gold}.")


def interpreter_messages(state: GameState, content: Content, raw: str, actions: list[Action]) -> tuple[str, str]:
    effects = "\n".join(f"- {name}: {help_}" for name, help_ in EFFECT_HELP.items())
    listed = "\n".join(f"{a.id}: {a.label}" for a in actions) or "(none)"
    user = f"SITUATION\n{situation(state, content)}\n\nLISTED ACTIONS\n{listed}\n\nPLAYER TYPED\n{raw}"
    return INTERPRETER_SYSTEM.format(effects=effects), user


def narrator_messages(state: GameState, content: Content, raw: str, events: list[Event],
                      tone: str, question: bool = False, opening: bool = False) -> tuple[str, str]:
    theme = content.themes[state.theme]
    room = state.room
    first_visit = opening or any(e.kind == "enter" and e.data.get("first") for e in events)
    length = "3 to 5 sentences" if first_visit else "2 to 4 sentences"
    system = NARRATOR_SYSTEM.format(tone=tone, length=length)

    notes = content.archetypes[room.archetype].blurb
    lines = [f"SETTING: {theme.name}. {theme.blurb} The player's goal: {theme.goal}",
             f"CURRENT ROOM: {room.name}. Room notes: {notes}"]
    if room.description and not first_visit:
        lines.append(f"How you described this room before: {room.description}")
    recent = state.journal[-6:]
    if recent:
        lines.append("RECENTLY:\n" + "\n".join(f"- {line}" for line in recent))
    if raw:
        lines.append(f"PLAYER TYPED: {raw}")
    facts = [e.text for e in events]
    if question:
        facts.append(situation(state, content))
    lines.append("FACTS:\n" + ("\n".join(f"- {f}" for f in facts) if facts else "- Nothing changes."))
    return system, "\n\n".join(lines)
