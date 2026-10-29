"""Room floor plans. The engine owns positions (language models are bad at spatial consistency);
the narrator just gets told where things are."""

from __future__ import annotations

import random

from .content import Content
from .models import GameState, Room

WIDTH, HEIGHT = 25, 9  # interior size; the grid adds a wall all round

DOORS = {"north": (WIDTH // 2 + 1, 0), "south": (WIDTH // 2 + 1, HEIGHT + 1),
         "west": (0, HEIGHT // 2 + 1), "east": (WIDTH + 1, HEIGHT // 2 + 1)}
INSIDE = {"north": (0, 1), "south": (0, -1), "west": (1, 0), "east": (-1, 0)}
CENTRE = (WIDTH // 2 + 1, HEIGHT // 2 + 1)  # where a fixture stands
# The two cells inside each doorway, kept clear so you can come and go.
KEEP_CLEAR = {(x + k * dx, y + k * dy) for d, (x, y) in DOORS.items() for dx, dy in [INSIDE[d]] for k in (1, 2)}
CAGE = "▥"  # a cage, as decor and as a feature: not "#", which is wall

FEATURE_GLYPHS = {
    "cauldron": "Ö", "statue": "Ω", "idol": "Ω", "saint": "Ω", "altar": "╥", "bell": "Å", "gong": "Ø",
    "chest": "≡", "box": "≡", "case": "≡", "wardrobe": "▯", "desk": "π", "table": "π", "bench": "π",
    "barrel": "θ", "bowl": "∪", "basin": "∪", "fountain": "◊", "bucket": "∪", "well": "◘", "drain": "▒",
    "bones": "%", "skulls": "%", "skeleton": "%", "coffin": "▭", "shelf": "▤", "bookshelf": "▤",
    "lectern": "¶", "catalog": "▤", "candle": "ı", "candles": "ı", "lantern": "ı", "chandelier": "¥",
    "forge": "♨", "bathtub": "♨", "anvil": "┬", "rope": "§", "cage": CAGE, "trough": "∪", "cart": "Ð",
    "wheelbarrow": "Ð", "junk": "&", "pile": "&", "heap": "&", "sack": "ð", "plates": "°", "throne": "Ħ",
    "orrery": "☼", "telescope": "/", "chart": "▫", "mushroom": "♣", "puffball": "●", "fungus": "♣",
    "nest": "ö", "knot": "o", "sap": "~", "creepers": "§", "vine": "§", "plinth": "▪", "sword": "†",
    "mosaic": "▒", "heart": "♥", "pew": "π", "rail": "═", "niche": "∩", "alcove": "∩", "remains": "&",
    "flagstone": "▫", "wall": "▒", "bedroll": "≈", "boots": "ь", "dice": "⁘", "rack": "‡", "gap": "▒",
}

ITEM_GLYPHS = {"weapon": ")", "armor": "[", "consumable": "!", "key": "♀", "trinket": "("}
FIXTURE_GLYPHS = {"shrine": "†", "chest": "■", "fountain": "◊", "stairs": ">", "shop": "¤"}


def feature_glyph(name: str) -> str:
    for word in reversed(name.lower().replace("'", " ").split()):
        if word in FEATURE_GLYPHS:
            return FEATURE_GLYPHS[word]
    return "*"


def build(rng: random.Random, room: Room, decor: str) -> None:
    """Paint the walls, doors and decor, and place features, item spots and the monster."""
    grid = [["#"] * (WIDTH + 2)] + [["#"] + ["."] * WIDTH + ["#"] for _ in range(HEIGHT)] + [["#"] * (WIDTH + 2)]
    for direction in room.exits:
        x, y = DOORS[direction]
        grid[y][x] = "+"

    def free(x: int, y: int) -> bool:
        return 1 <= x <= WIDTH and 1 <= y <= HEIGHT and grid[y][x] == "." and (x, y) not in KEEP_CLEAR

    for style in decor.split():
        _paint(rng, grid, style, free, CENTRE)

    taken: set[tuple[int, int]] = set()

    def spot(near_wall: bool = False) -> tuple[int, int]:
        for _ in range(200):
            x, y = rng.randint(2, WIDTH - 1), rng.randint(2, HEIGHT - 1)
            if near_wall:
                side = rng.choice("nsew")
                x = {"w": 2, "e": WIDTH - 1}.get(side, x)
                y = {"n": 2, "s": HEIGHT - 1}.get(side, y)
            if free(x, y) and (x, y) not in taken and all(abs(x - tx) + abs(y - ty) > 2 for tx, ty in taken):
                taken.add((x, y))
                return x, y
        return CENTRE

    if room.fixture:
        taken.add(CENTRE)
    for feature in room.features:
        feature.pos = spot(near_wall=True)
    room.item_spots = [spot() for _ in range(6)]
    room.monster_pos = spot()
    room.grid = ["".join(row) for row in grid]


def _paint(rng: random.Random, grid, style: str, free, centre) -> None:
    def scatter(glyph: str, count: int) -> None:
        for _ in range(count):
            x, y = rng.randint(1, WIDTH), rng.randint(1, HEIGHT)
            if free(x, y):
                grid[y][x] = glyph

    def blob(glyph: str, cx: int, cy: int, rx: int, ry: int) -> None:
        for y in range(cy - ry, cy + ry + 1):
            for x in range(cx - rx, cx + rx + 1):
                if ((x - cx) / max(rx, 1)) ** 2 + ((y - cy) / max(ry, 1)) ** 2 <= 1.0 and free(x, y):
                    grid[y][x] = glyph

    if style == "water":
        for _ in range(rng.randint(2, 3)):
            blob("~", rng.randint(3, WIDTH - 2), rng.randint(2, HEIGHT - 1), rng.randint(2, 4), rng.randint(1, 2))
    elif style == "pool":
        blob("~", centre[0], centre[1], 3, 1)
    elif style == "pillars":
        for x in range(5, WIDTH - 2, 6):
            for y in (3, HEIGHT - 2):
                if free(x, y):
                    grid[y][x] = "O"
    elif style == "bones":
        scatter("%", 9)
    elif style == "rubble":
        for _ in range(3):
            blob(":", rng.randint(3, WIDTH - 2), rng.randint(2, HEIGHT - 1), rng.randint(1, 3), 1)
    elif style == "tables":
        for y in (3, HEIGHT - 2):
            for x in range(5, WIDTH - 4):
                if free(x, y) and x % 8 != 0:
                    grid[y][x] = "="
    elif style == "cages":
        for x in range(3, WIDTH, 5):
            if free(x, 2):
                grid[2][x] = CAGE
            if free(x, HEIGHT - 1):
                grid[HEIGHT - 1][x] = CAGE
    elif style == "junk":
        scatter("&", 10)
    elif style == "fungus":
        scatter("♣", 12)
    elif style == "plants":
        scatter("\"", 14)
    elif style == "roots":
        for _ in range(3):
            x, y = rng.randint(1, WIDTH), rng.choice([1, HEIGHT])
            for _ in range(rng.randint(5, 9)):
                if free(x, y):
                    grid[y][x] = "≀"
                x += rng.choice([-1, 0, 1])
                y += 1 if y < HEIGHT // 2 else -1
    elif style == "shelves":
        for x in range(2, WIDTH):
            if x % 7 and free(x, 1):
                grid[1][x] = "▤"
            if x % 7 and free(x, HEIGHT):
                grid[HEIGHT][x] = "▤"
    elif style == "furniture":
        scatter("π", 5)
    elif style == "embers":
        scatter("^", 8)
    elif style == "caps":  # mushrooms as tall as trees, never side by side
        placed: list[tuple[int, int]] = []
        for _ in range(rng.randint(3, 5)):
            for _ in range(20):
                x, y = rng.randint(2, WIDTH - 1), rng.randint(2, HEIGHT - 1)
                if free(x, y) and all(abs(x - px) + abs(y - py) > 4 for px, py in placed):
                    grid[y][x] = "♠"
                    placed.append((x, y))
                    break
    elif style == "threads":  # curtains of threads hanging from the ceiling, each a short line across the room
        for _ in range(rng.randint(2, 3)):
            x, y = rng.randint(3, WIDTH - 2), rng.randint(2, HEIGHT - 1)
            dx, dy = rng.choice([(1, 0), (0, 1)])
            for k in range(rng.randint(3, 6)):
                if free(x + k * dx, y + k * dy):
                    grid[y + k * dy][x + k * dx] = "¦"
    elif style == "puffballs":
        scatter("●", 8)


STYLE_OF_GLYPH = {"#": "wall", ".": "floor", "+": "door", "~": "water", "O": "pillar", "%": "bones",
                  ":": "rubble", "=": "furniture", "&": "junk", "♣": "plant", "\"": "plant", "≀": "plant",
                  "▤": "furniture", "π": "furniture", "^": "fire", CAGE: "cage", "♠": "plant", "¦": "plant",
                  "●": "plant"}


def item_spots(room: Room) -> list[tuple[int, int]]:
    """Where each of the room's items lies: the spots it was built with (see build), then for a room that has come to
    hold more (gear left behind, a monster's drops), more of its free floor, the same ones every time."""
    spots = list(room.item_spots[:len(room.items)])
    if len(spots) == len(room.items) or not room.grid:
        return spots + [CENTRE] * (len(room.items) - len(spots))
    taken = set(room.item_spots) | {f.pos for f in room.features} | {room.monster_pos, CENTRE}
    free = [(x, y) for y in range(1, HEIGHT + 1) for x in range(1, WIDTH + 1)
            if room.grid[y][x] == "." and (x, y) not in taken and (x, y) not in KEEP_CLEAR]
    random.Random(f"items {room.id}").shuffle(free)
    free.sort(key=lambda p: any(abs(p[0] - x) + abs(p[1] - y) <= 1 for x, y in taken))  # not right beside anything
    piles = list(spots) or [CENTRE]
    while len(spots) < len(room.items):  # once the floor's full, they pile up where others lie
        spots.append(free.pop(0) if free else piles[len(spots) % len(piles)])
    return spots


def render(state: GameState, content: Content) -> tuple[list[list[tuple[str, str]]], list[tuple[str, str, str]]]:
    """The current room as rows of (glyph, style) cells, plus a legend of (glyph, style, label)."""
    room = state.room
    rows = [[(ch, STYLE_OF_GLYPH.get(ch, "floor")) for ch in line] for line in room.grid]
    for y, line in enumerate(room.grid[1:HEIGHT + 1], 1):  # cages drawn as "#" in a game saved before they had theirs
        for x, ch in enumerate(line[1:WIDTH + 1], 1):
            if ch == "#":
                rows[y][x] = (CAGE, "cage")
    legend: list[tuple[str, str, str]] = []
    for direction, exit_ in room.exits.items():
        x, y = DOORS[direction]
        rows[y][x] = ("=" if exit_.locked else " ", "locked" if exit_.locked else "door")
    if room.fixture:
        cx, cy = CENTRE
        glyph = FIXTURE_GLYPHS[room.fixture]
        rows[cy][cx] = (glyph, "fixture_used" if room.fixture_used else "fixture")
        legend.append((glyph, "fixture", {"stairs": "stairs down"}.get(room.fixture, room.fixture)))
    for feature in room.features:
        if feature.hidden:
            continue
        glyph = feature_glyph(feature.name)
        x, y = feature.pos
        spent = feature.searched or bool(feature.used)
        rows[y][x] = (glyph, "feature_used" if spent else "feature")
        legend.append((glyph, "feature_used" if spent else "feature", feature.name))
    for key, (x, y) in zip(room.items, item_spots(room)):
        item = content.item(key)
        glyph = ITEM_GLYPHS.get(item.kind, "*")
        rows[y][x] = (glyph, "item")
        legend.append((glyph, "item", item.name))
    if room.monster:
        monster = room.monster
        base = monster.ghost_of and "G" or monster.name.removeprefix("The ")
        glyph = base[0].upper() if content.monster(monster.key).boss or monster.ghost_of else base.split()[-1][0].lower()
        x, y = room.monster_pos
        style = "monster" if monster.hostile else "calm"
        rows[y][x] = (glyph, "boss" if content.monster(monster.key).boss else style)
        legend.append((glyph, style, monster.name))
    px, py = player_pos(room)
    rows[py][px] = ("@", "player")
    legend.insert(0, ("@", "player", "you"))
    return rows, legend


def player_pos(room: Room) -> tuple[int, int]:
    if room.entered_from in DOORS:
        x, y = DOORS[room.entered_from]
        dx, dy = INSIDE[room.entered_from]
        return x + dx, y + dy
    return WIDTH // 2 + 1, HEIGHT


def where(pos: tuple[int, int]) -> str:
    """Rough compass position inside the room, for the narrator."""
    x, y = pos
    col = "west" if x <= WIDTH // 3 else ("east" if x > 2 * WIDTH // 3 else "")
    row = "north" if y <= HEIGHT // 3 else ("south" if y > 2 * HEIGHT // 3 else "")
    return f"{row}-{col}" if row and col else (row or col or "centre")


def plain_lines(state: GameState, content: Content) -> list[str]:
    rows, legend = render(state, content)
    lines = ["".join(ch for ch, _ in row) for row in rows]
    lines.append("  ".join(f"{g} {label}" for g, _, label in legend))
    return lines
