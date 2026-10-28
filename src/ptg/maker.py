"""`ptg maker`: the Monster & Item Maker on this computer, with Claude to draw.

    uv run ptg maker                  # opens http://127.0.0.1:8770
    uv run ptg maker --port 8800 --no-browser

It serves the page GitHub Pages serves (docs/maker), and here the page grows a Claude panel: ask for a monster or an
item and Claude draws it on the maker's own boards, frame by frame, gives it fair numbers, looks at it the way a fight
shows it (every pose, and an item's small version), and runs the game's own import checks. Then you save it, or add it
to the game from here. Claude is told how the game uses art (SYSTEM, below), so what it makes goes in as it is.

The page runs Claude's tools, since they change what's on its boards: you watch every stroke land and can undo it.
This server makes each call to the API, so the key never reaches the page. It keeps no conversation (each request
brings it whole) and answers only this computer: it listens on 127.0.0.1, refuses other Host names, and wants the
token it gave the page with every call, so another website can't spend your key.

Needs the claude extra (uv sync --extra claude --extra web). The key: ANTHROPIC_API_KEY, an `ant auth login` profile,
or the Claude key saved in the game's settings.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import secrets
import sys
import threading
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import library, sprites

DEFAULT_PORT = 8770
MODELS = {"claude-opus-5-5": "Claude Opus 5.5", "claude-sonnet-5-5": "Claude Sonnet 5.5",
          "claude-haiku-5-5": "Claude Haiku 5.5"}
DEFAULT_MODEL = "claude-opus-5-5"
EFFORTS = ("low", "medium", "high")
DEFAULT_EFFORT = "medium"
MAX_TOKENS = 64000  # thinking counts against it too
MAX_BODY = 40 * 1024 * 1024  # a long conversation carries a picture with most tool results
TERMINAL = "#090a13"  # the game's background (ui/theme.py), which the terminal draws sprites on

# The game's 32 colours (library.ENDESGA, the maker page's PALETTE), in the letters Claude draws with: a-z, then A-F.
COLOUR_NAMES = ("rust", "burnt orange", "sand", "tan", "brown", "dark brown", "plum shadow", "crimson",
                "red", "orange", "amber", "yellow", "green", "leaf green", "forest", "deep teal",
                "navy", "blue", "cyan", "white", "pale grey", "grey blue", "slate", "dark slate",
                "midnight", "near black", "hot red", "purple", "magenta", "salmon", "peach", "clay")
LETTERS = library.ALPHABET[:len(library.ENDESGA)]


def _rgb(hex_colour: str) -> tuple[int, int, int]:
    return tuple(int(hex_colour[i:i + 2], 16) for i in (1, 3, 5))


OUTLINE = [letter for letter, colour in zip(LETTERS, library.ENDESGA) if sprites._light(_rgb(colour)) < sprites.OUTLINE]
COLOURS = "\n".join("  ".join(f"{letter} {colour} {name:<12}" for letter, colour, name in row).rstrip()
                    for row in (list(zip(LETTERS, library.ENDESGA, COLOUR_NAMES))[i:i + 4] for i in range(0, 32, 4)))

# Everything Claude is told once, at the start of every request. It never changes while the server runs (nor between
# runs of the same code): a byte-identical prefix is what lets the API reuse it from its cache, and what keeps the
# thinking from earlier turns valid.
SYSTEM = f"""You make pixel art for the Procedural Terminal Game, a dungeon crawl played in a terminal, working inside
its Monster & Item Maker: the page the person is looking at. Your tools work on the maker's own boards, so the person
watches every stroke land, can undo it, and can draw on the boards themselves between messages.

The person might be a kid with an idea for a monster, or the game's owner. Follow their idea; ask one short question
only when you can't start without it. Keep what you write short and friendly, and everything fit for kids. Never fill
in "Created by" (that's theirs), and never say something is saved or in the game: only the person saves it.

HOW THE GAME SHOWS ART
- A monster or an item is a 24x24 picture on a see-through background, with two frames, or up to four. The game plays
  them in order and round again as its idle animation, 0.6 seconds each. Frame 1 matters most: it's also the one
  that dies.
- Two frames is the usual. A monster's frame 2 is the bob: everything above the bottom five rows sinks a pixel while
  the bottom five rows (the feet) stay put (make_frame "bob"). An item's is the whole picture a pixel lower
  (make_frame "drop", which needs the bottom row empty) or a glint or a blink. For anything more (a blink, a flicking
  tail) copy frame 1 into frame 2 and change only a few pixels, so it reads as one thing moving, not two pictures.
- Frames 3 and 4 are for a longer loop, when the person asks for one or the idea needs it (a flapping wing, a dancing
  flame, a swirl): each a small step on from the one before, the last leading back into frame 1. Draw every frame
  up to the last one used: a gap loses the frames after it.
- In a fight the game makes poses from the frames: windup (raised a pixel, a red-orange glow round the silhouette: a
  heavy blow is coming), dizzy (stars circle just above its head), lunge (down a pixel or two, recoloured in reds),
  shake (a pixel side to side), hit (a white flash) and death (frame 1 dissolves in a dither, going grey). Poses crop
  at the frame's edges and the glow needs empty pixels round the silhouette, so keep a pixel clear on every side (two
  at the bottom, unless the feet are planted). Lunge, hit and death keep only how light each pixel is, so the thing
  must read by light against dark, not by hue alone.
- The terminal shows each pixel as half a character cell on a near-black background ({TERMINAL}). The house style:
  a 1-pixel outline in {", ".join(OUTLINE)} all round the silhouette, and nothing but outline on the frame's border.
  {", ".join(OUTLINE)} is the only colour dark enough to count as outline, and it barely shows on the terminal, so the
  thing reads by its lit colours: a clear silhouette, big simple shapes, two or three shades per material, light from
  the top left, bright eyes. Keep {", ".join(OUTLINE)} for the outline and the deepest shadow.
- Make it big: the box round its pixels (all its frames together) covers at least half the frame. Monsters stand on
  the ground, feet on the bottom rows, centred. Items float, centred.
- An item also has a small version, 12x12, for the inventory, its card and room pictures. Nearly every item in the
  game has one drawn by hand: draw it with small, as the same picture redrawn at half size rather than the drawing
  shrunk, with only colours the drawing uses, filling at least three quarters as much of its frame as the drawing
  does, and as many frames as the drawing, moving the same way. It needs no outline. Monsters have no small version.
- Use only the game's 32 colours. The importer flags anything else.
- Changing something already in the game: keep every colour it uses now (the floors' splash art borrows some), keep it
  recognisably the same thing, and change what was asked.
- Tidying a drawing someone made: keep it recognisably theirs. Give it the outline, move its colours to the 32, pull
  limbs in from the frame's edge, and draw an item's small version.

THE COLOURS (letter, colour, name; "." is see-through)
{COLOURS}

DRAWING IN LETTERS
A frame is 24 rows of 24 letters, top row first: one letter per pixel, x counting from 0 at the left and y from 0 at
the top. Draw a whole frame at once with draw and fix single pixels with paint. Count every row: exactly 24 letters.
Creatures read best mirrored left to right, unless the idea says otherwise.

THE DETAILS
Monsters: a name (up to 40 letters); a tier, 1 to 3 (4 is for bosses), which decides how deep it turns up (tier 1
on the first floor, tier 3 on the third and below); hp, defense, attack, damage dice (like 1d6 or 2d4+1) and xp close
to the typical numbers for its tier; its creature types; the floors it shows up on (dungeons), each floor a dungeon
with a feel of its own; weaknesses (things that work especially well against it); whether it's intelligent (it can be
talked down, bribed or bluffed); a tell, what it does just before a heavy blow, finishing "The Bog Cantor ..."; and a
description of how it looks and behaves, which the game's narrator reads.
Pick its floors every time: kept to none, a monster turns up on every floor that has its creature type, and a beast
or a goblinoid is on nearly all of them. Keep it to the one or two that suit it, or to the ones the person asks for.
Norfel, always the fourth floor, only draws tier 3 and up.
Items: a name; a kind (weapon: damage dice; armor: a defense bonus; consumable: heals, or lets you escape a fight;
trinket: no numbers, its tags and description do the work); a tier, 0 to 3; tags (used for stunts and for monster
weaknesses); and a description.
look shows the choices for each and the typical numbers for each tier.

HOW TO WORK
1. look first: the person may have drawn something already, or opened something from the game to change.
2. Look at one or two things already in the game with game_art, for the house style (similar creatures, or the thing
   being changed).
3. Draw frame 1 with draw, look at it with see_in_game, and fix what doesn't read with paint or another draw.
4. Make frame 2 (and 3 and 4, for a longer loop). For an item, draw its small version, every frame, with small.
5. Set the details with details, the floors it shows up on too.
6. Run check: the maker's rules, the game's own art tests and its importer, as a dry run. Fix what it reports and
   check again.
7. Finish in two or three sentences: what you made and the floors it shows up on, and that they can put their name
   in "Created by" and press Save (or "Add to the game" in this panel, if this is the game's own computer).
Before each group of tool calls, write one short line saying what you're about to do: the person reads them as you
go."""

FRAME = {"type": "integer", "enum": [1, 2, 3, 4],
         "description": "Which frame: 1 is the picture, 2 the idle's next step, 3 and 4 a longer loop's."}
ROWS = {"type": "array", "items": {"type": "string"}}
NOTHING = {"type": "object", "properties": {}}
TOOLS = [
    {"name": "look",
     "description": "See the board as it is now: the creation's type and details, each frame as rows of letters and as "
                    "a picture, an item's small version, the choices for each detail, the typical numbers for each "
                    "tier, and anything the maker would refuse to save.",
     "input_schema": NOTHING},
    {"name": "draw",
     "description": "Replace a whole frame of the 24x24 drawing. rows: 24 strings, top row first, each exactly 24 "
                    "characters: a colour letter per pixel, '.' for see-through.",
     "input_schema": {"type": "object", "properties": {"frame": FRAME, "rows": {**ROWS, "description": "24 rows of 24"}},
                      "required": ["frame", "rows"]}},
    {"name": "paint",
     "description": "Change single pixels of a frame: touch-ups after draw. c is a colour letter, or '.' to clear.",
     "input_schema": {"type": "object", "properties": {
         "frame": FRAME,
         "pixels": {"type": "array", "items": {"type": "object", "properties": {
             "x": {"type": "integer", "minimum": 0, "maximum": 23}, "y": {"type": "integer", "minimum": 0, "maximum": 23},
             "c": {"type": "string"}}, "required": ["x", "y", "c"]}}},
         "required": ["frame", "pixels"]}},
    {"name": "make_frame",
     "description": "Make a frame from the one before it (or from: an earlier one). frame: 2 to 4, 2 if left out. bob: "
                    "the idle bob (everything above the bottom five rows sinks a pixel, the feet stay). drop: the whole "
                    "picture a pixel lower (only when its bottom row is empty). copy: an exact copy, to change a few "
                    "pixels with paint. clear: empty (an empty frame 2 in a two-frame animation is the game's own bob). "
                    "board: \"small\" does it to an item's small version instead (its feet are two rows).",
     "input_schema": {"type": "object", "properties": {
         "make": {"type": "string", "enum": ["bob", "drop", "copy", "clear"]},
         "frame": {"type": "integer", "enum": [2, 3, 4]}, "from": {"type": "integer", "enum": [1, 2, 3]},
         "board": {"type": "string", "enum": ["drawing", "small"]}}, "required": ["make"]}},
    {"name": "small",
     "description": "Items only: draw the 12x12 small version, the picture the inventory, cards and room pictures "
                    "show. frame and rows (12 strings of 12 characters) draw one frame of it by hand; auto: true "
                    "goes back to the drawing halved.",
     "input_schema": {"type": "object", "properties": {"frame": FRAME, "rows": {**ROWS, "description": "12 rows of 12"},
                                                       "auto": {"type": "boolean"}}}},
    {"name": "details",
     "description": "Set the creation's details; leave out what stays the same. Monsters: name, tier, hp, defense, "
                    "attack, damage, xp, tags (creature types, plus any extra tags), dungeons (the floors it shows up on, by "
                    "key: look lists them; [] for every floor its creature types fit), weak, intelligent, tell, desc. "
                    "Items: name, kind, tier, damage (weapons), defense (armor), heal or escape (consumables), tags, "
                    "desc. tier_defaults: true sets the typical numbers for its tier first.",
     "input_schema": {"type": "object", "properties": {
         "name": {"type": "string"}, "tier": {"type": "integer"}, "hp": {"type": "integer"},
         "defense": {"type": "integer"}, "attack": {"type": "integer"}, "damage": {"type": "string"},
         "xp": {"type": "integer"}, "tags": {"type": "array", "items": {"type": "string"}},
         "dungeons": {"type": "array", "items": {"type": "string"}},
         "weak": {"type": "array", "items": {"type": "string"}}, "intelligent": {"type": "boolean"},
         "tell": {"type": "string"}, "desc": {"type": "string"},
         "kind": {"type": "string", "enum": ["weapon", "armor", "consumable", "trinket"]},
         "heal": {"type": "integer"}, "escape": {"type": "boolean"}, "tier_defaults": {"type": "boolean"}}}},
    {"name": "new_creation",
     "description": "Start a fresh board for a new monster or item. What's on the board now stays in the person's My "
                    "work.",
     "input_schema": {"type": "object", "properties": {"type": {"type": "string", "enum": ["monster", "item"]}},
                      "required": ["type"]}},
    {"name": "game_art",
     "description": "Something already in the game: its picture, its rows and its details, by name or key. Leave out "
                    "name for a list of everything. edit: true opens it on the board as a change to the game's own "
                    "(only when the person wants it changed).",
     "input_schema": {"type": "object", "properties": {"name": {"type": "string"}, "edit": {"type": "boolean"}}}},
    {"name": "see_in_game",
     "description": "See the creation as the game shows it, on the terminal's dark background: the idle animation, "
                    "every pose a fight puts it in (windup, dizzy, lunge, shake, hit, the death dissolve) and an "
                    "item's small version.",
     "input_schema": NOTHING},
    {"name": "check",
     "description": "Check the creation as it is now, nothing saved: the maker's rules, the game's own art tests "
                    "(outline, filling its frame, idle frames that keep their feet, a small version that matches, the "
                    "floors' colours) and its importer, which says whether the game still loads with it in.",
     "input_schema": NOTHING},
]
for _tool in TOOLS:  # the page validates every input, since streamed inputs arrive unchecked
    _tool["eager_input_streaming"] = True


def request(messages: list, model: str = DEFAULT_MODEL, effort: str = DEFAULT_EFFORT) -> dict:
    """The parameters for one turn of the conversation the page sent."""
    model = model if model in MODELS else DEFAULT_MODEL
    params = {"model": model, "max_tokens": MAX_TOKENS,
              "system": [{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
              "tools": TOOLS, "messages": messages,
              "output_config": {"effort": effort if effort in EFFORTS else DEFAULT_EFFORT},
              "cache_control": {"type": "ephemeral"}}  # and the conversation so far
    if model == "claude-haiku-5-5":  # no progress notes or server-side fallback for Haiku
        params["thinking"] = {"type": "adaptive", "display": "summarized"}
    else:  # its notes between tool calls, as short summaries; a declined request retried on another model
        params["thinking"] = {"type": "adaptive", "display": "updates"}
        params["betas"] = ["thinking-display-updates-2026-08-18", "server-side-fallback-2026-07-01"]
        params["fallbacks"] = "default"
    return params


def relay(stream, send) -> None:
    """Pass a turn on to the page as it comes (its words, its notes, the tools it reaches for), then the whole message
    for the page to keep and act on."""
    for event in stream:
        if event.type == "content_block_start":
            block = event.content_block
            if block.type == "tool_use":
                send({"type": "tool", "name": block.name})
            elif block.type == "fallback":
                send({"type": "fallback", "model": getattr(getattr(block, "to", None), "model", "")})
        elif event.type == "content_block_delta":
            delta = event.delta
            if delta.type == "text_delta":
                send({"type": "text", "text": delta.text})
            elif delta.type == "thinking_delta" and delta.thinking:
                send({"type": "note", "text": delta.thinking})
    message = stream.get_final_message()
    data = message.model_dump(mode="json", by_alias=True, exclude_none=True)
    usage = data.get("usage") or {}
    send({"type": "message", "content": data["content"], "stop_reason": data.get("stop_reason"),
          "stop_details": data.get("stop_details"), "model": data.get("model"),
          "usage": {k: usage.get(k) or 0 for k in ("input_tokens", "output_tokens", "cache_read_input_tokens",
                                                   "cache_creation_input_tokens")}})


# --- the game's own word on a creation --------------------------------------------------------------------------------

def check(creation: dict, folder: Path | None = None) -> dict:
    """What the game says about a creation: its art tests, run on these pictures (art_notes), and its importer, doing
    everything `uv run ptg import` would as a dry run (ok is whether it would take it)."""
    notes = art_notes(creation)
    try:
        said = library.apply([creation], folder, dry_run=True)
    except (ValueError, KeyError, IndexError, TypeError) as error:
        return {"ok": False, "said": [str(error)], "art": notes}
    return {"ok": True, "said": [line for line in said if not line.startswith("(dry run")], "art": notes}


INK = _rgb("#181425")  # the outline, as the art tests know it
UNLINED = 12  # lit pixels on a silhouette's edge before it counts as not outlined (see art_notes)


def _hex(rgb: tuple) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb[:3])


def _colours(frames) -> set:
    return {pixel[:3] for frame in frames or () for pixel in frame.get_flattened_data() if pixel[3] >= 128}


def _fill(frames) -> float:
    """sprites.fill, for pictures that aren't in the game yet."""
    boxes = [box for frame in frames if (box := frame.getbbox())]
    if not boxes:
        return 0.0
    width = max(box[2] for box in boxes) - min(box[0] for box in boxes)
    height = max(box[3] for box in boxes) - min(box[1] for box in boxes)
    return width * height / (frames[0].width * frames[0].height)


def _unlined(frame) -> int:
    """Pixels on the silhouette's edge or the frame's border that aren't outline (test_kids_art's outline test)."""
    px, (w, h) = frame.load(), frame.size
    return sum(1 for y in range(h) for x in range(w)
               if px[x, y][3] >= 128 and sprites._light(px[x, y][:3]) >= sprites.OUTLINE
               and any(not (0 <= x + dx < w and 0 <= y + dy < h) or px[x + dx, y + dy][3] < 128
                       for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))))


def _lone_ink(frame) -> int:
    """Outline pixels with no colour round them, even corner to corner: a second ring (test_kids_art)."""
    px, (w, h) = frame.load(), frame.size
    return sum(1 for y in range(h) for x in range(w) if px[x, y][3] >= 128 and px[x, y][:3] == INK
               and not any(0 <= x + dx < w and 0 <= y + dy < h and px[x + dx, y + dy][3] >= 128
                           and px[x + dx, y + dy][:3] != INK for dx in (-1, 0, 1) for dy in (-1, 0, 1)))


def _slides_off(frames) -> bool:
    """A later frame is frame 1 slid down whole while frame 1 uses its bottom row (test_kids_art, test_library)."""
    from PIL import Image

    first = frames[0]
    slid = Image.new("RGBA", first.size, (0, 0, 0, 0))
    slid.paste(first, (0, 1))
    bottom = first.crop((0, first.height - 1, first.width, first.height)).get_flattened_data()
    return any(pixel[3] >= 128 for pixel in bottom) and any(f.tobytes() == slid.tobytes() for f in frames[1:])


def _splash_lost(creation: dict, frames, small) -> list[str]:
    """Colours the floors' splash art uses that no sprite would have once this one replaces its old picture (test_sprites:
    splash art keeps to the sprites' colours, and some of them are in one sprite only)."""
    if not creation.get("base"):
        return []
    from .content import load_content

    key = creation["base"] if creation.get("type") == "monster" else f"item_{creation['base']}"
    folder = library.data_folder() / "sprites"
    others = [p for p in [*folder.glob("*.png"), *(folder / "small").glob("*.png")] if p.stem != key]
    kept = set().union(*(_colours(library.read_frames(p)) for p in others), _colours(frames), _colours(small),
                       {sprites.GLOW[0], sprites.GLOW[1], sprites.STAR, *sprites.GREYS, *sprites.REDS, *sprites.LIGHTS})
    used = {pixel[:3] for theme in load_content().themes for width, _ in sprites.splash_sizes(theme)
            for pixel in sprites.splash(theme, width).get_flattened_data()}
    return sorted(_hex(colour) for colour in used - kept)


def art_notes(creation: dict) -> list[str]:
    """The game's own art tests (tests/test_kids_art.py, test_library.py, test_sprites.py) on a creation's pictures,
    before they're in: what each would complain about, or nothing."""
    try:
        frames = library.decode_art(creation["art"])  # (an empty frame 2 bobs, as it will in the game)
        small = library.decode_art(creation["small"]) if creation.get("small") else None
    except (KeyError, TypeError, ValueError, IndexError):
        return []  # nothing drawn, or nothing the importer would take: it says which
    notes, line = [], OUTLINE[0]
    # The kids' monsters are tested for a perfect ring; the game's own art keeps a few lit pixels on its edges (eyes,
    # glints: up to 10 in its monsters' first frames), so only a missing outline is worth a word.
    if (unlined := _unlined(frames[0])) > UNLINED:
        notes.append(f"{unlined} pixels round frame 1's silhouette (or on the frame's border) aren't outline: give it "
                     f"a 1-pixel {line} outline all round, inside the frame (a few glints on the edge are fine).")
    fill = _fill(frames)
    if fill < 0.5:
        notes.append(f"It fills {fill:.0%} of its frame; the game's art fills at least half (its monsters 54-100%). "
                     "Draw it bigger.")
    sent = len(creation["art"].get("frames") or ())
    if sent > 2 and len(frames) == 2:  # (an empty frame 2 makes the importer bob frame 1 and leave the rest)
        notes.append(f"Frame 2 is empty, so the importer would bob frame 1 and leave out frames 3 to {sent}: draw "
                     "frame 2.")
    if empty := [n for n, frame in enumerate(frames[2:], 3) if not frame.getbbox()]:
        notes.append(f"Frame {' and '.join(map(str, empty))} is empty, and the game would play it: draw it, or send "
                     "fewer frames.")
    if _slides_off(frames):
        notes.append("A later frame is frame 1 slid down a pixel, and frame 1 uses its bottom row, which falls off: "
                     "bob it, or empty that row.")
    for n, frame in enumerate(frames[1:], 2):
        if _lone_ink(frame) > _lone_ink(frames[0]) + 2:
            notes.append(f"Frame {n} has a second ring of outline ({line} with no colour beside it): outline it once.")
    if creation.get("type") == "item" and not small:
        notes.append("No small version: the game would halve the drawing. Nearly every item has one drawn by hand.")
    elif creation.get("type") == "item":
        if len(small) != len(frames):
            notes.append(f"The small version has {len(small)} frames and the drawing {len(frames)}: the game wants "
                         "the same number.")
        if extra := _colours(small) - _colours(frames):
            notes.append("The small version uses colours the drawing doesn't: "
                         + ", ".join(_hex(c) for c in sorted(extra)) + ".")
        if _fill(small) < 0.75 * fill:
            notes.append(f"The small version fills {_fill(small):.0%} of its frame, under three quarters of the "
                         f"drawing's {fill:.0%}: draw it bigger.")
        if _slides_off(small):
            notes.append("A frame of the small version slides its bottom row off: bob it, or empty that row.")
    if lost := _splash_lost(creation, frames, small):
        notes.append(f"Without {', '.join(lost)}, the floors' splash art loses colours only the old picture had: "
                     "use them somewhere in it.")
    return notes


def preview(creation: dict) -> dict:
    """The creation as a fight shows it, on the terminal's background: a row for each pose (idle, windup, dizzy, lunge,
    shake, hit, death) through the game's own sprites.posed, and an item's small version, as one PNG."""
    from PIL import Image, ImageDraw

    try:
        frames = library.decode_art(creation["art"])
        small = library.decode_art(creation["small"]) if creation.get("small") else [sprites.halve(f) for f in frames]
    except (KeyError, TypeError, ValueError, IndexError) as error:
        return {"ok": False, "said": f"nothing to show: {error}"}
    hit = sprites._recolour(frames[0], lambda r, g, b: sprites._shade(sprites.LIGHTS, r, g, b))
    n = len(frames)  # (poses go round its frames as the idle does: sprites._render)
    rows = [("idle", frames), ("windup", [sprites.posed(frames[i % n], "windup", i) for i in range(max(2, n))]),
            ("dizzy", [sprites.posed(frames[i % n], "dizzy", i) for i in range(4)]),  # the stars go round in 4
            ("lunge", [sprites.posed(frames[i % n], "lunge", i) for i in range(2)]),
            ("shake", [sprites.posed(frames[i % n], "shake", i) for i in range(2)]), ("hit", [hit]),
            ("death", [sprites.posed(frames[0], "death", i) for i in range(sprites.DEATH_FRAMES)])]
    if creation.get("type") == "item":
        rows.append(("small", small))
    scale, cell, label = 4, 104, 56
    sheet = Image.new("RGB", (label + cell * max(len(r) for _, r in rows), cell * len(rows)), _rgb(TERMINAL))
    pen = ImageDraw.Draw(sheet)
    for y, (name, pictures) in enumerate(rows):
        pen.text((6, y * cell + cell // 2 - 6), name, fill=(163, 166, 200))
        for x, picture in enumerate(pictures):
            big = picture.resize((picture.width * scale, picture.height * scale), Image.NEAREST)
            at = (label + x * cell + (cell - big.width) // 2, y * cell + (cell - big.height) // 2)
            sheet.paste(big, at, big)
    buffer = io.BytesIO()
    sheet.save(buffer, format="PNG")
    drawn = creation["art"]["frames"]
    bobbing = len(drawn) < 2 or all(set(row) <= {"."} for row in drawn[1])
    note = "Frame 2 is empty, so the idle row shows the game's own bob. " if bobbing else ""
    return {"ok": True, "image": base64.b64encode(buffer.getvalue()).decode(),
            "said": note + "Each row is a pose, left to right in time, at 4x on the terminal's background."}


# --- the server ----------------------------------------------------------------------------------------------------

class Studio:
    """The Claude panel's side of the server: the API client (made when first needed), why the panel is off if it
    is, the token the page must show, and the data folder "Add to the game" writes to (the game's own unless a test
    says otherwise)."""

    def __init__(self, client=None, folder: Path | None = None):
        self.token = secrets.token_urlsafe(24)
        self.client = client
        self.folder = folder
        self.problem = "" if client else _problem()
        self.adding = threading.Lock()

    def api(self):
        if self.client is None:
            import anthropic

            own = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
            self.client = anthropic.Anthropic(api_key=None if own else (_saved_key() or None))
        return self.client


def _saved_key() -> str:
    """The Claude key saved in the game's settings, if its narrator is Claude."""
    from .config import load_config

    config = load_config()
    return config.api_key if config and config.backend == "anthropic" else ""


def _problem() -> str:
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return "Claude needs the claude extra: uv sync --extra claude --extra web, then start ptg maker again"
    if (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN") or _saved_key()
            or (Path.home() / ".config" / "anthropic").is_dir()):
        return ""
    return "Claude needs a key: set ANTHROPIC_API_KEY (or run `ant auth login`), then start ptg maker again"


class Handler(SimpleHTTPRequestHandler):
    """docs/maker as files, studio.json for the page to find the panel, and the panel's /api/ calls."""

    studio: Studio

    def log_message(self, *args) -> None:  # quiet: a line for each Claude turn is enough (see turn)
        pass

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _local(self) -> bool:
        """Asked for by this computer's own name: a page another site pointed at 127.0.0.1 isn't."""
        host = self.headers.get("Host", "")
        return host in (f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}")

    def _json(self, data: dict, status: int = 200) -> None:
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if not self._local():
            return self._json({"error": "this server only answers 127.0.0.1"}, 403)
        if self.path.split("?")[0] == "/studio.json":
            studio = self.studio
            return self._json({"enabled": not studio.problem, "problem": studio.problem, "token": studio.token,
                               "models": MODELS, "model": DEFAULT_MODEL, "efforts": EFFORTS, "effort": DEFAULT_EFFORT})
        return super().do_GET()

    def do_POST(self) -> None:
        if not self._local():
            return self._json({"error": "this server only answers 127.0.0.1"}, 403)
        if not secrets.compare_digest(self.headers.get("X-Maker-Token", ""), self.studio.token):
            return self._json({"error": "this page didn't come from this server: reload it"}, 403)
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            return self._json({"error": "that's too big"}, 413)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return self._json({"error": "that wasn't JSON"}, 400)
        path = self.path.split("?")[0]
        if path == "/api/claude":
            return self.turn(body)
        if path in ("/api/check", "/api/preview", "/api/add") and not isinstance(body.get("creation"), dict):
            return self._json({"error": "there's no creation in that"}, 400)
        if path == "/api/check":
            return self._json(check(body["creation"], self.studio.folder))
        if path == "/api/preview":
            return self._json(preview(body["creation"]))
        if path == "/api/add":
            return self._json(self.add(body["creation"]))
        return self._json({"error": "no such thing"}, 404)

    def add(self, creation: dict) -> dict:
        """Into the game's data, as `uv run ptg import` would: the sprite, the entry with its credit, re-signed, and
        library.json refreshed."""
        if not str(creation.get("by") or "").strip():
            return {"ok": False, "said": ["Put a name in Created by first: it's the credit in the game."]}
        with self.studio.adding:
            try:
                said = library.apply([creation], self.studio.folder)
            except (ValueError, KeyError, IndexError, TypeError) as error:
                return {"ok": False, "said": [str(error)]}
        print("Added to the game: " + " ".join(said), flush=True)
        return {"ok": True, "said": said}

    def turn(self, body: dict) -> None:
        """One turn of the conversation, streamed to the page as server-sent events."""
        if self.studio.problem:
            return self._json({"error": self.studio.problem}, 503)
        messages = body.get("messages")
        if not isinstance(messages, list) or not messages:
            return self._json({"error": "there's no conversation in that"}, 400)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()

        def send(event: dict) -> None:
            self.wfile.write(b"data: " + json.dumps(event).encode() + b"\n\n")
            self.wfile.flush()

        params = request(messages, body.get("model", DEFAULT_MODEL), body.get("effort", DEFAULT_EFFORT))
        try:
            import anthropic

            try:
                with self.studio.api().beta.messages.stream(**params) as stream:
                    relay(stream, _logged(send, params["model"]))
            except ValueError:  # a tool's streamed input that isn't JSON at all: the page asks for the turn again
                send({"type": "retry"})
            except anthropic.AuthenticationError:
                send({"type": "error", "message": "Claude didn't accept the key: set ANTHROPIC_API_KEY (or run "
                                                  "`ant auth login`) and start ptg maker again."})
            except anthropic.PermissionDeniedError:
                send({"type": "error", "message": f"That key can't use {MODELS[params['model']]}."})
            except anthropic.NotFoundError:
                send({"type": "error", "message": f"Claude doesn't know the model {params['model']}."})
            except anthropic.RateLimitError:
                send({"type": "error", "message": "Too many requests just now: wait a minute and ask again."})
            except anthropic.BadRequestError as error:
                send({"type": "error", "message": f"Claude couldn't take that: {error.message}"})
            except anthropic.APIStatusError as error:
                send({"type": "error", "message": f"Claude had a problem ({error.status_code}): try again."})
            except anthropic.APIConnectionError:
                send({"type": "error", "message": "Couldn't reach Claude: is this computer online?"})
        except (BrokenPipeError, ConnectionResetError):
            pass  # the page stopped listening (Stop, or a reload)


def _logged(send, model: str):
    """send, plus a line in the terminal for each turn: what it cost in tokens."""
    def logged(event: dict) -> None:
        if event["type"] == "message":
            u = event["usage"]
            print(f"Claude ({MODELS.get(event.get('model'), model)}): {u['input_tokens']} in "
                  f"(+{u['cache_read_input_tokens']} cached, {u['cache_creation_input_tokens']} cache written), "
                  f"{u['output_tokens']} out, {event['stop_reason']}", flush=True)
        send(event)
    return logged


def make_server(port: int, folder: Path, studio: Studio) -> ThreadingHTTPServer:
    handler = type("MakerHandler", (Handler,), {"studio": studio})
    server = ThreadingHTTPServer(("127.0.0.1", port), partial(handler, directory=str(folder)))
    server.daemon_threads = True
    return server


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="ptg maker", description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"the port to listen on (default {DEFAULT_PORT})")
    parser.add_argument("--no-browser", action="store_true", help="don't open a browser")
    args = parser.parse_args(argv)
    folder = library.maker_folder()
    if folder is None or not (folder / "index.html").is_file():
        print("ptg maker serves docs/maker, so it runs from a checkout of the game's repository.")
        return 1
    studio = Studio()
    try:
        server = make_server(args.port, folder, studio)
    except OSError as error:
        print(f"Couldn't listen on port {args.port} ({error.strerror}): try --port with another number.")
        return 1
    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"The Monster & Item Maker is at {url}" + ("" if not studio.problem else f"\n{studio.problem}."))
    print("Ctrl+C stops it.", flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
