"""The dungeon's characters who aren't just monsters, mostly made by the kids in the maker: where they turn up (ODDS,
high while they're being tried out: turn them down here), what you can do with them, and what the narrator is told.

    Lucky Lenny   in some runs, calm on floor 1 or 2. A goblin knocked his bad tooth out with a pan, and it's hidden
                  somewhere on his floor (now and then the floor before). Ask him and he points you to it. Give it back
                  and he yanks out his good one for you (+1 to every roll).
    Swoogy        in some floors' secret room. Guess the number on his die and his diaper is yours. Guess wrong and he
                  charges up his flaps: calm him down with something (gold, a potion, anything you carry), or fight him
                  (stronger than the floor's boss, nowhere near the 100 HP his maker gave him), or get away and come
                  back. Beat him and the diaper's yours anyway.
    King Mouse    now and then he guards the stairs on floor 2 instead of the warden, cut down to size there (his full
                  size waits for deeper floors), and he leaves his vest. Not on floor 1: there, he ended one run in
                  fourteen of the test bot's.
    anyone else   tagged npc in the maker and placed by nothing else: turns up calm on some floors, to talk to and ask.

Each draws on dice of its own (dice.stream), so where they go changes nothing else about a floor.
"""

from __future__ import annotations

import random

from . import dice
from .combat import telegraph
from .content import Content
from .events import Action, Event
from .models import Feature, GameState, MonsterState, Room
from .text import cap, the

LENNY, BAD_TOOTH, GOOD_TOOTH = "lucky_lenny", "lenny_s_bad_tooth", "lenny_s_good_tooth"
SWOOGY, DIAPER = "swoogy_the_gooey", "swoogy_s_diaper"
KING_MOUSE = "king_mouse"
ODDS = {LENNY: 0.5, SWOOGY: 0.5, KING_MOUSE: 0.15, "npc": 0.3}  # a run, a secret room, a staircase, a floor
PLACED = {LENNY, SWOOGY}  # (and the shopkeepers have their shops)
# Cut down to size for the floor they're on: (HP, attack, defense, damage taken off their dice).
SWOOGY_SIZE = {1: (40, 5, 13, -4), 2: (55, 6, 14, -3), 3: (70, 7, 15, -2)}  # more than the boss, far less than 100
KING_MOUSE_SIZE = {2: (30, 4, 12, -5)}  # about the usual floor-2 guard: bigger, and the bot won 3 points fewer runs
SWOOGY_PRICE = 10  # gold a floor, to calm him down
TOOTH_SPOTS = ["a crack between the flagstones", "a heap of old rubbish", "a dark corner"]


def lenny_plan(seed: int) -> tuple[int, int] | None:
    """Whether Lucky Lenny is in this run, and where: his floor and his tooth's floor (his, or now and then the one
    before), or None."""
    rng = dice.stream(seed, LENNY)
    if rng.random() >= ODDS[LENNY]:
        return None
    floor = rng.choice((1, 2))
    return floor, floor if floor == 1 or rng.random() < 0.7 else 1


def place(state: GameState, content: Content, rooms: list[Room], end_id: int) -> None:
    """This floor's characters (see the module's docstring)."""
    floor, seed = state.floor, state.seed
    open_rooms = [r for r in rooms if r.id not in (0, end_id) and not (r.secret or r.shop)
                  and not (r.monster and r.monster.ghost_of)]
    plan = lenny_plan(seed)
    if plan and plan[1] == floor and open_rooms:
        rng = dice.stream(seed, BAD_TOOTH, floor)
        rng.choice(open_rooms).features.append(Feature(name=rng.choice(TOOTH_SPOTS), hidden=True, loot=[BAD_TOOTH]))
    if plan and plan[0] == floor and open_rooms:
        _calm(content, _quiet_room(dice.stream(seed, LENNY, floor), open_rooms), LENNY, "tooth")
    secret = next((r for r in rooms if r.secret), None)
    if secret and floor in SWOOGY_SIZE and dice.stream(seed, SWOOGY, floor).random() < ODDS[SWOOGY]:
        secret.monster = sized(content, SWOOGY, SWOOGY_SIZE[floor], hostile=False, mood="challenge")
    if rooms[end_id].fixture == "stairs" and floor in KING_MOUSE_SIZE \
            and dice.stream(seed, KING_MOUSE, floor).random() < ODDS[KING_MOUSE]:
        rooms[end_id].monster = sized(content, KING_MOUSE, KING_MOUSE_SIZE[floor])
    others = sorted(m.key for m in content.monsters.values()
                    if m.npc and m.key not in PLACED and "shopkeeper" not in m.tags)
    rng = dice.stream(seed, "npc", floor)
    if others and open_rooms and rng.random() < ODDS["npc"]:
        _calm(content, _quiet_room(rng, open_rooms), rng.choice(others))


def sized(content: Content, key: str, size: tuple[int, int, int, int], hostile: bool = True,
          mood: str = "") -> MonsterState:
    """A monster at the strength given, whatever its maker wrote, and worth three times the souls."""
    base = content.monster(key)
    hp, attack, defense, damage = size
    return MonsterState(key=key, name=base.name, hp=hp, max_hp=hp, hostile=hostile, mood=mood, reward_mult=3.0,
                        attack_mod=attack - base.attack, defense_mod=defense - base.defense, damage_mod=damage)


def _quiet_room(rng: random.Random, rooms: list[Room]) -> Room:
    return rng.choice([r for r in rooms if not r.monster] or rooms)


def _calm(content: Content, room: Room, key: str, mood: str = "") -> None:
    base = content.monster(key)
    room.monster = MonsterState(key=key, name=base.name, hp=base.hp, max_hp=base.hp, hostile=False, mood=mood)


# --- what you can do with them ------------------------------------------------

def actions(state: GameState, content: Content) -> list[Action]:
    """The numbered choices a character here gives you, beyond asking it things and attacking it."""
    monster, player = state.room.monster, state.player
    if monster is None:
        return []
    if monster.key == LENNY and monster.mood == "tooth" and not monster.hostile and BAD_TOOTH in player.inventory:
        return [Action("lenny", f"Give {the(monster.name)} his bad tooth", "he wants it back")]
    if monster.key != SWOOGY:
        return []
    if monster.hostile:
        return offers(state, content) if monster.mood == "angry" else []
    if monster.mood == "challenge":
        return [Action("swoogy", "Take Swoogy's challenge: guess the number on his die", "a d6")]
    if monster.mood == "guessing":
        return [Action(f"guess:{n}", f"Guess {n}") for n in range(1, 7)]
    return []


def offers(state: GameState, content: Content, everything: bool = False) -> list[Action]:
    """What you could give an angry Swoogy to calm him down: gold, or something from your pack (potions and food as
    choices; anything else, `everything`, if you say so)."""
    player, price = state.player, SWOOGY_PRICE * state.floor
    choices = [Action("appease:gold", f"Calm Swoogy down with {price} gold", "no diaper")] if player.gold >= price else []
    for key in dict.fromkeys(player.inventory):
        if everything or content.item(key).kind == "consumable":
            choices.append(Action(f"appease:{key}", f"Calm Swoogy down with {the(content.item(key).name)}",
                                  "no diaper"))
    return choices


def unlisted(state: GameState, content: Content) -> list[Action]:
    """Things to give Swoogy that aren't numbered choices, for the interpreter to match ("give him my rubber duck")."""
    monster = state.room.monster
    if not (monster and monster.key == SWOOGY and monster.hostile and monster.mood == "angry"):
        return []
    listed = {a.id for a in offers(state, content)}
    return [a for a in offers(state, content, everything=True) if a.id not in listed]


def perform(state: GameState, content: Content, rng: random.Random, verb: str, arg: str) -> list[Event]:
    from .rules import gain_item

    monster, player = state.room.monster, state.player
    if verb == "lenny":
        player.inventory.remove(BAD_TOOTH)
        monster.mood = "happy"
        state.room.remember(f"you gave {the(monster.name)} his bad tooth back")
        return [Event("lenny", f"{cap(the(monster.name))} snatches his bad tooth and jams it back in with a squelch. "
                               "Then he yanks out his good one with a *POP* and presses it into your hand: \"Don't "
                               "need this anymore!\"")] + gain_item(state, content, GOOD_TOOTH)
    if verb == "swoogy":
        monster.mood, monster.secret = "guessing", rng.randint(1, 6)
        return [Event("swoogy", "Swoogy rolls a six-sided die behind his back, peeks at it, and wobbles with glee. "
                                "\"Guess!\"")]
    if verb == "guess":
        guess, number = int(arg), monster.secret
        if guess == number:
            monster.mood = "won"
            state.rares.append(DIAPER)  # his only one: it won't turn up again, beaten out of him or not
            state.room.remember("you guessed Swoogy's number and won his diaper")
            return [Event("guess", f"You guess {guess}. Swoogy uncovers his die: {number}! He wails, peels off his "
                                   "diaper and hands it over. Fully loaded.", data={"won": True})] + \
                gain_item(state, content, DIAPER)
        monster.mood, monster.hostile, monster.intent = "angry", True, "heavy"
        return [Event("guess", f"You guess {guess}. Swoogy uncovers his die: {number}. Wrong! He's not happy. Calm "
                               "him down with something, quick, or he'll make you pay.", data={"won": False})] + \
            telegraph(state, content)
    if verb == "appease":
        if arg == "gold":
            paid = SWOOGY_PRICE * state.floor
            player.gold -= paid
            what = f"{paid} gold"
        else:
            player.inventory.remove(arg)
            what = the(content.item(arg).name)
        monster.hostile, monster.mood, monster.intent = False, "paid", "strike"
        state.room.remember(f"you calmed Swoogy down with {what}")
        return [Event("appease", f"You hand Swoogy {what}. He snatches it, gives it a long sniff and settles down, "
                                 "grumbling. The diaper stays where it is.")]
    return [Event("info", "You can't do that right now.")]


# --- what the narrator is told --------------------------------------------------

def facts(state: GameState, content: Content) -> str:
    """How a character here is getting on, for the narrator (and the interpreter): "" for anyone else."""
    monster = state.room.monster
    if monster is None:
        return ""
    if monster.key == LENNY:
        if monster.mood == "tooth":
            told = (" You're carrying his bad tooth right now." if BAD_TOOTH in state.player.inventory else
                    " It's hidden somewhere on this floor, or the one before.")
            return (f"{cap(the(monster.name))} is a friendly, down-on-his-luck fellow, not a monster to fight. A "
                    f"goblin knocked his bad tooth out with a pan, and he'd give anything to have it back.{told}")
        if monster.mood == "happy":
            return f"{cap(the(monster.name))} has his bad tooth back and grins a gap-toothed grin."
    if monster.key == SWOOGY:
        return {"challenge": "Swoogy the Gooey, a huge man-baby in a diaper, wants to play a game: guess the number "
                             "on his six-sided die. Guess right and his prized diaper is yours; guess wrong and he "
                             "gets very cranky.",
                "guessing": "Swoogy has rolled his die behind his back and is waiting for your guess.",
                "angry": "Swoogy is furious about your wrong guess and about to attack, unless you calm him down "
                         "with something: gold, a potion, anything you carry.",
                "paid": "Swoogy sits sulking, sniffing whatever you gave him. He's done with you.",
                "won": "Swoogy sits bare-bottomed, wailing for his diaper."}.get(monster.mood, "")
    if content.monster(monster.key).npc and not monster.hostile:
        return f"{cap(the(monster.name))} isn't looking for a fight, and might talk."
    return ""


def tooth_spot(state: GameState) -> tuple[Room, Feature] | None:
    """Where Lenny's bad tooth is hidden on this floor, if it's still there and nobody's said."""
    return next(((room, feature) for room in state.rooms for feature in room.features
                 if BAD_TOOTH in feature.loot and feature.hidden and not feature.told), None)
