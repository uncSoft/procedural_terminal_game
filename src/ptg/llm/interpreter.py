"""Turns whatever the player typed into an Intent. Obvious commands are matched locally (no model call);
everything else goes to the language model, with the keyword matcher as the fallback.

The keyword matcher reads a use of one thing on another as the interaction grid reads a stunt (interactions.read, on
the room's scene.RoomView): what's done (the verb), with what (the subject: what the verb is done to, by its own
name, never by the name of whoever it's aimed at), at what (the target), and how much gold. What that comes to is the
grid's to say. So "throw the cheese at the ghoul" throws the cheese, not the first thing whose label has the ghoul's
name in it; a throw is never a drink; "smoke bomb" is the Smoke Bomb, never one of your bombs; "unlock the chest" uses
your key and "pick the lock" picks it. Handing something over (give, feed, bribe, calm him down...) or naming a
character is never sure enough to skip the model: it may know better. While Swoogy waits for a guess, a number is the
guess (guessed); "look around" is a free look (looks), and only searching searches the room.

The model is shown the room as typed refs (prompts.situation's SCENE) and may say a use of its own, as the Intent's
`verb`, `subject`, `target` and `amount`: grounded puts them in the grid's terms.
"""

from __future__ import annotations

import difflib
import re

from pydantic import ValidationError

from .. import interactions, inventory
from ..content import Content
from ..events import Action
from ..intent import Intent, intent_schema
from ..interactions import Clause, Row, Use, use_id
from ..inventory import DROP_WORDS
from ..models import GameState
from ..rules import unavailable
from ..scene import PRONOUNS, Ref, RoomView, words as named_by
from .base import LLM, LLMError
from .prompts import interpreter_messages

DIRECTION_ALIASES = {"n": "north", "s": "south", "e": "east", "w": "west"}
MOVE_WORDS = {"go", "walk", "head", "move", "travel", "enter", "proceed"}
ATTACK_WORDS = {"attack", "hit", "strike", "stab", "fight", "kill", "swing", "slash", "smack", "punch", "kick"}
FLEE_WORDS = {"flee", "run", "escape", "retreat"}
FLEE_PHRASES = ("get out", "get away", "run for it", "run away", "back off")  # (said whole, they're a getaway)
REST_WORDS = {"rest", "sleep", "nap", "camp", "sit"}
TAKE_WORDS = {"take", "grab", "pick", "get", "loot", "collect"}
USE_WORDS = {"drink", "quaff", "eat", "use", "consume", "chug"}  # as it is, or on yourself: never "throw"
THROW_WORDS = {"throw", "toss", "hurl", "fling", "lob", "chuck"}
SEARCH_WORDS = {"search", "examine", "check", "inspect", "open", "investigate", "rummage", "look"}  # (a feature)
ROOM_SEARCH = {"search", "rummage", "investigate", "scour", "ransack"}  # the only words that search the room itself
SECRET_WORDS = {"secret", "secrets", "hidden", "passage", "passages"}  # ...or these, said with any searching word
ROOM_WORDS = {"room", "around", "everywhere", "place"}
LOOK_WORDS = {"look", "peer", "glance", "gaze", "survey", "scan", "examine", "check", "inspect", "observe"}
AROUND = {"around", "about", "round", "room", "here", "this", "place", "surroundings", "everything", "again", "at",
          "the", "a", "bit", "carefully", "closely", "quickly", "me", "my", "whole"}  # "look around the room": a look
DODGE_WORDS = {"dodge", "duck", "evade", "sidestep", "roll", "jump"}
DISTRACT_WORDS = {"distract", "wave", "shine", "squeak", "pop", "show"}
SAID_AS = {"light": "use", "ignite": "use", "activate": "use"}  # typed verbs the grid knows as another
# What you do with what you carry (inventory.moves): the first word, or the first two. ("Brandish" isn't one: brandish
# your sword at the goblin, and that's a stunt.)
EQUIP_WORDS = {"equip", "wield", "wear", "don", "swap", "switch", "ready", "put on", "change into", "swap to",
               "switch to"}
UNEQUIP_WORDS = {"unequip", "remove", "doff", "take off"}
SELL_WORDS = {"sell", "pawn", "flog"}
MOVES = (("unequip:", UNEQUIP_WORDS), ("equip:", EQUIP_WORDS), ("drop:", DROP_WORDS), ("sell:", SELL_WORDS))
CARRY_PREFIXES = tuple(prefix for prefix, _ in MOVES)
SPLIT_MOVES = {("put", "down"): "drop:", ("set", "down"): "drop:", ("take", "off"): "unequip:", ("put", "on"): "equip:"}
# The verbs that can't be about anything but a thing you carry ("wield", not "leave" or "switch"): with nothing you
# carry by that name, you're told so (the engine's "equip:"), not narrated doing it. Nor after "drop to the floor".
SURE_WORDS = {"equip", "wield", "wear", "don", "put on", "unequip", "doff", "take off", "drop", "discard", "put down",
              "set down", "throw away", "toss away", "sell", "pawn"}
NOT_A_THING = {"to", "down", "into", "onto", "back", "out", "off", "dead", "low", "flat", "in", "on", "over", "room"}
# Where the thing a move is done to ends: "leave the room | with the war pick", "remove the cobwebs | from my shirt".
OBJECT_ENDS = {"with", "from", "in", "into", "on", "onto", "to", "at", "and", "then", "but", "or", "for", "over",
               "under", "by", "near", "behind", "against", "while", "before", "after", "until", "so", "as"}
ARTICLES = {"the", "a", "an", "my", "your", "his", "her", "its", "this", "that", "some", "our"}
AFTER_A_MOVE = {"here", "there", "now", "please", "quickly", "again"}  # said after the thing, they change nothing
SLOT_WORDS = {"armor": "(worn)", "armour": "(worn)", "weapon": "(in hand)", "weapons": "(in hand)",
              "helm": "(on head)", "helmet": "(on head)", "hat": "(on head)"}  # inventory.WORN
TAKE_OFF = {"(worn)": "unequip:armor", "(on head)": "unequip:helm"}  # what you wear, by its mark
ASK_WORDS = {"ask", "question", "inquire", "interrogate", "quiz", "pester"}
TALK_WORDS = {"talk", "chat", "speak", "greet", "hello", "hi", "hey", "hiya", "howdy", "converse", "chatter"}
WATCH_WORDS = {"watch", "follow", "observe", "trail"}
TIP_WORDS = {"secret", "secrets", "hidden", "hide", "treasure", "loot", "stash", "know", "knows", "rumor", "rumors",
             "rumour", "rumours", "gossip", "lore", "where", "tip", "tips"}
FIXTURE_WORDS = {  # (a chest's are by what's done to it: CHEST_VERBS)
    "descend": {"descend", "downstairs", "stairs"},
    "shrine_pray": {"pray", "kneel", "curse", "curses", "bless"},
    "shrine_blood": {"blood", "bleed"},
    "shrine_gold": {"gold", "coins", "pay"},
    "fountain": {"fountain", "basin"},
    "shop": {"shop", "browse", "wares", "buy", "trade", "barter", "haggle", "merchant", "counter"},
}
CHEST_WORDS = {"chest", "lock", "trunk", "lid", "padlock"}
CHEST_VERBS = (("chest_bomb", {"bomb", "bombs", "blast", "blow"}),
               ("chest_smash", {"smash", "break", "kick", "bash", "force", "pry", "prise", "crack", "hack", "batter",
                                "bust", "wrench", "lever"}),
               ("chest_key", {"unlock", "key", "keys"}),
               ("chest", {"pick", "lockpick", "jimmy"}))
NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}
GUESS_WORDS = {"i", "guess", "say", "pick", "choose", "it's", "its", "it", "is", "the", "number", "maybe", "um", "er",
               "go", "with", "for", "think", "how", "about", "my", "hmm", "ok", "okay", "then", "a", "i'll", "i'm"}
STOPWORDS = {"the", "a", "an", "of", "to", "with", "at", "my", "your", "in", "on", "for", "it", "up", "into", "and"}
QUESTION_STARTS = ("what", "where", "how", "who", "why", "which", "am i", "do i", "can i", "is there", "are there")
VERBS = interactions.GRID_VERBS | interactions.CARRY  # what a use's verb may be
AS_VERB = {"eat": "use", "distract": "show", "bomb": "use"}  # (what interactions.verb_class says, as one of VERBS)


def _action(action_id: str) -> Intent:
    return Intent(kind="action", action_id=action_id, difficulty="trivial")


def _words(text: str) -> list[str]:
    """The words of something said or a label: "pick the chest's lock" -> pick, the, chest, lock."""
    return [w.removesuffix("'s") for w in re.findall(r"[a-z']+", text.lower())]


def _best_target(words: list[str], actions: list[Action], prefix: str) -> Action | None:
    """The action of a kind (`prefix`) whose thing some words name best: by the words of the thing it's about
    (_about), never of whoever it's aimed at, so "throw the cheese at the ghoul" is no throw of the holy water."""
    best, best_score = None, 0
    said = set(words)
    for action in actions:
        if not action.id.startswith(prefix):
            continue
        score = len(_about(action.label) & said)
        if score > best_score:
            best, best_score = action, score
    return best


def _about(label: str) -> set[str]:
    """The words of what an action's label is about: "Throw the Vial of Holy Water at the Ghoul" is about the vial,
    "Distract the Ghoul with the Laser Pointer" the pointer, "Equip the War Pick (1d6 → 1d10)" the pick."""
    label = label.lower().split(" (")[0]  # just the thing: not "(1d6 → 1d10)" nor "(in hand)"
    head, with_, tail = label.partition(" with ")
    said = _words(tail) if with_ else _words(head.partition(" at ")[0])[1:]
    return {w for w in said if w not in STOPWORDS}


def _carried(raw: str, words: list[str], actions: list[Action]) -> tuple[Intent, bool] | None:
    """What you do with what you carry (inventory.moves): "wield the hand axe", "take the chain shirt off", "put the
    bread down", "sell my armor". Only what the verb is done to counts, the words straight after it up to a
    preposition or an "and": "leave the room with the war pick" leaves the room, "remove the cobwebs from my chain
    shirt" the cobwebs, "drop down and eat the bread" nothing, and "leave with the potion" or "leave the chain shirt
    on" aren't leaving anything. With more said after the thing, the model may know better. None if it's none of
    those."""
    tail = words[:-1] if len(words) > 2 and words[-1] in ("here", "there") else words  # "leave the bread here"
    split = SPLIT_MOVES.get((words[0], tail[-1])) if len(tail) > 2 else None
    for prefix, verbs in MOVES:
        if split == prefix:
            verb, said = f"{words[0]} {tail[-1]}", tail[1:-1]
        else:
            verb = next((v for v in (" ".join(words[:2]), words[0]) if v in verbs), None)
            said = words[len(verb.split()):] if verb else []  # (not "off" from "take off")
        if verb is None:
            continue
        end = next((i for i, word in enumerate(said) if word in OBJECT_ENDS), len(said))
        target, after = said[:end], said[end:]
        thing = [word for word in target if word not in ARTICLES]
        if prefix == "drop:" and (not thing or after[:1] == ["on"]):
            return Intent(kind="flavor", summary=raw.strip()), False
        if thing and thing[0] in NOT_A_THING:  # "wear down the door", "leave the room quietly"
            return Intent(kind="flavor", summary=raw.strip()), False
        match = _best_target(target, actions, prefix) or _slot(target, actions, prefix)
        if match:
            return _action(match.id), not set(after) - AFTER_A_MOVE
        if thing and (verb in SURE_WORDS or {w for w in thing if w in SLOT_WORDS}):
            return _action(prefix), False  # nothing you carry by that name: the engine says so (the model may know)
        return Intent(kind="flavor", summary=raw.strip()), False
    return None


def _slot(words: list[str], actions: list[Action], prefix: str) -> Action | None:
    """"Drop my armor", "sell my weapon", "take off my helmet": what you have on in that slot (inventory.moves marks
    it). Not to equip: "swap weapons" means one in your pack, not the one in your hand."""
    marks = tuple({SLOT_WORDS[w] for w in words if w in SLOT_WORDS})
    if not marks or prefix == "equip:":
        return None
    if prefix == "unequip:":
        return next((a for a in actions if a.id in {TAKE_OFF.get(m) for m in marks}), None)
    return next((a for a in actions if a.id.startswith(prefix) and a.label.endswith(marks)), None)


def guessed(raw: str, actions: list[Action]) -> str | None:
    """While Swoogy waits for a guess (his guess:1-6 are among the actions), the guess some words make: a bare "3",
    "four", "i guess three", "6!". None if he isn't guessing, or it isn't one number from 1 to 6."""
    if "guess:1" not in {a.id for a in actions}:
        return None
    said = re.findall(r"[a-z0-9']+", raw.lower())
    numbers = {int(w) if w.isdigit() else NUMBERS[w] for w in said if w.isdigit() or w in NUMBERS}
    if len(numbers) != 1 or any(not (w.isdigit() or w in NUMBERS) and w not in GUESS_WORDS for w in said):
        return None
    number = numbers.pop()
    return f"guess:{number}" if 1 <= number <= 6 else None


def looks(raw: str) -> bool:
    """Whether some words only ask to look around: "look", "look around", "check the room", "examine room". That's
    the Look panel's (or a free look: the narrator describes the room), never the room's one search."""
    said = _words(raw)
    said = said[1:] if said[:1] == ["i"] else said
    return bool(said) and said[0] in LOOK_WORDS and set(said[1:]) <= AROUND and \
        (said[0] == "look" or len(said) == 1 or "room" in said or "around" in said)


def offline_interpret(raw: str, actions: list[Action], view: RoomView | None = None) -> tuple[Intent, bool]:
    """Keyword matching. Returns the intent and whether it's confident enough to skip the language model. With the
    room's `view`, a use of one thing on another is read as the grid reads it (see the module's docstring)."""
    text = raw.lower().strip(" .!")
    guess = guessed(raw, actions)
    if guess:
        return _action(guess), True
    words = _words(text)
    if not words:
        return Intent(kind="flavor"), False
    labels = {a.label.lower(): a for a in actions}
    if text in labels:
        return _action(labels[text].id), True
    intent, confident = _match(raw, text, words, actions, view)
    said_to = _character_named(view, words) and not intent.action_id.startswith(("talk:", "sell:"))
    if confident and (_handing(words) or said_to):  # (talking to her, or selling her something, is just that)
        confident = False  # (who it's for, or what it means to them: the model may know better)
    return intent, confident


def _match(raw: str, text: str, words: list[str], actions: list[Action],
           view: RoomView | None) -> tuple[Intent, bool]:
    ids = {a.id for a in actions}
    short = len(words) <= 3
    if looks(raw):  # a free look, never the room's search
        return Intent(kind="question", summary=raw.strip()), True
    if _bomb_said(words, actions, view):  # "bomb the east wall", "blow up the west wall", in a fight "throw a bomb"
        for word in words:
            if f"bomb:{DIRECTION_ALIASES.get(word, word)}" in ids:
                return _action(f"bomb:{DIRECTION_ALIASES.get(word, word)}"), True
        if CHEST_WORDS & set(words) and _chest_here(ids, view):
            return _action("chest_bomb"), True
        if "bomb" in ids:
            return _action("bomb"), True
    for word in words:
        direction = DIRECTION_ALIASES.get(word, word)
        if f"go:{direction}" in ids and (short or words[0] in MOVE_WORDS):
            return _action(f"go:{direction}"), short
    chest = _chest(words, ids, view)
    if chest:
        return _action(chest), True
    if words[0] in ATTACK_WORDS and "attack" in ids and not _at_a_thing(text, view):
        return _action("attack"), len(words) <= 4 and not _carried_named(text, view)
    if words[0] in DODGE_WORDS and "dodge" in ids:
        return _action("dodge"), len(words) <= 3
    fixture = _fixture(words, ids, view)
    if fixture:
        return _action(fixture), True
    if (FLEE_WORDS & set(words) or any(p in text for p in FLEE_PHRASES)) and "flee" in ids:
        # Sure of it when it's short, or plainly a getaway naming nothing in the room ("get out of here, run!"
        # was a dodge to a small model): "run past the goblin to the chest" is the model's to read.
        return _action("flee"), short or (len(words) <= 6 and view is not None and not named_by(text) & {
            w for ref in view.refs for w in named_by(ref.name)})
    if words[0] in REST_WORDS and "rest" in ids:
        return _action("rest"), short
    carried = _carried(raw, words, actions)
    if carried:
        return carried
    if words[0] in TAKE_WORDS:
        match = _best_target(words[1:], actions, "take:")
        if match:
            return _action(match.id), True
    if words[0] in USE_WORDS and not _aimed_said(text):  # "drink the potion", "use the smoke bomb" (on nothing)
        match = _best_target(words[1:], actions, "use:") or _best_target(words[1:], actions, "reveal:")
        if match:
            return _action(match.id), True
    if view is not None:
        grid = _grid(text, view, actions)
        if grid:
            return grid
    elif words[0] in THROW_WORDS:  # (no view of the room: by the thing thrown alone)
        match = _best_target(words[1:], actions, "throw:")
        if match:
            return _action(match.id), True
    if words[0] in DISTRACT_WORDS:
        match = _best_target(words[1:], actions, "distract:")
        if match:
            return _action(match.id), True
    talks = [a for a in actions if a.id.startswith("talk:")]
    if talks and words[0] in TALK_WORDS:  # a character: "talk to lenny", "hello granny" (their own words, no turn)
        match = _best_target(words, talks, "talk:") or (talks[0] if len(talks) == 1 else None)
        if match:
            return _action(match.id), True
    if "ask" in ids:  # a calm creature: "ask the goblin about secrets", "watch the rat" (small talk isn't asking)
        if words[0] in ASK_WORDS and (TIP_WORDS & set(words) or len(words) <= 3):
            return _action("ask"), True
        if words[0] in WATCH_WORDS and (_best_target(words, actions, "ask") or len(words) <= 2):
            return _action("ask"), True
    if words[0] in SEARCH_WORDS:
        searching = words[0] in ROOM_SEARCH and (ROOM_WORDS & set(words) or len(words) == 1)
        if "search_room" in ids and (searching or SECRET_WORDS & set(words)):  # (only searching: not a look)
            return _action("search_room"), short or bool(SECRET_WORDS & set(words))
        match = _best_target(words[1:], actions, "search:")
        if match:
            return _action(match.id), True
    close = _close(text, words, actions)
    if close:
        return _action(close.id), True
    how = _say_how(text, view)
    if how:
        return _action(how), False
    if text.endswith("?") or text.startswith(QUESTION_STARTS):
        return Intent(kind="question", summary=raw), False
    return Intent(kind="flavor", summary=raw.strip()), False


def _handing(words: list[str]) -> bool:
    """Whether some words hand something over: give, hand, feed, offer, pay, bribe, calm him down..."""
    lead = words[1:] if words[:1] == ["i"] else words
    return bool(lead) and interactions.verb_class(lead[0]) == "give"


def _character_named(view: RoomView | None, words: list[str]) -> bool:
    """Whether some words are about a character here, by name or as "him": Lucky Lenny, Swoogy, a shopkeeper."""
    if view is None:
        return False
    who = view.match(named_by(" ".join(words)), ("monster", "keeper"))
    return who is not None and (who.kind == "keeper" or who.state["npc"])


def _bomb_said(words: list[str], actions: list[Action], view: RoomView | None) -> bool:
    """Whether a bomb is what's said: "bomb" on its own, never in a thing's name ("smoke bomb" is the Smoke Bomb,
    whether you have one or not); or "blast", or "blow ... up", for what's done ("blast the wall", "blow it up"; not
    "blow a kiss")."""
    said = [_one(w) for w in words]
    names = [item.name for item in view.content.items.values()] if view is not None else \
        [a.label for a in actions if a.id.partition(":")[0] in ("use", "throw", "take", "drop", "sell", "appease")]
    for name in names:
        named = [_one(w) for w in (_words(name) if view is not None else sorted(_about(name))) if w not in STOPWORDS]
        if len(named) > 1 and "bomb" in named and all(w in said for w in named):
            for word in named:
                said.remove(word)
    lead = words[1:] if words[:1] == ["i"] else words
    return "bomb" in said or lead[:1] == ["blast"] or (lead[:1] == ["blow"] and "up" in lead)


def _one(word: str) -> str:
    """A word as one of a thing: "bombs" is "bomb"."""
    return word[:-1] if word.endswith("s") and len(word) > 3 and not word.endswith("ss") else word


def _chest_here(ids: set[str], view: RoomView | None) -> bool:
    return bool({"chest", "chest_key", "chest_smash"} & ids) or bool(view and view.get("fixture:chest"))


def _chest(words: list[str], ids: set[str], view: RoomView | None) -> str | None:
    """What's done to the chest here, by its verb (CHEST_VERBS): "unlock the chest" (or anything with a key) is your
    small key, "smash" or "kick" it forcing it, "pick the lock" picking it, and "open it" your key if you have one,
    else picking it. None if the chest isn't named (or there's none)."""
    if not CHEST_WORDS & set(words) or not _chest_here(ids, view):
        return None
    for action_id, verbs in CHEST_VERBS:
        if verbs & set(words) and not (action_id == "chest" and "up" in words):  # (not "pick up")
            return action_id
    return ("chest_key" if "chest_key" in ids else "chest") if "open" in words else None


def _fixture(words: list[str], ids: set[str], view: RoomView | None) -> str | None:
    """The room's fixture's action that some words say, by what's said of it (FIXTURE_WORDS), short or said first:
    "descend", "pray at the shrine", "kneel and pray", "lift the curse", "drink from the fountain". Praying at a
    shrine with no curse to lift is told why not."""
    for action_id, keywords in FIXTURE_WORDS.items():
        here = action_id in ids or (action_id == "shrine_pray" and view is not None and view.get("fixture:shrine"))
        first = words[0] in keywords or (action_id == "descend" and words[0] not in THROW_WORDS | USE_WORDS) or \
            (action_id == "fountain" and words[0] in USE_WORDS)  # "go down the stairs", "drink from the fountain"
        if here and keywords & set(words) and (len(words) <= 3 or first):
            return action_id
    return "fountain" if words == ["drink"] and "fountain" in ids else None


def _at_a_thing(text: str, view: RoomView | None) -> bool:
    """Whether a blow is aimed at a thing, not a creature: "kick the door", "hit the cauldron"."""
    if view is None:
        return False
    said = named_by(text)
    return view.match(said, ("monster",)) is None and \
        view.match(said, ("fixture", "feature", "exit", "wall", "floor", "ware")) is not None


def _carried_named(text: str, view: RoomView | None) -> bool:
    """Whether some words name a thing in your pack ("hit it with the cheese"): more than just a blow."""
    return view is not None and view.match(named_by(text), ("item",)) is not None


def _aimed_said(text: str) -> bool:
    """Whether what's said is aimed at something: "use the potion on the ghoul", not "use the potion"."""
    parts = interactions.clauses(text)
    return bool(parts and parts[0].aimed())


def _said(text: str) -> str:
    """Typed words, as the grid reads a stunt's: a verb it knows for one it doesn't (SAID_AS: "light the smoke bomb"
    is using it)."""
    said = text.split()
    i = 1 if said[:1] == ["i"] else 0
    if len(said) > i and said[i] in SAID_AS:
        said[i] = SAID_AS[said[i]]
    return " ".join(said)


def _grid(text: str, view: RoomView, actions: list[Action]) -> tuple[Intent, bool] | None:
    """A use of one thing on another, read as the interaction grid reads it (interactions.read), and the action it
    comes to here: a listed one if one does just that ("throw:holy_water", "lenny"), else the grid's own whole use
    ("throw:cheese_wheel@monster:ghoul", which says why not if it can't be, at no cost). Sure of it only when it can
    be done and the words name just what's used and what at. None if the words aren't plainly one use the grid has
    a row for."""
    state, content = view.state, view.content
    said = _said(text)
    parts = interactions.clauses(said)
    use = interactions.read(view, said) or _paid(view, parts)
    if use is None:
        return None
    if use.verb in interactions.CARRY:  # "put away my sword and wield the war pick"
        action_id = interactions.carry_id(state, content, use)
        return (_action(action_id), False) if action_id else None
    use = _named_item(view, said, use)
    if use.verb == "throw" and use.target.startswith(("monster:", "keeper:")) and _tossed_to(parts[0]):
        use = Use("give", use.subject, use.target, use.amount)  # "throw the potion to swoogy": a gift
    if use.verb == "give" and not use.target and parts[0].aimed():  # "offer the tooth at the shrine"
        to = view.match(named_by(" ".join(parts[0].aimed())), interactions.AIMS["give"])
        use = Use("give", use.subject, to.id if to else "", use.amount)
    row, use = _aimed(view, use)
    if row is None:
        return None
    listed = {a.label.lower(): a.id for a in actions}
    action_id = row.alias or listed.get(row.label.lower()) or use_id(use.verb, use.subject, use.target, use.amount)
    return _action(action_id), row.works and len(parts) == 1 and _just(view, parts[0], use)


def _paid(view: RoomView, parts: list[Clause]) -> Use | None:
    """"Pay swoogy", "bribe the goblin": with gold, as much as it'd take."""
    if len(parts) != 1 or not interactions.forms(parts[0].verb) & {"pay", "bribe"} or not view.get("gold"):
        return None
    target = view.match(named_by(" ".join(parts[0].obj)), ("monster", "keeper"))
    return Use("give", "gold", target.id if target else "", interactions.amount_said(parts[0].obj))


def _named_item(view: RoomView, said: str, use: Use) -> Use:
    """A use read as one of your bombs or small keys that names a thing by its whole name ("throw the smoke bomb",
    "use the reliquary key on the door"): that thing, had or not (the grid says if you haven't it)."""
    if use.subject not in inventory.PICKUPS:
        return use
    words = named_by(said)
    for key, item in view.content.items.items():
        named = named_by(item.name)
        if key not in inventory.PICKUPS and len(named) > 1 and named & {"bomb", "key"} and named <= words:
            return Use(use.verb, key, use.target, use.amount)
    return use


def _tossed_to(part: Clause) -> bool:
    """Whether a throw's said to be to someone ("throw the bone to the dog"), not at them."""
    return next((prep for prep, _ in part.phrases if prep in interactions.AIMED), "") == "to"


def _aimed(view: RoomView, use: Use) -> tuple[Row | None, Use]:
    """What a use comes to (interactions.plan), and the use: one with nothing it's aimed at is aimed where it would do
    something, of where it might go: a throw at whoever you're fighting (else down here), a gift to whoever's here,
    anything else on yourself, the monster you're fighting, the room's fixture or the room ("use the laser pointer"
    in a fight shows it to the monster, "use the key" opens the chest)."""
    state, content = view.state, view.content
    if use.target or not use.subject:
        return interactions.plan(state, content, use, view), use
    fight = view.monster if state.in_combat else None
    if use.verb == "throw":
        aims = [fight or view.get("room")]
    elif use.verb in ("give", "show"):
        aims = [view.monster, view.keeper]
    else:
        aims = [view.get("self"), fight] + view.of("fixture") + [view.get("room")]
    found: tuple[Row | None, Use] = (None, use)
    for ref in (r for r in aims if r is not None):
        aimed = Use(use.verb, use.subject, ref.id, use.amount)
        row = interactions.plan(state, content, aimed, view)
        if row is not None and row.works:
            return row, aimed
        if row is not None and found[0] is None:
            found = (row, aimed)
    return found


def _just(view: RoomView, part: Clause, use: Use) -> bool:
    """Whether the thing a verb is done to is just what's used (or used on), and nothing else: "throw the cheese at
    the ghoul", not "throw the moldy cheese" (no cheese is moldy here) or "throw the cheese and the pickle"."""
    named = set(PRONOUNS) | interactions.FILLER
    for ref in (_ref_of(view, use.subject), view.get(use.target) if use.target else None):
        if ref is not None:
            named |= ref.words()
    return not named_by(" ".join(part.obj)) - named


def _ref_of(view: RoomView, key: str) -> Ref | None:
    """The ref of what a use's subject names: something you carry or that lies here, a bomb, a small key, gold."""
    counters = {"bomb": "bombs", "small_key": "keys", "gold": "gold"}
    if not key:
        return None
    if key in counters:
        return view.get(counters[key])
    return view.get(f"item:{key}") or next((r for r in view.of("gear", "floor") if r.key == key), None)


def _close(text: str, words: list[str], actions: list[Action]) -> Action | None:
    """A label near enough to what's said to be a slip of the fingers ("atack the gobin"): every word said is in it,
    or nearly. Not one that only reads alike: "offer the tooth at the shrine" is no "Offer blood at the shrine". Nor a
    move with what you carry: "drink the healing potion" at full health is almost "Drop the Healing Potion", "hold the
    war pick" at a shop almost "Sell the War Pick". Those are only what they say (_carried)."""
    loose = {a.label.lower(): a for a in actions if not a.id.startswith(CARRY_PREFIXES)}
    for label in difflib.get_close_matches(text, list(loose), n=3, cutoff=0.8):
        named = _words(label)
        if all(w in STOPWORDS or w in named or difflib.get_close_matches(w, named, n=1, cutoff=0.75) for w in words):
            return loose[label]
    return None


def _say_how(text: str, view: RoomView | None) -> str | None:
    """In a fight, words about a thing in your pack that come to nothing the grid knows ("sniff the potion", "wave the
    cheese about"): what it could do here instead, a picker of them (interactions.choices), which costs nothing. Not
    words the monster gets a free swing for. None out of a fight, or if nothing it could do would work."""
    if view is None or not view.state.in_combat:
        return None
    parts = interactions.clauses(_said(text))
    thing = view.match(named_by(" ".join(parts[0].obj)), ("item",)) if parts and parts[0].obj else None
    if thing is None:
        return None
    picker = use_id("use", thing.key)
    works = [o for o in interactions.choices(view.state, view.content, picker) if o.hint != interactions.NO]
    return picker if works else None


async def interpret(llm: LLM | None, state: GameState, content: Content, raw: str,
                    actions: list[Action], trust_keywords: bool = True) -> tuple[Intent, str | None]:
    """Returns the intent and, if the model failed, an error message for the log. Commands the keyword matcher is
    sure of skip the model, unless `trust_keywords` is off (when checking what the model itself makes of them)."""
    view = RoomView(state, content)
    fallback, confident = offline_interpret(raw, actions, view)
    if confident and fallback.action_id in {a.id for a in unavailable(state, content)}:
        confident = False  # (it can't be done now, and says why: but the words may mean something else to the model)
    if llm is None or (confident and trust_keywords):
        return fallback, None
    system, user = interpreter_messages(state, content, raw, actions, view)
    try:
        intent = Intent.model_validate(await llm.complete_json(system, user, intent_schema(), max_tokens=400))
    except (LLMError, ValidationError, ValueError) as e:
        return fallback, f"interpreter: {e}"
    intent = grounded(view, intent)
    if intent.kind == "action" and intent.action_id not in {a.id for a in actions} and \
            not _a_use(view, intent.action_id):
        if fallback.kind == "action":
            return fallback, None
        return Intent(kind="flavor", summary=intent.summary or raw), None
    if intent.kind == "flavor" and fallback.kind == "action" and fallback.action_id.endswith(":"):
        return fallback, None  # "wield the snitch", with none: you're told you haven't one, not narrated wielding it
    return intent, None


def _a_use(view: RoomView, action_id: str) -> bool:
    """Whether an action id is a whole use of the grid that has a row here (a model's own: "give:pickle@monster:
    lucky_lenny")."""
    use = interactions.parse(action_id)
    return use is not None and interactions.plan(view.state, view.content, use, view) is not None


def grounded(view: RoomView, intent: Intent) -> Intent:
    """A model's intent with the use it says (its verb, subject, target and amount) in the grid's own terms: the verb
    one the grid knows ("feed" is give, "drink" a use on yourself), the subject an item's key, "bomb", "small_key" or
    "gold" for the SCENE id or the name given, the target a SCENE id. A verb it can't make sense of drops the use (its
    words are read instead: interactions.from_intent). An "action" with no listed id but a use is that use; and a
    change of what's held or worn, or a thing put down or sold, is always the move itself (inventory.py), never a
    stunt that rolls and leaves the gear as it was."""
    verb = intent.verb.lower().strip()
    kind = interactions.verb_class(verb) if verb and verb not in VERBS else verb
    verb = AS_VERB.get(kind, kind) if kind in VERBS or kind in AS_VERB else ""
    if not verb:
        return intent.model_copy(update={"verb": "", "subject": "", "target": "", "amount": 0})
    subject = _subject_key(view, intent.subject) or ("bomb" if kind == "bomb" else "")
    target = _target_id(view, intent.target) or ("self" if kind == "eat" else "")
    update = {"verb": verb, "subject": subject, "target": target, "amount": max(0, intent.amount)}
    if intent.action_id or intent.kind not in ("action", "creative") or not subject:
        return intent.model_copy(update=update)
    use = Use(verb, subject, target, update["amount"])
    if verb in interactions.CARRY:
        move = interactions.carry_id(view.state, view.content, use)
        if move:
            update.update(kind="action", action_id=move, difficulty="trivial", success_effects=[], failure_effects=[])
    elif intent.kind == "action":
        row, use = _aimed(view, use)
        update["action_id"] = (row.alias or use_id(use.verb, use.subject, use.target, use.amount)) if row else ""
    return intent.model_copy(update=update)


def _subject_key(view: RoomView, said: str) -> str:
    """What a model's `subject` names, as a use's subject: an item's key, for its SCENE id ("item:holy_water",
    "gear:weapon"), its key or its name; "bomb", "small_key" or "gold". "" for nothing it could be."""
    said = said.strip()
    counters = {"bombs": "bomb", "bomb": "bomb", "keys": "small_key", "small_key": "small_key", "gold": "gold"}
    if not said or said.lower() in counters:
        return counters.get(said.lower(), "")
    ref = view.get(said)
    if ref is not None and ref.kind in ("item", "gear", "floor"):
        return ref.key
    if said in view.content.items:
        return said
    ref = view.match(named_by(said), ("gear", "item", "bombs", "keys", "gold"))
    return ref.key if ref else ""


def _target_id(view: RoomView, said: str) -> str:
    """What a model's `target` names, as a SCENE id: the id itself (one that's gone stays, to be told so), or the ref
    its words name."""
    said = said.strip()
    if not said or view.get(said) or ":" in said:
        return said
    ref = view.match(named_by(said), ("monster", "keeper", "fixture", "feature", "exit", "wall", "gear", "item",
                                      "self", "room"))
    return ref.id if ref else ""


SCENE_SYSTEM = """\
You match a player's typed words to the choices in a scripted scene of a text adventure.
Reply with JSON: {"choice": N, "question": false}
- choice: the number of the choice the player's words mean or amount to. Judge the action, not the exact
  wording: "let my sword arm fall to my side" amounts to lowering a weapon; "smash it" amounts to attacking.
  Use 0 if the words don't fit any choice.
- question: true only if the player is asking about the scene instead of doing something.
"""

SCENE_SCHEMA = {
    "type": "object",
    "properties": {"choice": {"type": "integer"}, "question": {"type": "boolean"}},
    "required": ["choice", "question"],
    "additionalProperties": False,
}


async def scene_choice(llm: LLM, scene_text: str, labels: list[str], raw: str) -> tuple[int | None, bool, str | None]:
    """Which of a scene's choices the player's words amount to: (index or None, is it a question, error)."""
    listed = "\n".join(f"{i}. {label}" for i, label in enumerate(labels, 1))
    user = f"SCENE:\n{scene_text}\n\nCHOICES:\n{listed}\n\nPLAYER TYPED:\n{raw}"
    try:
        reply = await llm.complete_json(SCENE_SYSTEM, user, SCENE_SCHEMA, max_tokens=60)
        choice, question = int(reply.get("choice", 0)), bool(reply.get("question", False))
    except (LLMError, ValueError, TypeError) as e:
        return None, False, f"scene: {e}"
    return (choice - 1 if 1 <= choice <= len(labels) else None), question, None
