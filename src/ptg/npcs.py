"""The dungeon's characters who aren't just monsters, mostly made by the kids in the maker: where they turn up (ODDS,
high while they're being tried out: turn them down here), what you can do with them, what they say, and what the
narrator is told.

    Lucky Lenny   in some runs, calm on floor 1 or 2. A goblin knocked his bad tooth out with a pan, and it's hidden
                  somewhere on his floor (always his: there's no going back up for it). Talk to him (or ask him) and
                  he points you to it, for nothing, as often as you like. Give it back and he yanks out his good one
                  for you (+1 to every roll). Hit him and he fights back, but his tooth still calms him down.
    Swoogy        in some floors' secret room. Guess the number on his die and his diaper is yours. Guess wrong (or
                  hit him) and he charges up his flaps: calm him down with something (gold, a potion, anything you
                  carry), or fight him (stronger than the floor's boss, nowhere near the 100 HP his maker gave him),
                  or get away and come back. Beat him and the diaper's yours anyway; calm him down (or talk him down)
                  and it stays his.
    King Mouse    now and then he guards the stairs on floor 2 instead of the warden, cut down to size there (his full
                  size waits for deeper floors), and he leaves his vest. Not on floor 1: there, he ended one run in
                  fourteen of the test bot's.
    anyone else   tagged npc in the maker and placed by nothing else: turns up calm on some floors, to talk to and ask.

Each draws on dice of its own (dice.stream), so where they go changes nothing else about a floor.

What they say is data, in their own words (data/dialogue.toml, by moment: meeting them, talking to them, being hit,
Lenny's tooth back, Swoogy's game, a shopkeeper's thanks...), and shown just as written: a story card with their
picture (say), which the narrator never rewords. react hears what each turn did and has whoever it was about say
their piece, right after it: walking in on them, hitting them, beating or calming them, a hand-over, a sale. Talking
to them (talk) is free: no roll, no turn. Baby Joey, Swamp Bottoms and King Mouse have their say too; anyone tagged
npc with no lines of their own gets the [npc] ones.

Where each one's story has got to this run is GameState.quests (stage, STAGES): Lenny's tooth found, Lenny met, his
tooth back; Swoogy's game; King Mouse beaten... Story files read and set it ("if: npc lucky_lenny met", "[npc
lucky_lenny done]": set_stage), the map marks whoever's waiting on you (waiting), and quest_log says how each stands.

Characters own what comes of dealing with them: what each takes when you hand it something (wants: anything else
is handed back, at no cost), and how one takes being talked down (calm: it stops fighting, no reward, nothing lost).
The interaction grid (interactions.py) asks them; nothing else hands them things or pays out for calming them.
"""

from __future__ import annotations

import random
import re

from . import dice, inventory
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
# Where a character's story can get to this run (GameState.quests: "unknown" until then), and the mood each stage
# puts it in when a story moves it there (None: as it is). Anyone else: GENERIC.
STAGES: dict[str, dict[str, str | None]] = {
    LENNY: {"found_item": None, "met": "tooth", "angry": None, "done": "happy", "beaten": None},
    SWOOGY: {"challenge": "challenge", "guessing": "guessing", "won": "won", "angry": "angry", "paid": "paid",
             "calmed": "calmed", "beaten": None},
}
GENERIC = {"met": None, "angry": None, "calmed": None, "beaten": None}
CALM = {"calmed", "paid", "done", "challenge", "guessing", "won"}  # stages that have a character stop fighting
BLANK = re.compile(r"\{([a-z_]+)\}")


def lenny_floor(seed: int) -> int | None:
    """Whether Lucky Lenny is in this run, and on which floor (1 or 2): his tooth is hidden on that floor too, since
    you can't go back up for it."""
    rng = dice.stream(seed, LENNY)
    if rng.random() >= ODDS[LENNY]:
        return None
    return rng.choice((1, 2))


def place(state: GameState, content: Content, rooms: list[Room], end_id: int) -> None:
    """This floor's characters (see the module's docstring)."""
    floor, seed = state.floor, state.seed
    open_rooms = [r for r in rooms if r.id not in (0, end_id) and not (r.secret or r.shop)
                  and not (r.monster and r.monster.ghost_of)]
    if lenny_floor(seed) == floor and open_rooms:
        hide_tooth(state, open_rooms)
        _calm(content, _quiet_room(dice.stream(seed, LENNY, floor), open_rooms), LENNY, "tooth")
    secret = next((r for r in rooms if r.secret), None)
    if secret and floor in SWOOGY_SIZE and dice.stream(seed, SWOOGY, floor).random() < ODDS[SWOOGY] \
            and DIAPER not in state.rares:  # (once his diaper's gone, won or beaten out of him, so is he)
        secret.monster = sized(content, SWOOGY, floor, SWOOGY_SIZE, hostile=False, mood="challenge")
    if rooms[end_id].fixture == "stairs" and floor in KING_MOUSE_SIZE \
            and dice.stream(seed, KING_MOUSE, floor).random() < ODDS[KING_MOUSE]:
        rooms[end_id].monster = sized(content, KING_MOUSE, floor, KING_MOUSE_SIZE, warden=True)
    others = sorted(m.key for m in content.monsters.values()
                    if m.npc and m.key not in PLACED and "shopkeeper" not in m.tags)
    rng = dice.stream(seed, "npc", floor)
    if others and open_rooms and rng.random() < ODDS["npc"]:
        _calm(content, _quiet_room(rng, open_rooms), rng.choice(others))


def hide_tooth(state: GameState, rooms: list[Room]) -> tuple[Room, Feature]:
    """Lenny's bad tooth, hidden in one of `rooms` (where a goblin's pan sent it flying): the room, and where in it."""
    rng = dice.stream(state.seed, BAD_TOOTH, state.floor)
    room = rng.choice(rooms)
    feature = Feature(name=rng.choice(TOOTH_SPOTS), hidden=True, loot=[BAD_TOOTH])
    room.features.append(feature)
    return room, feature


def sized(content: Content, key: str, floor: int, sizes: dict[int, tuple[int, int, int, int]], hostile: bool = True,
          mood: str = "", warden: bool = False) -> MonsterState:
    """A monster at the strength its sizes give for the floor, whatever its maker wrote: at least as tough as the
    floor's warden to dodge and to run from (tougher, if its maker made it so: Swoogy), and worth three times the
    souls."""
    from .world import warden_tier

    base = content.monster(key)
    hp, attack, defense, damage = sizes[floor]
    return MonsterState(key=key, name=base.name, hp=hp, max_hp=hp, hostile=hostile, mood=mood, reward_mult=3.0,
                        attack_mod=attack - base.attack, defense_mod=defense - base.defense, damage_mod=damage,
                        tier=max(warden_tier(floor), base.tier), warden=warden)


def _quiet_room(rng: random.Random, rooms: list[Room]) -> Room:
    return rng.choice([r for r in rooms if not r.monster] or rooms)


def _calm(content: Content, room: Room, key: str, mood: str = "") -> None:
    base = content.monster(key)
    room.monster = MonsterState(key=key, name=base.name, hp=base.hp, max_hp=base.hp, hostile=False, mood=mood)


# --- where their stories have got to ----------------------------------------------

def stage(state: GameState, key: str) -> str:
    """Where a character's story has got to this run: "unknown" until you've met it (or found its thing)."""
    return state.quests.get(key, "unknown")


def stages(key: str) -> list[str]:
    """Every stage a character's story can be at (STAGES), for story files to name."""
    return ["unknown", *STAGES.get(key, GENERIC)]


def set_stage(state: GameState, key: str, to: str) -> None:
    """Move a character's story on (a story file's [npc lucky_lenny done]): its stage this run, and the character
    itself, wherever it is on this floor: the mood the stage puts it in (STAGES), fighting you if it's angry, not if
    it's calmed down (or done, paid, playing its game). It isn't moved, hurt or handed anything."""
    state.quests[key] = to
    mood = STAGES.get(key, GENERIC).get(to)
    for room in state.rooms:
        monster = room.monster
        if not (monster and monster.key == key and monster.hp > 0):
            continue
        monster.met = monster.met or to != "unknown"
        monster.mood = mood or monster.mood
        if to == "guessing" and not monster.secret:
            monster.secret = dice.stream(state.seed, SWOOGY, "story", state.turn).randint(1, 6)
        if to == "angry":
            monster.hostile, monster.intent = True, "heavy" if key == SWOOGY else monster.intent
        elif to in CALM:
            monster.hostile, monster.intent = False, "strike"


def _advance(state: GameState, key: str, to: str) -> None:
    state.quests[key] = to


# --- what they say -------------------------------------------------------------------

def speaks(content: Content, key: str) -> bool:
    """Whether a creature is a character with something to say: lines of its own (dialogue.toml), or tagged npc (the
    [npc] lines, until it has some)."""
    return key in content.dialogue or (key in content.monsters and content.monster(key).npc)


def lines(content: Content, key: str, moment: str) -> list[str]:
    """A character's lines for a moment (content.MOMENTS): its own, or, tagged npc, the [npc] ones."""
    own = content.dialogue.get(key, {}).get(moment)
    if own:
        return own
    if key in content.monsters and content.monster(key).npc:
        return content.dialogue.get("npc", {}).get(moment, [])
    return []


def line(state: GameState, content: Content, key: str, moment: str, advance: bool = False, **blanks: str) -> str:
    """The line a character would say next at a moment, its blanks (content.BLANKS) filled in ({name} is its own),
    or "" if it has none: for a panel to show (a shopkeeper's greeting on her counter). `advance`: it's said, and
    next time it's the next one (its lines take turns)."""
    said = lines(content, key, moment)
    if not said:
        return ""
    tally = f"{key}:{moment}"
    count = state.said.get(tally, 0)
    if advance:
        state.said[tally] = count + 1
    blanks = {"name": content.monster(key).name, **blanks}
    return BLANK.sub(lambda m: blanks.get(m.group(1), m.group(0)), said[count % len(said)])


def say(state: GameState, content: Content, key: str, moment: str, **blanks: str) -> list[Event]:
    """What a character says at a moment, in its own words (line), as a story card with its picture: Game logs it as
    a card and the story shows it so, never narrated. Nothing, if it has no line for it.

        Event("story", "WOAH WOAH WOAH WOAH! ...", data={"voice": "exact", "title": "Lucky Lenny",
              "sprite": "lucky_lenny", "speaker": "lucky_lenny", "moment": "meet"})"""
    text = line(state, content, key, moment, advance=True, **blanks)
    if not text:
        return []
    return [Event("story", text, data={"voice": "exact", "title": content.monster(key).name, "sprite": key,
                                       "speaker": key, "moment": moment})]


def _place(state: GameState, room: Room) -> str:
    """Where a room is, for a character to say: "right here", "in the Feast Hall", "in a room you haven't been to"."""
    if room.id == state.room_id:
        return "right here"
    return f"in {the(room.name)}" if room.visited else "in a room you haven't been to yet"


# --- what you can do with them ------------------------------------------------

def actions(state: GameState, content: Content) -> list[Action]:
    """The numbered choices a character here gives you, beyond talking to it, asking it things and attacking it:
    Lenny's tooth whenever you carry it (hit, it calms him down), Swoogy's game and his guesses, or, angry, one for his
    price in gold and one to give him something of yours, which picks what (a picker: see interactions.choices), not
    one for every potion and loaf you carry."""
    monster, player = state.room.monster, state.player
    if monster is None or monster.hp <= 0:
        return []
    if monster.key == LENNY and monster.mood == "tooth" and BAD_TOOTH in player.inventory:
        return [Action("lenny", f"Give {the(monster.name)} his bad tooth",
                       "he'd stop fighting" if monster.hostile else "he wants it back")]
    if monster.key != SWOOGY:
        return []
    if monster.hostile:
        if monster.mood != "angry":
            return []
        given = [a for a in offers(state, content, everything=True) if a.id != "appease:gold"]
        pick = [Action(f"give:@monster:{SWOOGY}", "Give Swoogy something to calm him down…", "pick it · no diaper")]
        return [a for a in offers(state, content) if a.id == "appease:gold"] + (pick if given else [])
    if DIAPER in state.rares:  # nothing left to play for: talked down, he handed it over already
        return []
    if monster.mood == "challenge":
        return [Action("swoogy", "Take Swoogy's challenge: guess the number on his die", "a d6")]
    if monster.mood == "guessing":
        return [Action(f"guess:{n}", f"Guess {n}") for n in range(1, 7)]
    return []


def talk_action(state: GameState, content: Content) -> Action | None:
    """Talking to whoever's here, if they'll talk: a character who isn't fighting you, or a shop's keeper. Free: no
    roll, no turn."""
    room = state.room
    if state.in_combat:
        return None
    if room.shop:
        return Action(f"talk:{room.shop.keeper}", f"Talk to {content.monster(room.shop.keeper).name}", "no turn")
    monster = room.monster
    if monster is None or monster.hp <= 0 or monster.hostile or not speaks(content, monster.key):
        return None
    return Action(f"talk:{monster.key}", f"Talk to {the(monster.name)}",
                  "where's his tooth?" if tells_of_tooth(state) else "no turn")


def primary_actions(state: GameState, content: Content) -> list[Action]:
    """What to do with whoever's here, the most useful first (what a click on them offers, Enter the first): what
    they're after or their game (actions), a keeper's wares, talking to them, asking them what they know, and only
    then attacking them. In a fight, what would end it peacefully (Lenny's tooth, Swoogy's price) comes first too."""
    from .rules import available_actions

    own = {a.id for a in actions(state, content)}

    def rank(action: Action) -> int | None:
        if action.id in own or action.id == "shop":
            return 0
        return {"talk": 1, "ask": 2, "attack": 3}.get(action.id.partition(":")[0])

    return sorted((a for a in available_actions(state, content) if rank(a) is not None), key=rank)


def offers(state: GameState, content: Content, everything: bool = False) -> list[Action]:
    """What you could give an angry Swoogy to calm him down: gold, or something from your pack (potions and food;
    anything else too, `everything`), but never what you'll be needing (see needed)."""
    player, price = state.player, SWOOGY_PRICE * state.floor
    choices = [Action("appease:gold", f"Calm Swoogy down with {price} gold", "no diaper")] if player.gold >= price else []
    for key in dict.fromkeys(player.inventory):
        if inventory.keeps(state, content, key):  # (what you'll be needing, or a curse that won't let go)
            continue
        if everything or content.item(key).kind == "consumable":
            choices.append(Action(f"appease:{key}", f"Calm Swoogy down with {the(content.item(key).name)}",
                                  "no diaper"))
    return choices


def needed(state: GameState, content: Content, key: str) -> bool:
    """Whether something you carry is never to be handed over or used up: a key (a run could hang on it: no bomb opens
    the boss's door), or what a character is still waiting for (Lenny's bad tooth, until he has it back)."""
    if content.item(key).kind == "key":
        return True
    if key != BAD_TOOTH:
        return False
    floor = lenny_floor(state.seed)
    waiting = any(r.monster and r.monster.key == LENNY and r.monster.mood == "tooth" for r in state.rooms)
    return waiting or bool(floor and state.floor < floor)  # (he's here, or on a floor still to come)


def unlisted(state: GameState, content: Content) -> list[Action]:
    """Things to give Swoogy that aren't numbered choices, for the interpreter to match ("give him my rubber duck")."""
    monster = state.room.monster
    if not (monster and monster.key == SWOOGY and monster.hostile and monster.mood == "angry"):
        return []
    listed = {a.id for a in offers(state, content)}
    return [a for a in offers(state, content, everything=True) if a.id not in listed]


def perform(state: GameState, content: Content, rng: random.Random, verb: str, arg: str) -> list[Event]:
    """Lenny's tooth back, Swoogy's game and his guesses, calming him down: what's done (react has them say their
    piece about it)."""
    monster = state.room.monster
    if verb == "lenny":
        return give_tooth(state, content)
    if verb == "swoogy":
        monster.mood, monster.secret = "guessing", rng.randint(1, 6)
        return [Event("swoogy", "Swoogy rolls a six-sided die behind his back, peeks at it, and wobbles with glee.")]
    if verb == "guess":
        guess, number = int(arg), monster.secret
        if guess == number:  # his diaper's yours, at your feet: to take, if you dare (it's cursed), or leave
            monster.mood = "won"
            state.rares.append(DIAPER)  # his only one: it won't turn up again, beaten out of him or not
            state.room.remember("you guessed Swoogy's number and won his diaper")
            return [Event("guess", f"You guess {guess}. Swoogy uncovers his die: {number}! He peels off his diaper "
                                   "and drops it at your feet. Fully loaded.",
                          data={"won": True, **inventory.lay(state, DIAPER, "win", SWOOGY)})]
        monster.mood, monster.hostile, monster.intent = "angry", True, "heavy"
        return [Event("guess", f"You guess {guess}. Swoogy uncovers his die: {number}. Wrong! Calm him down with "
                               "something, quick, or he'll make you pay.", data={"won": False})] + \
            telegraph(state, content)
    if verb == "appease":
        return appease(state, content, arg)
    return [Event("info", "You can't do that right now.")]


def give_tooth(state: GameState, content: Content) -> list[Event]:
    """Lenny's bad tooth back where it belongs (calming him down first, if you'd hit him), and his good one in your
    hand for it."""
    monster = state.room.monster
    name = cap(the(monster.name))
    events = []
    if monster.hostile:
        monster.hostile, monster.intent = False, "strike"
        events.append(Event("calm", f"{name} sees his tooth in your hand and stops dead."))
    given = inventory.give(state, BAD_TOOTH, LENNY)
    monster.mood = "happy"
    state.room.remember(f"you gave {the(monster.name)} his bad tooth back")
    events.append(Event("lenny", f"{name} snatches his bad tooth and jams it back in with a squelch. Then he yanks out "
                                 "his good one with a *POP* and presses it into your hand.", data=given))
    return events + inventory.gain(state, content, GOOD_TOOTH, "give", LENNY)


def appease(state: GameState, content: Content, what: str, amount: int = 0) -> list[Event]:
    """Calm an angry Swoogy down with something you carry, or gold: his price, or more if you say so (`amount`). He
    keeps it, and the diaper stays his. The event says what changed hands, an item's move (inventory.moved) or the
    gold's: {"gold": 30, "how": "give", "from": "purse", "to": "swoogy_the_gooey"}."""
    monster, player = state.room.monster, state.player
    if what == "gold":
        paid = min(player.gold, max(amount, SWOOGY_PRICE * state.floor))
        player.gold -= paid
        given, said = {"gold": paid, "how": "give", "from": "purse", "to": SWOOGY}, f"{paid} gold"
    else:
        given, said = inventory.give(state, what, SWOOGY), the(content.item(what).name)
    monster.hostile, monster.mood, monster.intent = False, "paid", "strike"
    state.room.remember(f"you calmed Swoogy down with {said}")
    diaper = " The diaper stays where it is." if DIAPER not in state.rares else ""
    return [Event("appease", f"You hand Swoogy {said}. He snatches it, gives it a long sniff and settles down, "
                             f"grumbling.{diaper}", data=given)]


def wants(state: GameState, content: Content, monster: MonsterState, what: str,
          amount: int = 0) -> tuple[str, str, str]:
    """What a character makes of being handed something (`what`: an item's key, or "gold", and how much): how it
    takes it ("lenny": Lenny his bad tooth, his good one in return; "appease": an angry Swoogy, anything that isn't
    too little gold), or "" and what it does with it (hands it back, at no cost, no turn), and the moment of what it
    says to that (its line: see say), if anything."""
    name, player = cap(the(monster.name)), state.player
    given = (f"{amount} gold" if amount else "your gold") if what == "gold" else the(content.item(what).name)
    if monster.key == LENNY:
        if monster.mood == "tooth" and what == BAD_TOOTH:
            return "lenny", "", ""
        if monster.mood == "tooth":
            return "", f"{name} sniffs {given} and hands it back.", "refuse_gift"
        return "", f"{name} grins his gap-toothed grin and waves {given} away.", "keep_it"
    if monster.key == SWOOGY:
        if monster.mood == "angry" and monster.hostile:
            price = SWOOGY_PRICE * state.floor
            if what == "gold" and (amount or price) < price:
                return "", f"Swoogy sniffs at {amount} gold and flaps harder: it'd take {price}.", ""
            if what == "gold" and player.gold < (amount or price):
                return "", f"Swoogy wants {price} gold, and you have {player.gold}.", ""
            return "appease", "", ""
        if monster.mood in ("challenge", "guessing"):
            return "", f"Swoogy pushes {given} away and wobbles his die at you.", "refuse_gift"
        if monster.mood == "won":
            return "", f"Swoogy won't even look at {given}.", "bare"
        return "", f"Swoogy turns his back on {given}, sulking.", "keep_it"
    return "", f"{name} turns {given} over and hands it back.", "refuse_gift"


def take(state: GameState, content: Content, rng: random.Random, what: str, amount: int = 0) -> list[Event]:
    """A character takes what it wants (see wants): Lenny his tooth (calming down first, if you'd hit him), an angry
    Swoogy whatever calms him."""
    if state.room.monster.key == LENNY:
        return give_tooth(state, content)
    return appease(state, content, what, amount)


def calm(state: GameState, content: Content, monster: MonsterState) -> list[Event]:
    """A character talked down (a stunt, a story's [calm]): it stops fighting, and that's all. It isn't beaten, so
    there's no reward and it keeps what it has (Swoogy his diaper); an angry Swoogy sulks instead (his mood says so,
    for the narrator)."""
    name = cap(the(monster.name))
    monster.hostile, monster.intent = False, "strike"
    state.player.bump("pacify")
    data = {"monster": monster.key, "how": "calmed"}
    if monster.key == SWOOGY and monster.mood == "angry":
        monster.mood = "calmed"
        state.room.remember("you talked Swoogy down")
        diaper = " The diaper stays where it is." if DIAPER not in state.rares else ""
        return [Event("pacify", f"Swoogy stops flapping and settles down, grumbling.{diaper}", data=data)]
    state.room.remember(f"you talked {the(monster.name)} down")
    return [Event("pacify", f"{name} calms down, though {'he' if monster.key == LENNY else 'it'} keeps an eye on "
                            "you.", data=data)]


def shown(state: GameState, content: Content, monster: MonsterState, what: str) -> list[Event]:
    """What a creature that isn't fighting you makes of being shown something (free)."""
    name = cap(the(monster.name))
    showing = "your gold" if what == "gold" else the(content.item(what).name)
    if monster.key == LENNY and monster.mood == "tooth" and what == BAD_TOOTH:
        return [Event("info", f"{name} gasps.")] + say(state, content, LENNY, "has_item")
    if monster.key == SWOOGY and what == "gold":
        return [Event("info", "Swoogy's eyes go wide at the gold, then narrow. He'd rather play.")]
    if not content.monster(monster.key).intelligent:
        return [Event("info", f"{name} sniffs at {showing} and loses interest.")]
    return [Event("info", f"{name} peers at {showing} and shrugs.")]


# --- talking to them ---------------------------------------------------------------

def talk(state: GameState, content: Content, key: str) -> list[Event]:
    """Talking to whoever's here (a character, or a shop's keeper): what they've got to say right now, in their own
    words. No roll, no turn. Lucky Lenny tells you where his tooth went, as often as you like."""
    room = state.room
    if room.shop and room.shop.keeper == key:
        return say(state, content, key, "talk") or _silent(content, key)
    monster = room.monster
    if monster.key == LENNY:
        said = _lenny_talks(state, content, monster)
    elif monster.key == SWOOGY:
        moment = "bare" if monster.mood == "won" or DIAPER in state.rares else \
            {"guessing": "guessing", "paid": "sulk", "calmed": "sulk"}.get(monster.mood, "talk")
        said = say(state, content, SWOOGY, moment)
    else:
        said = say(state, content, key, "talk")
    return said or _silent(content, key)


def _silent(content: Content, key: str) -> list[Event]:
    return [Event("info", f"{cap(the(content.monster(key).name))} has nothing to say.", data={"quiet": True})]


def _lenny_talks(state: GameState, content: Content, monster: MonsterState) -> list[Event]:
    if monster.mood == "happy":
        return say(state, content, LENNY, "after")
    if monster.mood != "tooth":  # (not in his story: anyone's [npc] small talk)
        return say(state, content, LENNY, "talk")
    if BAD_TOOTH in state.player.inventory:
        return say(state, content, LENNY, "has_item")
    where = tooth_where(state)
    if where is None:
        return say(state, content, LENNY, "missing")
    room, feature = where
    if feature is None:
        return say(state, content, LENNY, "lying", place=_place(state, room))
    return point(state, content, room, feature)


def point(state: GameState, content: Content, room: Room, feature: Feature) -> list[Event]:
    """Lenny saying where his tooth went (for nothing, as often as you ask): you can see the spot from then on, and
    it's on your map."""
    monster = state.room.monster
    first = not feature.told
    feature.told, feature.hidden = monster.name, False
    tip = []
    if first:
        here = room.id == state.room_id
        tip = [Event("tip", f"{cap(the(monster.name))} points a shaky finger"
                            + (" across the room." if here else ". It's on your map now."), data={"room": room.id})]
    return tip + say(state, content, LENNY, "point", feature=feature.name, place=_place(state, room))


def tooth_where(state: GameState) -> tuple[Room, Feature | None] | None:
    """Where Lenny's bad tooth is on this floor, if it isn't yours: the room, and the feature it's hidden in (None
    once it's been found and lies there for the taking)."""
    for room in state.rooms:
        for feature in room.features:
            if BAD_TOOTH in feature.loot:
                return room, feature
    return next(((room, None) for room in state.rooms if BAD_TOOTH in room.items), None)


def tooth_spot(state: GameState) -> tuple[Room, Feature] | None:
    """Where Lenny's bad tooth is hidden on this floor, if it's still there and nobody's said."""
    return next(((room, feature) for room in state.rooms for feature in room.features
                 if BAD_TOOTH in feature.loot and feature.hidden and not feature.told), None)


def tells_of_tooth(state: GameState) -> bool:
    """Whether Lenny, here, has yet to tell you where his tooth went (and would, for nothing: talk, or ask him)."""
    monster = state.room.monster
    where = tooth_where(state)
    return bool(monster and monster.key == LENNY and monster.mood == "tooth" and not monster.hostile and where
                and where[1] and not where[1].told and BAD_TOOTH not in state.player.inventory)


def tooth_first(state: GameState) -> bool:
    """Whether Lenny, here, has nothing on his mind but his tooth: he's yet to tell you where it went, or he can see
    it in your hand. Asked anything then, he talks of that, for nothing (no roll, and the asking keeps for later)."""
    monster = state.room.monster
    return tells_of_tooth(state) or bool(monster and monster.key == LENNY and monster.mood == "tooth"
                                         and not monster.hostile and BAD_TOOTH in state.player.inventory)


TALK_WORDS = {"talk", "chat", "speak", "greet", "hello", "hi", "hey", "hiya", "howdy", "converse", "chatter", "ask",
              "tell", "say", "natter"}


def talked_to(state: GameState, content: Content, words: str) -> str | None:
    """The talk action that some words amount to ("talk to lenny", "ask lenny what his favourite food is", "hello
    granny"), if they're said to someone here who might answer: whoever's here, a character (fighting you or not: then
    it says why not, for nothing) or a shop's keeper. None for anything else."""
    said = re.findall(r"[a-z']+", words.lower())
    said = said[1:] if said[:1] == ["i"] else said
    if not said or said[0] not in TALK_WORDS:
        return None
    room = state.room
    if room.shop:
        return f"talk:{room.shop.keeper}"
    monster = room.monster
    return f"talk:{monster.key}" if monster and monster.hp > 0 and speaks(content, monster.key) else None


# --- what they say to what happens --------------------------------------------------

def react(state: GameState, content: Content, events: list[Event]) -> list[Event]:
    """The turn's events, with what the characters say to them, each right after what it's about: walking in on one
    (meeting it: its line's data says "met"), hitting one that wasn't fighting you, beating or calming one, Lenny's
    tooth back, Swoogy's game, a shopkeeper's sale or haggle, Baby Joey's grab. Where their stories have got to
    (GameState.quests) moves on with them."""
    out: list[Event] = []
    for event in events:
        out.append(event)
        out += _reaction(state, content, event)
    return out


def _reaction(state: GameState, content: Content, event: Event) -> list[Event]:
    kind, data, room = event.kind, event.data, state.room
    monster = room.monster if room.monster and room.monster.hp > 0 else None
    if kind == "enter":
        return _walk_in(state, content)
    if kind == "provoke" and monster and speaks(content, monster.key):
        if monster.key == SWOOGY and DIAPER not in state.rares:
            monster.mood = "angry"  # (his game's off: he's cranky, and something you give him could calm him down)
        _advance(state, monster.key, "angry")
        return say(state, content, monster.key, "angry")
    who = data.get("monster", "")
    if kind == "defeat" and who and speaks(content, who):
        _advance(state, who, "beaten")
        return say(state, content, who, "beaten")
    if kind == "pacify" and who and speaks(content, who):  # (Lenny's back to waiting for his tooth, or done)
        mood = monster.mood if monster else ""
        calmed = mood if who == SWOOGY and mood in STAGES[SWOOGY] else "calmed"  # (diaper won, it's still "won")
        _advance(state, who, {"tooth": "met", "happy": "done"}.get(mood, calmed))
        return say(state, content, who, "calmed")
    if kind == "lenny":
        _advance(state, LENNY, "done")
        return say(state, content, LENNY, "done") + [
            Event("story_effect", "Quest complete: Lucky Lenny has his bad tooth back.", data={"quest": LENNY})]
    if kind == "swoogy":
        _advance(state, SWOOGY, "guessing")
        return say(state, content, SWOOGY, "guessing")
    if kind == "guess":
        _advance(state, SWOOGY, "won" if data.get("won") else "angry")
        return say(state, content, SWOOGY, "won" if data.get("won") else "lost")
    if kind == "appease":
        _advance(state, SWOOGY, "paid")
        return say(state, content, SWOOGY, "paid")
    if kind in ("buy", "sell") and room.shop:
        return say(state, content, room.shop.keeper, "thanks" if kind == "buy" else "buys")
    if kind == "barter" and room.shop and event.dice:
        return say(state, content, room.shop.keeper, "haggle_won" if event.dice.success else "haggle_lost")
    if kind == "steal" and monster:
        return say(state, content, monster.key, "steal")
    if kind == "take" and data.get("item") == BAD_TOOTH:
        if monster and monster.key == LENNY and monster.mood == "tooth":
            return say(state, content, LENNY, "has_item")
        if stage(state, LENNY) == "unknown":  # found before you've met him
            _advance(state, LENNY, "found_item")
            return [Event("story_effect", "A bad tooth, with a name scratched on it: LENNY. Someone will be wanting "
                                          "this back.", data={"quest": LENNY})]
    return []


def _walk_in(state: GameState, content: Content) -> list[Event]:
    """Walking in on someone: a shop's keeper greets you every time; a character has its say the first time you see
    it (Lenny's on whether you've his tooth; Swoogy, met on a floor before, wants a rematch). The first meeting this
    run is marked on what's said (data "met": a story's "when: meet")."""
    room = state.room
    if room.shop:
        key = room.shop.keeper
        first = stage(state, key) == "unknown"
        _advance(state, key, "met")
        said = say(state, content, key, "greet" if first else "again")
    else:
        monster = room.monster
        if monster is None or monster.hp <= 0 or monster.met or not speaks(content, monster.key):
            return []
        monster.met = True
        key, known = monster.key, stage(state, monster.key)
        first = known in ("unknown", "found_item")
        if key == LENNY:
            carrying = BAD_TOOTH in state.player.inventory and monster.mood == "tooth"
            moment = "has_item" if carrying else "meet"
        elif key == SWOOGY:
            moment = "meet" if first or monster.mood != "challenge" else "again"
        else:
            moment = "meet"
        if key == SWOOGY:  # (his game on offer again, met on a floor before or not)
            _advance(state, SWOOGY, monster.mood or "challenge")
        elif first:
            _advance(state, key, "met")
        said = say(state, content, key, moment)
    if first:
        said = said or [Event("meet", "", data={"told_by": "silent"})]
        said[0].data["met"] = key
    return said


# --- what the narrator is told --------------------------------------------------

def facts(state: GameState, content: Content) -> str:
    """How a character here is getting on, for the narrator (and the interpreter), in a few in-world words: "" for
    anyone else. Whether it's fighting you comes first: hit, even a friendly soul fights back."""
    monster = state.room.monster
    if monster is None or monster.hp <= 0:
        return ""
    name = cap(the(monster.name))
    if monster.key == LENNY and monster.mood in ("tooth", "happy"):
        return _lenny_facts(state, monster, name)
    if monster.key == SWOOGY and (monster.mood or monster.hostile):
        return _swoogy_facts(state, monster)
    if monster.key == KING_MOUSE:
        return ("King Mouse, a VERY big mouse in a royal vest, guards the stairs down and won't let anyone by."
                if monster.hostile else "King Mouse has stopped fighting, and lets you by to the stairs.")
    if content.monster(monster.key).npc:
        return f"{name} is fighting you." if monster.hostile else f"{name} isn't looking for a fight, and might talk."
    return ""


def _lenny_facts(state: GameState, monster: MonsterState, name: str) -> str:
    carrying = BAD_TOOTH in state.player.inventory
    if monster.hostile:
        if monster.mood == "happy":
            return f"{name} is fighting back: you hit him, after you'd given him his tooth back and all."
        return (f"{name} is fighting back: you hit him, and all he ever wanted was his bad tooth back."
                + (" You're carrying his bad tooth right now." if carrying else ""))
    if monster.mood == "happy":
        return f"{name} has his bad tooth back and grins a gap-toothed grin."
    where = tooth_where(state)
    if carrying:
        told = " You're carrying his bad tooth right now, and he's spotted it."
    elif where is None:
        told = " It's gone for good."
    elif where[1] is None:
        told = f" It's lying {_place(state, where[0])}, found."
    elif where[1].told:
        told = f" It's in {where[1].name} {_place(state, where[0])}: he told you so."
    else:
        told = " It flew off somewhere on this floor, and he saw where."
    return (f"{name} is a down-on-his-luck fellow with a fake gold crown pinching the gap in his teeth. A goblin's "
            f"frying pan knocked his bad tooth out, and he wants it back.{told}")


def _swoogy_facts(state: GameState, monster: MonsterState) -> str:
    if monster.hostile:
        if DIAPER in state.rares:
            return "Swoogy is cranky and fighting you, bare-bottomed: his diaper's gone already."
        return ("Swoogy is furious and about to attack, unless you calm him down with something: gold, a potion, "
                "anything you carry.")
    return {"challenge": "Swoogy the Gooey, a huge man-baby in a diaper, wants to play a game: guess the number on "
                         "his six-sided die. Guess right and his prized diaper is yours; guess wrong and he gets very "
                         "cranky.",
            "guessing": "Swoogy has rolled his die behind his back and is waiting for your guess.",
            "angry": "Swoogy is furious about your wrong guess, but not fighting you.",
            "paid": "Swoogy sits sulking, sniffing whatever you gave him. He's done with you.",
            "calmed": "Swoogy sits sulking, talked down but still in his diaper. He's done with you.",
            "won": "Swoogy sits bare-bottomed, wailing for his diaper."}.get(monster.mood, "")


# --- how their stories stand: for the glossary, the map and the journal ---------------------------------------------

def status(state: GameState, content: Content, key: str) -> str:
    """A character's state in a few words ("wants his bad tooth back"), for its card: the one on this floor, or
    else where its story's got to. "" for anyone who isn't a character."""
    if not speaks(content, key):
        return ""
    if "shopkeeper" in content.monster(key).tags:
        return "keeps a shop"
    here = next((r.monster for r in state.rooms if r.monster and r.monster.key == key and r.monster.hp > 0), None)
    now = stage(state, key)
    if here is not None and here.hostile:
        return "guards the stairs" if key == KING_MOUSE and now != "angry" else "fighting you"
    if key == LENNY:
        return "has his bad tooth back" if (here and here.mood == "happy") or now == "done" else \
            "wants his bad tooth back"
    if key == SWOOGY:
        mood = here.mood if here else now
        return {"challenge": "wants to play a guessing game", "guessing": "waiting for your guess",
                "won": "lost his diaper to you", "paid": "sulking", "calmed": "sulking"}.get(mood, "")
    if key == KING_MOUSE:
        return "lets you pass" if now == "calmed" else "guards the stairs"
    return "isn't looking for a fight" if here is not None else ""


def waiting(state: GameState, monster: MonsterState) -> bool:
    """Whether a character wants something from you: Lenny his tooth, Swoogy his game (the map marks them)."""
    if monster.hostile or monster.hp <= 0:
        return False
    return (monster.key == LENNY and monster.mood == "tooth") or \
        (monster.key == SWOOGY and monster.mood in ("challenge", "guessing") and DIAPER not in state.rares)


def quest_log(state: GameState, content: Content) -> list[tuple[str, str, bool]]:
    """How each character's story stands, for the journal: (whose, in a line, still open), the open ones first.
    "Lucky Lenny wants his bad tooth back: it's in a heap of old rubbish in the Feast Hall."."""
    found: list[tuple[str, str, bool]] = []
    lenny = _lenny_log(state)
    if lenny:
        found.append((LENNY, *lenny))
    swoogy = {"challenge": ("Swoogy wants you to guess the number on his die.", True),
              "guessing": ("Swoogy has rolled his die, and is waiting for your guess.", True),
              "angry": ("Swoogy is cranky: calm him down with gold or something you carry, or beat him.", True),
              "won": ("You won Swoogy's diaper.", False),
              "paid": ("You calmed Swoogy down: he kept his diaper.", False),
              "calmed": ("You talked Swoogy down: he kept his diaper.", False),
              "beaten": ("You beat Swoogy, and his diaper fell to you.", False)}.get(stage(state, SWOOGY))
    if swoogy:
        here = any(r.monster and r.monster.key == SWOOGY for r in state.rooms)
        found.append((SWOOGY, *(swoogy if here or not swoogy[1] else ("Swoogy's game was left unfinished.", False))))
    mouse = {"met": ("King Mouse guards the stairs down.", True), "angry": ("King Mouse guards the stairs down.", True),
             "calmed": ("King Mouse let you pass.", False), "beaten": ("You beat King Mouse.", False)}.get(
        stage(state, KING_MOUSE))
    if mouse:
        found.append((KING_MOUSE, *mouse))
    return sorted(found, key=lambda entry: not entry[2])


def _lenny_log(state: GameState) -> tuple[str, bool] | None:
    now = stage(state, LENNY)
    if now == "unknown":
        return None
    if now == "found_item":
        return "You found a bad tooth with LENNY scratched on it. Someone will be wanting it back.", True
    if now == "done":
        return "Lucky Lenny has his bad tooth back, and you have his good one.", False
    if now == "beaten":
        return "Lucky Lenny is gone, his bad tooth never back.", False
    lenny = next((r for r in state.rooms if r.monster and r.monster.key == LENNY and r.monster.hp > 0), None)
    if lenny is None:
        return (f"You left Lucky Lenny behind on floor {lenny_floor(state.seed) or state.floor - 1}, still missing "
                "his bad tooth."), False
    if BAD_TOOTH in state.player.inventory:
        return f"Take Lucky Lenny his bad tooth: he's {_place(state, lenny)}.", True
    where = tooth_where(state)
    if where is None:
        return "Lucky Lenny's bad tooth is gone for good.", False
    room, feature = where
    if feature is None:
        return f"Lucky Lenny wants his bad tooth back: it's lying {_place(state, room)}.", True
    if feature.told:
        return f"Lucky Lenny wants his bad tooth back: it's in {feature.name} {_place(state, room)}.", True
    return "Lucky Lenny wants his bad tooth back. It flew off somewhere on this floor: he saw where.", True


def wanted_by(state: GameState, content: Content, key: str) -> str:
    """Who wants a thing you've got back, for its card ("Lucky Lenny wants it back."), or ""."""
    if key != BAD_TOOTH:
        return ""
    now = stage(state, LENNY)
    if now == "found_item":
        return "Someone called Lenny will be wanting it back."
    return "Lucky Lenny wants it back." if now not in ("done", "beaten") and needed(state, content, key) else ""
