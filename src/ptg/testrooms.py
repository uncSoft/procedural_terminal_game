"""Test rooms: straight to whoever you want to try (a character, a shop, a boss, any monster) with the kit you choose,
in a run that counts for nothing: it never autosaves over your real run and writes nothing to the profile (no souls,
no Hall of Legends, no ghost, no bestiary). From `ptg --test-room`, the debug screen (F12, Test rooms) or a served
game's test-rooms page (PTG_TEST_ROOMS=1).

You start next door, so walking in plays out as it would in a run: Swoogy's wall to bomb (a bomb's in your pack), a
shop's door (a small key, two bombs and 100 gold to spend), a boss's locked door (its key), Lucky Lenny with his bad
tooth in your pack (as if you'd found it first: lenny), or still missing it, hidden somewhere on his floor, for him to
tell you where (lenny_quest). Or down in the Underbloom, floor 5, where a run goes once you've won one
(docs/plans/floor-5.md): next door to a room nothing lights, with something in it, a torch and a flask of lamp oil in
your pack (underbloom), or no light at all (underbloom_dark); or by the web over the Sporefang Matriarch's lair, with
a torch to burn it and the Ring she wants (matriarch). His tooth is only ever on his own floor (there's no going back
up), so there's no room for it on the floor above him.

Kits (`loadout`): "new" (a new adventurer), "random" (gear, level and perks about where a run is by that floor),
"strong" (the best of everything), or your own: "weapon=war_pick,armor=chain_shirt,items=holy_water+pickle,level=3,
gold=50,bombs=2,keys=1" (anything left out is a new adventurer's).
"""

from __future__ import annotations

import random

from . import light, loot, npcs, powers
from .content import Content, load_content
from .models import DEEPEST, DELTA, DUNGEONS, FLOORS, LEVEL_XP, GameState, MonsterState, Player, Room
from .text import a, cap, the
from .world import LAIRS, build_floor, generate, monster_for, party, tier_for

# Who you can test besides the bosses and the monsters, and the floor each is tried on unless you say.
SPECIAL = {"lenny": ("Lucky Lenny, with his bad tooth in your pack", 1),
           "lenny_quest": ("Lucky Lenny, still missing his bad tooth: it's hidden on his floor", 1),
           "swoogy": ("Swoogy, behind a wall for you to bomb", 1),
           "king_mouse": ("King Mouse, guarding the floor-2 stairs", 2),
           "poison": ("Poisoned already, with a Pure in your pack and a shrine next door", 1),
           "shop": ("Granny Gristle's shop, at its door, with gold to spend", 1),
           "shiny_shop": ("Granny Kamultruk's shop, at its door, with gold to spend", 1),
           "underbloom": ("The Underbloom, floor 5: the Dark Hollow next door, with a torch and lamp oil", 5),
           "underbloom_dark": ("The Underbloom, floor 5, with no light of your own: the Dark Hollow next door", 5),
           "matriarch": ("The Sporefang Matriarch's lair, behind its web: a torch to burn it, and the Ring she wants",
                         5)}
DARK_ROOMS = {"underbloom": True, "underbloom_dark": False}  # the dark floor's rooms: whether you bring a torch
MATRIARCH, RING = LAIRS["underbloom"][1], "a_ring_probably_importan"  # (behind the web, and what she wants)
LENNYS = {"lenny": npcs.LENNY, "lenny_quest": npcs.LENNY}  # the rooms with Lucky Lenny next door
SHOP_GOLD = 100
LOADOUTS = {"new": "a new adventurer", "random": "random gear, as a run would have it on that floor",
            "strong": "the best of everything"}
LEVELS = {1: 1, 2: 3, 3: 5, 4: 6, 5: 7}  # about where a run is on each floor (5: where one would be, down that far)
STRONG = {"weapon": "silvered_blade", "armor": "scale_hauberk", "level": 5, "gold": 200, "bombs": 3, "keys": 2,
          "items": ["superior_healing_potion"] * 3 + ["holy_water", "smoke_bomb"]}
FIELDS = ("weapon", "armor", "items", "level", "gold", "bombs", "keys")  # a kit of your own


def choices(content: Content) -> dict[str, str]:
    """Who you can test, and what that means: the characters and shops, then the bosses, then anyone the maker's
    tagged npc, then every monster."""
    found = {key: words for key, (words, _) in SPECIAL.items()}
    for theme in sorted(content.themes.values(), key=lambda t: t.name):
        if theme.boss:  # (a floor still being made may have none yet)
            found[theme.boss] = f"{content.monster(theme.boss).name}, the boss of {theme.name}"
    for monster in sorted(content.monsters.values(), key=lambda m: (m.tier, m.name)):
        if monster.npc and monster.key not in npcs.PLACED and "shopkeeper" not in monster.tags:
            found.setdefault(monster.key, f"{monster.name}, to talk to")
    for monster in sorted(content.monsters.values(), key=lambda m: (m.tier, m.name)):
        if monster.roams:
            home = _home(content, monster.key)
            where = f", {content.themes[home].name}" if home else ""
            found.setdefault(monster.key, f"{monster.name} (tier {monster.tier}{where})")
    return found


def floors(content: Content) -> list[tuple[int, str]]:
    """The floors a test room can be on, as they're offered: the dungeons' three, then each floor that's always the
    same place, by its name, short (Norfel, the Underbloom)."""
    named = {theme.floor: theme.name.split(",")[0] for theme in content.themes.values() if theme.floor}
    return [(n, f"floor {n}: {named[n]}" if n in named else f"floor {n}") for n in range(1, DEEPEST + 1)]


def _home(content: Content, key: str) -> str:
    """The floor of its own a monster's kept to (`dungeons`: the Sporerat and the Hollowed, to the Underbloom), if
    that's the only place it lives: the theme's key, or ""."""
    themes = [content.themes[k] for k in content.monster(key).dungeons if k in content.themes]
    return themes[0].key if themes and all(t.floor for t in themes) else ""


def floor_for(content: Content, who: str) -> int:
    """The floor `who` is tried on unless you say (a dungeon's boss only ever on 3, Serpentis on 4, King Mouse on
    2, and a monster kept to a floor of its own on that floor: the Sporerat in the Underbloom, 5)."""
    if who in SPECIAL:
        return SPECIAL[who][1]
    boss_of = next((theme for theme in content.themes.values() if theme.boss == who), None)
    if boss_of:
        return boss_of.floor or DUNGEONS
    home = _home(content, who)
    return content.themes[home].floor if home else max(1, min(DUNGEONS, content.monster(who).tier))


def fixed_floor(content: Content, who: str) -> int:
    """The one floor `who` can be on, or 0 if it's up to you."""
    return floor_for(content, who) if who in ("king_mouse", "matriarch", *DARK_ROOMS) or \
        any(t.boss == who for t in content.themes.values()) else 0


def build(content: Content, who: str, loadout: str = "random", floor: int = 0, name: str = "Tester",
          seed: int | None = None):
    """A test run, standing next door to `who`, with the kit `loadout` names."""
    if who not in choices(content):
        raise ValueError(f"no test room {who!r}: try {', '.join(choices(content))}")
    rng = random.Random(seed)
    seed = rng.randrange(1_000_000) if seed is None else seed
    floor = fixed_floor(content, who) or max(1, min(DEEPEST, floor or floor_for(content, who)))  # (5: the Underbloom)
    boss_of = next((t.key for t in content.themes.values() if t.boss == who), None)
    if boss_of:
        state, start = _boss(content, seed, boss_of)
    elif who == "swoogy":
        state, start = _swoogy(content, seed, floor)
    elif who in ("shop", "shiny_shop"):
        state, start = _shop(content, seed, floor, loot.SHINY if who == "shiny_shop" else loot.SHOPKEEPER)
    elif who == "king_mouse":
        state, start = _king_mouse(content, seed)
    elif who == "poison":
        state, start = _shrine_floor(content, seed, floor)
    elif who in DARK_ROOMS:
        state, start = _dark_room(content, seed, floor)
    elif who == "matriarch":
        state, start = _lair(content, seed)
    else:
        state, start = _next_door(content, seed, floor, LENNYS.get(who, who))
    state.test_room, state.run_id, state.daily, state.ghost = who, None, "", None
    state.player = kit(content, state, loadout, floor, rng, name)
    player = state.player
    if who == "lenny":
        player.inventory.append(npcs.BAD_TOOTH)
        _only_yours(state, npcs.BAD_TOOTH)
        state.quests[npcs.LENNY] = "found_item"  # (as if you'd found it before you met him)
    elif who == "lenny_quest":
        player.inventory = [k for k in player.inventory if k != npcs.BAD_TOOTH]
        _only_yours(state, npcs.BAD_TOOTH)
        lenny = target(state)
        npcs.hide_tooth(state, [r for r in state.rooms if r.id not in (start, lenny.id) and not (r.secret or r.shop)]
                        or [lenny])
    elif who == "swoogy":
        player.bombs = max(player.bombs, 1)
    elif who == "poison":
        player.statuses["poison"] = 1
        player.inventory.append("pure")
    elif who in ("shop", "shiny_shop"):
        player.keys, player.bombs, player.gold = max(player.keys, 1), max(player.bombs, 2), max(player.gold, SHOP_GOLD)
    elif boss_of:
        player.inventory.append(content.themes[boss_of].key_item)
        _only_yours(state, content.themes[boss_of].key_item)
    elif who in DARK_ROOMS or who == "matriarch":  # (a torch to try, and oil to fill it with; or none: by the glow)
        player.inventory = [k for k in player.inventory if "torch" not in content.item(k).powers]
        player.inventory += ["torch", light.OIL] if DARK_ROOMS.get(who, True) else []
        if who == "matriarch":  # (what she wants, as if you'd found it in a secret room on the way down)
            player.inventory.append(RING)
            _only_yours(state, RING)
    if light.dark_floor(state, content) and DARK_ROOMS.get(who, True) and not light.torch(state, content):
        player.inventory.append("torch")  # (down in the dark, a light, as a run would bring one: not underbloom_dark)
    powers.settle_stats(state, content)
    room = state.rooms[start]
    state.room_id, room.visited = start, True
    room.far = room.river and room.exits.get(room.across) is not None \
        and room.exits[room.across].to == target(state, content).id  # (by the river's bank next door: no crossing)
    if room.monster and room.monster.hostile:
        room.monster, room.others = None, []  # (somewhere safe to stand)
    player.lit = light.lit(state, content)  # (your torch is lit already, down there: no telling you on your first go)
    return state


def kit(content: Content, state, loadout: str, floor: int, rng: random.Random, name: str) -> Player:
    """The player, kitted out (see the module's docstring)."""
    if loadout == "new":
        return Player(name=name)
    if loadout == "strong":
        spec = dict(STRONG)
    elif loadout == "random":
        gear = min(floor, DUNGEONS)  # (no tier-4 gear but the rare)
        spec = {"level": LEVELS[floor], "gold": 20 * floor + rng.randint(0, 20),
                "weapon": loot.pick(rng, content, f"weapon {gear}") or "rusty_sword",
                "armor": loot.pick(rng, content, f"armor {gear}"),
                "items": [k for k in [loot.pick(rng, content, f"potion {max(1, floor - 1)}"), "healing_potion",
                                      loot.pick(rng, content, "food 1+" if floor > 1 else "food 0"),
                                      loot.pick(rng, content, "trinket")] if k]}
    else:
        spec = custom(loadout)
    player = Player(name=name, bombs=1 + floor // 2, keys=floor // 2)
    state.player = player
    for _ in range(max(1, min(len(LEVEL_XP), int(spec.get("level", 1)))) - 1):  # with a perk a level, as in a run
        from .rules import _offer_perks, choose_perk

        player.level += 1
        player.max_hp += 2
        player.hp = player.max_hp
        _offer_perks(state, content)
        choose_perk(state, content, rng.choice(state.pending_perks))
    player.xp = LEVEL_XP[player.level - 1]
    for key in [spec.get("weapon"), spec.get("armor"), *spec.get("items", [])]:
        if key and key not in content.items:
            raise ValueError(f"there's no item {key!r} (the debug screen's Items tab has every item's key)")
    for field in ("weapon", "armor"):
        if spec.get(field):
            if content.item(spec[field]).kind != field:
                raise ValueError(f"{spec[field]!r} isn't {'a weapon' if field == 'weapon' else 'armor'}")
            setattr(player, field, spec[field])
    if "items" in spec:
        player.inventory = list(spec["items"])
    player.gold, player.bombs, player.keys = (int(spec.get(k, getattr(player, k))) for k in ("gold", "bombs", "keys"))
    return player


def custom(spec: str) -> dict:
    """"weapon=war_pick,items=holy_water+pickle,level=3" as a kit."""
    out: dict = {}
    for part in filter(None, (p.strip() for p in spec.split(","))):
        field, _, value = part.partition("=")
        field, value = field.strip(), value.strip()
        if field not in FIELDS or not value or (field in FIELDS[3:] and not value.isdigit()):
            raise ValueError(f"{part!r}: a kit is weapon=, armor=, items= (joined with +), or a number for level=, "
                             "gold=, bombs= or keys=")
        out[field] = [v.strip() for v in value.split("+") if v.strip()] if field == "items" else value
    return out


def target(state: GameState, content: Content | None = None) -> Room:
    """The room whoever you're testing is in (a shop, for a shop; the shrine, poisoned; the room nothing lights, down
    in the dark)."""
    who = {**LENNYS, "swoogy": npcs.SWOOGY, "matriarch": MATRIARCH}.get(state.test_room, state.test_room)
    keeper = {"shop": loot.SHOPKEEPER, "shiny_shop": loot.SHINY}.get(who)
    content = content or load_content()  # (which rooms are dark is the content's to say)
    here = state.room
    return min((r for r in state.rooms if (r.fixture == "shrine" if who == "poison" else
                                          light.pitch_dark(content, r) if who in DARK_ROOMS else
                                          r.shop.keeper == keeper if keeper and r.shop else
                                          r.monster is not None and r.monster.key == who)),
               key=lambda r: abs(r.x - here.x) + abs(r.y - here.y))


def describe(content: Content, state: GameState) -> list[tuple[str, str]]:
    """What a test run is, in a few lines: who's where, and your kit."""
    room, player = target(state, content), state.player
    way = next((d for d, (dx, dy) in DELTA.items() if (state.room.x + dx, state.room.y + dy) == (room.x, room.y)), "")
    name = content.monster(room.shop.keeper).name + "'s shop" if room.shop else \
        "A shrine" if state.test_room == "poison" else \
        f"{cap(the(room.name))}, pitch dark, {a(room.monster.name)} in it" if state.test_room in DARK_ROOMS \
        else room.monster.name
    gear = [content.item(k).name for k in (player.weapon, player.armor) if k]
    pack = {}
    for key in player.inventory:
        pack[content.item(key).name] = pack.get(content.item(key).name, 0) + 1
    return [("Next door", f"{name}, {way} (floor {state.floor}, seed {state.seed})"),
            ("You", f"level {player.level} · {player.hp}/{player.max_hp} HP · might {player.might} · agility "
                    f"{player.agility} · wits {player.wits}"),
            ("Perks", ", ".join(content.perks[k].name for k in player.perks) or "none"),
            ("Gear", " · ".join(gear)),
            ("Pack", ", ".join(f"{n} ×{c}" if c > 1 else n for n, c in pack.items()) or "nothing"),
            ("Also", f"{player.gold} gold · {player.bombs} bomb{'s' * (player.bombs != 1)} · {player.keys} small "
                     f"key{'s' * (player.keys != 1)}")]


def _only_yours(state: GameState, key: str) -> None:
    """The one in your pack is the floor's only one, as in a run: not another hidden somewhere (a tooth's own hiding
    place goes with it)."""
    for room in state.rooms:
        held = [f for f in room.features if key in f.loot]
        for feature in held:
            feature.loot = [k for k in feature.loot if k != key]
        gone = {id(f) for f in held if f.hidden and not (f.loot or f.gold)}
        room.features = [f for f in room.features if id(f) not in gone]
        room.items = [k for k in room.items if k != key]


# --- where you start --------------------------------------------------------------------------------------------------

def _at_floor(content: Content, seed: int, floor: int):
    state = generate(seed, content=content, floors=max(FLOORS, min(floor, DEEPEST)))  # (as deep as it needs to go)
    below = {t.floor: t.key for t in content.themes.values() if t.floor > len(state.themes)}
    if floor > len(state.themes):  # (a floor below the run's, still being made: as if the run went that far)
        state.themes += [below[f] for f in range(len(state.themes) + 1, floor + 1)]
        state.floors_total = floor
    if floor > 1:  # (straight there: what the floors before would have had doesn't matter here)
        state.floor = floor
        build_floor(state, content)
    return state


def _first(content: Content, seed: int, floor: int, fits):
    """The first dungeon from `seed` on whose floor `fits` finds what's wanted: (state, what it found)."""
    for tries in range(2000):
        state = _at_floor(content, seed + tries, floor)
        found = fits(state)
        if found is not None:
            return state, found
    raise RuntimeError("no dungeon had it")


def _next_door(content: Content, seed: int, floor: int, key: str):
    """Anyone (Lenny, any monster) in a room next to where you start."""
    state = _at_floor(content, seed, floor)
    start = state.rooms[0]
    room = state.rooms[next(e.to for e in start.exits.values() if not e.shut)]
    base = content.monster(key)
    if base.npc:  # (there's only one of each: not another somewhere else on the floor)
        for other in state.rooms:
            if other.monster and other.monster.key == key:
                other.monster = None
    room.monster = MonsterState(key=key, name=base.name, hp=base.hp, max_hp=base.hp, hostile=not base.npc,
                                mood="tooth" if key == npcs.LENNY else "")
    room.others = party(random.Random(seed), content, room.monster, floor)  # (a Sporerat never comes alone)
    return state, start.id


def _swoogy(content: Content, seed: int, floor: int):
    state, secret = _first(content, seed, floor, lambda s: next((r for r in s.rooms if r.secret), None))
    secret.monster = npcs.sized(content, npcs.SWOOGY, floor, npcs.SWOOGY_SIZE, hostile=False, mood="challenge")
    beside = next(r for r in state.rooms
                  if not r.secret and not r.shop and abs(r.x - secret.x) + abs(r.y - secret.y) == 1)
    return state, beside.id


def _shrine_floor(content: Content, seed: int, floor: int):
    """A floor with a shrine on it: you start next door (the step in burns)."""
    def beside(s):
        shrine = next((r for r in s.rooms if r.fixture == "shrine"), None)
        return next((s.rooms[e.to] for e in shrine.exits.values() if not e.shut and not s.rooms[e.to].secret
                     and not s.rooms[e.to].shop), None) if shrine else None
    state, start = _first(content, seed, floor, beside)
    return state, start.id


def _shop(content: Content, seed: int, floor: int, keeper: str):
    state, shop = _first(content, seed, floor,
                         lambda s: next((r for r in s.rooms if r.shop and r.shop.keeper == keeper), None))
    return state, next(iter(shop.exits.values())).to


def _king_mouse(content: Content, seed: int):
    state = _at_floor(content, seed, 2)
    stairs = next(r for r in state.rooms if r.fixture == "stairs")
    stairs.monster = npcs.sized(content, npcs.KING_MOUSE, 2, npcs.KING_MOUSE_SIZE, warden=True)
    return state, next(e.to for e in stairs.exits.values() if not e.shut)


def _dark_room(content: Content, seed: int, floor: int):
    """A dark floor (the Underbloom: below the run, so built as a run would build it if it went that far, with
    nothing at its end yet) with a room nothing lights next to where you start, something hostile in it."""
    def beside(s):
        hollow = next((r for r in s.rooms if light.pitch_dark(content, r) and not r.secret), None)
        start = next((s.rooms[e.to] for e in hollow.exits.values() if not e.shut and not s.rooms[e.to].secret
                      and not s.rooms[e.to].shop and not light.pitch_dark(content, s.rooms[e.to])), None) \
            if hollow else None
        return (hollow, start) if start else None
    state, (hollow, start) = _first(content, seed, floor, beside)
    if not (hollow.monster and hollow.monster.hostile):
        hollow.monster = monster_for(random.Random(seed), content, state.theme, tier_for(floor, state.floors_total),
                                     floor=floor)
    return state, start.id


def _lair(content: Content, seed: int):
    """The Underbloom with its lair (world._lair): you start in the room whose door is sealed with web."""
    def webbed(s):
        return next((r for r in s.rooms if any(e.webbed for e in r.exits.values())), None)
    state, start = _first(content, seed, 5, webbed)
    return state, start.id


def _boss(content: Content, seed: int, theme: str):
    floor = content.themes[theme].floor or DUNGEONS
    state, boss = _first(content, seed, floor, lambda s: next((r for r in s.rooms if r.is_boss), None)
                         if s.themes[floor - 1] == theme else None)
    gate = next(r for r in state.rooms if any(e.to == boss.id for e in r.exits.values()))
    return state, gate.id
