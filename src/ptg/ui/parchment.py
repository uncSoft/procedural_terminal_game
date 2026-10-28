"""The floor as a map drawn on parchment, for the Map panel (grid.ChartScreen): the rooms you know, the passages
between them, the paper's grain, its creases and its scorched edge, a compass rose and the floor's name across the
top, all drawn in pixels and shown in half blocks, with each room's name and what's in it written over its floor in
ink. A room you've been in is drawn in ink; one you've only seen through a door, faintly, in pencil; yours in red. A
room you can get back to is a click away ("travel", as on the chart: see widgets.StoryLine).

It keeps to a few colours of the sprites' palette (sprites.palette): a GPU terminal caches every pair of colours it
meets, and a map in a thousand shades of brown would fill it."""

from __future__ import annotations

import zlib

from PIL import Image
from rich.style import Style
from rich.text import Text

from ..rules import journey
from ..world import map_glyph
from .tabs import known_rooms

PAPER, GRAIN, FLOOR, EDGE, BURNT = "#e4a672", "#c28569", "#ead4aa", "#b86f50", "#733e39"
INK, PENCIL, RED, GILT = "#3e2731", "#b86f50", "#a22633", "#feae34"
# A chart note's colour (grid.room_notes), as an ink that reads on paper: a foe in red, someone in purple, what's
# lying there or a fixture in rust, a draft in blue, the rest faded.
INKS = {"#ff4b4b": RED, "#ff4f9a": "#68386c", "#ffd166": "#be4a2f", "#ffb000": "#be4a2f", "#5fe3ff": "#124e89"}
SLOT_MOST = (48, 15)  # the most a room's place on the map takes, (columns, rows), passage and all
ROOM_LEAST = (12, 3)  # the least a room's box needs to say anything, (columns, rows)
MARGIN = (4, 4, 2)  # columns each side, rows above (the scorched edge and the title), rows below
ROSE = [".....R.....", "....RRR....", "...RRRRR...", ".....R.....", "I....I....I", "IIIIIIIIIII", "I....I....I",
        ".....I.....", "....III...."]  # a compass rose, north in red
FLAG = "#e8b796"  # the joints between a room's flagstones
# The little pictures in a room's corner: what's there that matters. (I ink, N wood, Y gold, B and C water, R red.)
ICONS = {
    "stairs": ["......II", "....IIII", "..IIIIII", "IIIIIIII"],
    "chest": [".NNNNNN.", "NYYYYYYN", "NNNYYNNN", "NNNNNNNN"],
    "fountain": ["...C....", "..CBC...", "IIIIIIII", ".IIIIII."],
    "shrine": ["...Y....", "..YRY...", "IIIIIIII", ".I....I."],
    "foe": [".RRRRR..", "RR.R.RR.", "RRRRRRR.", ".R.R.R.."],
}
ICON_INKS = {"I": INK, "N": "#733e39", "Y": "#feae34", "B": "#0099db", "C": "#2ce8f5", "R": RED}


def _rgb(colour: str) -> tuple[int, int, int, int]:
    return int(colour[1:3], 16), int(colour[3:5], 16), int(colour[5:7], 16), 255


def _hex(pixel: tuple[int, ...]) -> str | None:
    return None if pixel[3] == 0 else f"#{pixel[0]:02x}{pixel[1]:02x}{pixel[2]:02x}"


def _speck(x: int, y: int, seed: int, every: int) -> bool:
    """A fleck of grain, the same on every drawing of the same floor."""
    return zlib.crc32(f"{seed}:{x}:{y}".encode()) % every == 0


def draw(state, width: int, height: int, title: str, labels: dict[int, str],
         notes: dict[int, list[tuple[str, str]]], hover: int | None = None) -> Text | None:
    """The map, at most `width` columns by `height` rows, or None if the floor won't fit at a size worth reading.
    `labels` is each known room's name on it (grid.room_label); `notes`, what's in each (grid.room_notes); `hover`,
    the room the mouse is on: if you can get back to it, it's drawn in gold, so it's plain that it's a click away."""
    rooms = known_rooms(state)
    min_x, min_y = min(r.x for r in rooms), min(r.y for r in rooms)
    across, down = max(r.x for r in rooms) - min_x + 1, max(r.y for r in rooms) - min_y + 1
    side, above, below = MARGIN
    slot_w = min(SLOT_MOST[0], (width - 2 * side + 4) // across)
    slot_r = min(SLOT_MOST[1], (height - above - below + 1) // down)
    gap_x, gap_r = max(4, slot_w // 5), max(1, slot_r // 4)
    room_w, room_r = slot_w - gap_x, slot_r - gap_r
    if room_w < ROOM_LEAST[0] or room_r < ROOM_LEAST[1]:
        return None
    cols = 2 * side + across * slot_w - gap_x
    rows = above + below + down * slot_r - gap_r
    seed = state.seed * 31 + state.floor
    img = Image.new("RGBA", (cols, rows * 2), _rgb(PAPER))
    px = img.load()

    def put(x: int, y: int, colour: str) -> None:
        if 0 <= x < cols and 0 <= y < rows * 2:
            px[x, y] = _rgb(colour)

    # The paper: flecks of grain, a crease each way where it was folded, and its edge scorched and torn.
    for y in range(rows * 2):
        for x in range(cols):
            if _speck(x, y, seed, 41):
                px[x, y] = _rgb(GRAIN)
    for y in range(rows * 2):
        if not _speck(cols // 2, y, seed, 3):
            put(cols // 2, y, GRAIN)
    for x in range(cols):
        if not _speck(x, rows, seed, 3):
            put(x, rows, GRAIN)
    for y in range(rows * 2):
        for x in range(cols):
            edge = min(x, cols - 1 - x, y, rows * 2 - 1 - y)  # (in pixels: a cell is one across, two down)
            corner = min(x, cols - 1 - x) + min(y, rows * 2 - 1 - y)
            if edge == 0 or corner < 3 or (edge == 1 and _speck(x, y, seed, 3)):
                px[x, y] = (0, 0, 0, 0)
            elif edge <= 1 or corner < 5:
                px[x, y] = _rgb(BURNT)
            elif edge == 2 or (edge == 3 and _speck(x, y, seed, 2)):
                px[x, y] = _rgb(EDGE)

    # The rooms, each a box in its place: ink for one you've been in, pencil (dashed) for one you've only seen, red
    # for yours; its floor pale, or the bare paper of one you haven't been in.
    places: dict[int, tuple[int, int, int, int]] = {}  # each room's (left, top row, right, bottom row)
    for room in rooms:
        left = side + (room.x - min_x) * slot_w
        top = above + (room.y - min_y) * slot_r
        places[room.id] = (left, top, left + room_w - 1, top + room_r - 1)
    mapped = state.mapped_floor == state.floor
    for room in rooms:
        left, top, right, bottom = places[room.id]
        here = room.id == state.room_id
        seen = room.visited or here
        lit = room.id == hover and not here and journey(state, room.id) is not None
        line = RED if here else GILT if lit else INK if seen else PENCIL
        y0, y1 = top * 2, bottom * 2 + 1
        for y in range(y0, y1 + 1):
            for x in range(left, right + 1):
                rim = x in (left, right) or y in (y0, y1) or (lit and (x in (left + 1, right - 1) or y in (y0 + 1,
                                                                                                          y1 - 1)))
                if rim:
                    if seen or (x + y) % 4 < 2:
                        put(x, y, line)
                elif seen:  # (its floor, flagstoned)
                    put(x, y, FLAG if (y - y0) % 4 == 0 or (x - left + (y - y0) // 4 * 3) % 8 == 0 else FLOOR)
    # The passages between them, where you know of them: a corridor of floor between ink walls, through a gap in
    # each room's wall (a locked door barred in red).
    for room in rooms:
        if not (room.visited or mapped):
            continue
        left, top, right, bottom = places[room.id]
        for direction, exit_ in room.exits.items():
            if exit_.to not in places:
                continue
            o_left, o_top, o_right, o_bottom = places[exit_.to]
            door = RED if exit_.locked else FLOOR
            if direction == "east":
                y = (top + room_r // 2) * 2  # (the middle row of the room, and of the one beside it)
                for x in range(right + 1, o_left):
                    put(x, y - 1, INK)
                    put(x, y, FLOOR)
                    put(x, y + 1, FLOOR)
                    put(x, y + 2, INK)
                for x in (right, o_left):
                    put(x, y, door)
                    put(x, y + 1, door)
            elif direction == "south":
                mid = left + room_w // 2 - 1
                for y in range(bottom * 2 + 2, o_top * 2):
                    put(mid - 1, y, INK)
                    put(mid, y, FLOOR)
                    put(mid + 1, y, FLOOR)
                    put(mid + 2, y, INK)
                for y in (bottom * 2 + 1, o_top * 2):
                    put(mid, y, door)
                    put(mid + 1, y, door)
    # In each room you've been in, a little picture in its corner of what's there: the stairs, a chest, a fountain or
    # a shrine not yet used, a foe still standing.
    for room in rooms:
        if not (room.visited or room.id == state.room_id):
            continue
        monster = room.monster if room.monster and room.monster.hp > 0 and room.monster.hostile else None
        kind = "foe" if monster else (room.fixture if room.fixture in ICONS and not room.fixture_used else "")
        left, top, right, bottom = places[room.id]
        art = ICONS.get(kind)
        if art and (bottom - top) >= 3 + len(notes.get(room.id, [])[:max(0, room_r - 3)]):
            x0, y0 = right - 2 - len(art[0]), bottom * 2 - 1 - len(art)
            for dy, row in enumerate(art):
                for dx, ink in enumerate(row):
                    if ink != ".":
                        put(x0 + dx, y0 + dy, ICON_INKS[ink])
    # A compass rose in the bottom right corner (its N over it), if no room is there.
    rose_x, rose_y = cols - side - len(ROSE[0]), rows * 2 - below * 2 - len(ROSE)
    rose = (rose_x - 1, rose_y // 2 - 2, rose_x + len(ROSE[0]), (rose_y + len(ROSE)) // 2)  # (cells, rows)
    clear = rose_x > side and rose[1] > above and all(
        right < rose[0] or left > rose[2] or bottom < rose[1] or top > rose[3] for left, top, right, bottom in
        places.values())
    if clear:
        for dy, row in enumerate(ROSE):
            for dx, ink in enumerate(row):
                if ink != ".":
                    put(rose_x + dx, rose_y + dy, RED if ink == "R" else INK)

    # Now in cells: each a pair of pixels (a half block), or a letter in ink over the paper or the floor.
    letters: dict[tuple[int, int], tuple[str, str, str]] = {}  # (column, row): (letter, ink, paper under it)

    def write(x: int, y: int, words: str, ink: str, under: str) -> None:
        for i, ch in enumerate(words):
            letters[(x + i, y)] = (ch, ink, under)

    name = "~ " + " ".join(title.upper()) + " ~"
    if len(name) > cols - 2 * side:
        name = title.upper()[:cols - 2 * side]
    write((cols - len(name)) // 2, 2, name, INK, PAPER)
    if clear:
        write(rose_x + len(ROSE[0]) // 2, rose_y // 2 - 1, "N", RED, PAPER)
    meta: dict[tuple[int, int], Style] = {}
    for room in rooms:
        left, top, right, bottom = places[room.id]
        here = room.id == state.room_id
        seen = room.visited or here
        reachable = not here and journey(state, room.id) is not None
        tip = Style(meta={"tip": labels[room.id] + (" (you're here)" if here else " (click to travel there)"
                                                    if reachable else ""),
                          **({"travel": room.id} if reachable else {})})
        for y in range(top, bottom + 1):
            for x in range(left, right + 1):
                meta[(x, y)] = tip
        under = FLOOR if seen else PAPER
        room_cols = right - left - 3  # (inside its walls, a column of floor each side)
        glyph = map_glyph(state, room)
        label = labels[room.id]
        first = f"{glyph} {label}" if len(label) + 2 <= room_cols else f"{glyph} {label[:room_cols - 3]}…"
        lit = room.id == hover and reachable
        write(left + 2, top + 1, first[:room_cols], RED if here else "#be4a2f" if lit else INK if seen else PENCIL,
              under)
        for i, (note, colour) in enumerate(notes.get(room.id, [])[:max(0, room_r - 3)]):
            note = note if len(note) <= room_cols else note[:room_cols - 1] + "…"
            write(left + 2, top + 2 + i, note, INKS.get(colour, PENCIL), under)

    pixels = img.load()
    text = Text(no_wrap=True)
    for y in range(rows):
        for x in range(cols):
            style = meta.get((x, y))
            if (x, y) in letters:
                ch, ink, under = letters[(x, y)]
                cell = Style(color=ink, bgcolor=under, bold=ink in (INK, RED))
                text.append(ch, cell + style if style else cell)
                continue
            top, bottom = _hex(pixels[x, y * 2]), _hex(pixels[x, y * 2 + 1])
            if top is None and bottom is None:
                text.append(" ", style)
            elif top == bottom:
                text.append(" ", Style(bgcolor=top) + style if style else Style(bgcolor=top))
            elif bottom is None:
                text.append("▀", Style(color=top) + style if style else Style(color=top))
            elif top is None:
                text.append("▄", Style(color=bottom) + style if style else Style(color=bottom))
            else:
                cell = Style(color=top, bgcolor=bottom)
                text.append("▀", cell + style if style else cell)
        text.append("\n")
    text.rstrip()
    return text
