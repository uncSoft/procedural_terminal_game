"""The library: every monster and item in the game, as the Monster & Item Maker sees them (docs/maker), and the
way things made there come back into the game.

    uv run ptg export                        # write docs/maker/library.json, the library the maker page shows
    uv run ptg import --saves                # list what's been saved in the maker but isn't in the game yet
    uv run ptg import --saves 3 7            # bring those saves into the game (add --dry-run to only look)
    uv run ptg import --github               # import every open "[maker]" issue on GitHub, then close them
    uv run ptg import --github 12 15         # just those issues (add --dry-run to only look, --keep-open to not close)
    uv run ptg import "<link>"               # a link from the maker, a saved .json file, or a URL serving creations
    uv run ptg import made.json --dry-run    # just say what would change

A creation from the maker is a little JSON document: what it is (a monster or an item), the game's own fields for
it (the page turns a child's answers into balanced numbers using the reference stats exported here), which entry it
edits if any, who drew it, and its pixel art as rows of palette letters. Importing writes the sprite and the entry
(and, for a new monster, ASCII art for the ASCII mode), checks that the whole game still loads before anything is
written, re-signs the data (so Hackerman knows it was you), and refreshes library.json.
"""

from __future__ import annotations

import base64
import json
import re
import shutil
import string
import subprocess
import sys
import tomllib
import zlib
from datetime import date
from pathlib import Path
from statistics import median

from PIL import Image
from PIL.PngImagePlugin import PngInfo

from . import integrity
from .content import ContentError, build_content, load_content
from .models import DUNGEONS
from .sprites import SMALL, count_frames

ALPHABET = string.ascii_lowercase + string.ascii_uppercase + string.digits
MONSTER_FIELDS = {"name": str, "hp": int, "defense": int, "attack": int, "damage": str, "xp": int, "tier": int,
                  "tags": list, "intelligent": bool, "boss": bool, "ghost": bool, "weak": list, "tell": str,
                  "desc": str}
ITEM_FIELDS = {"name": str, "kind": str, "damage": str, "defense": int, "heal": int, "escape": bool, "tier": int,
               "tags": list, "desc": str}
CREDIT = re.compile(r"^# drawn by (.+?)(?: \((\d{4}-\d\d-\d\d)\))?$")
# Endesga 32, the maker's palette (PALETTE in docs/maker/index.html). The game's art keeps to it: every colour off it
# is one more for the effects to snap to and a terminal to cache (see sprites.palette).
ENDESGA = ("#be4a2f", "#d77643", "#ead4aa", "#e4a672", "#b86f50", "#733e39", "#3e2731", "#a22633",
           "#e43b44", "#f77622", "#feae34", "#fee761", "#63c74d", "#3e8948", "#265c42", "#193c3e",
           "#124e89", "#0099db", "#2ce8f5", "#ffffff", "#c0cbdc", "#8b9bb4", "#5a6988", "#3a4466",
           "#262b44", "#181425", "#ff0044", "#68386c", "#b55088", "#f6757a", "#e8b796", "#c28569")


def data_folder() -> Path:
    return integrity.data_folder()


def maker_folder() -> Path | None:
    """docs/maker in a checkout of the game's repository, if this is one."""
    repo = Path(__file__).resolve().parents[2]
    return repo / "docs" / "maker" if (repo / "pyproject.toml").is_file() else None


# --- pixel art ----------------------------------------------------------------------------------------------------

def sprite_file(kind: str, key: str, folder: Path) -> Path:
    return folder / "sprites" / (f"{key}.png" if kind == "monster" else f"item_{key}.png")


def small_file(key: str, folder: Path) -> Path:
    """An item's hand-made small version (see ptg/sprites.py): 12 pixels square, drawn in the maker or by hand."""
    return folder / "sprites" / "small" / f"item_{key}.png"


def read_frames(path: Path) -> list[Image.Image]:
    """A sprite strip's frames at their real size."""
    with Image.open(path) as sheet:
        count = count_frames(sheet, path.parent.name == "small", path.name)
        sheet = sheet.convert("RGBA")
    width = sheet.width // count
    return [sheet.crop((i * width, 0, (i + 1) * width, sheet.height)) for i in range(count)]


def encode_art(frames: list[Image.Image]) -> dict:
    """Frames as rows of palette letters ('.' is see-through), the way the maker stores drawings."""
    palette: list[str] = []
    rows_per_frame = []
    for frame in frames:
        rows = []
        for y in range(frame.height):
            row = ""
            for x in range(frame.width):
                r, g, b, a = frame.getpixel((x, y))
                if a < 128:
                    row += "."
                    continue
                colour = f"#{r:02x}{g:02x}{b:02x}"
                if colour not in palette:
                    if len(palette) == len(ALPHABET):  # more colours than letters: use the nearest one
                        colour = min(palette, key=lambda c: sum((int(c[i:i + 2], 16) - v) ** 2
                                                                for i, v in zip((1, 3, 5), (r, g, b))))
                    else:
                        palette.append(colour)
                row += ALPHABET[palette.index(colour)]
            rows.append(row)
        rows_per_frame.append(rows)
    return {"w": frames[0].width, "h": frames[0].height, "palette": palette, "frames": rows_per_frame}


def off_palette(frames: list[Image.Image]) -> list[str]:
    """The colours a picture uses that aren't in the maker's palette (custom colours picked in the maker)."""
    used = {f"#{r:02x}{g:02x}{b:02x}" for frame in frames for r, g, b, a in frame.get_flattened_data() if a >= 128}
    return sorted(used - set(ENDESGA))


def decode_art(art: dict) -> list[Image.Image]:
    width, height, palette = int(art["w"]), int(art["h"]), list(art["palette"])
    if not (8 <= width <= 64 and 8 <= height <= 64):
        raise ValueError(f"a drawing should be between 8 and 64 pixels across, not {width}x{height}")
    if len(palette) > len(ALPHABET) or not all(re.fullmatch(r"#[0-9a-fA-F]{6}", c) for c in palette):
        raise ValueError("the drawing's colours aren't in #rrggbb form")
    frames = []
    for rows in art["frames"][:4]:
        if len(rows) != height or any(len(row) != width for row in rows):
            raise ValueError("a picture's rows don't match its size")
        frame = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        for y, row in enumerate(rows):
            for x, ch in enumerate(row):
                if ch != ".":
                    value = palette[ALPHABET.index(ch)]
                    frame.putpixel((x, y), (int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16), 255))
        frames.append(frame)
    if not frames or not any(frame.getbbox() for frame in frames):
        raise ValueError("the drawing is empty")
    if len(frames) == 1 or not frames[1].getbbox():  # one picture: let it bob, like the game's own sprites
        frames = [frames[0], bob(frames[0])]
    return frames


def bob(frame: Image.Image) -> Image.Image:
    """An idle frame for a single picture, the way the game's own sprites bob (tools/build_sprites.py, and the maker
    page's "Make it bob"): the feet, its bottom rows, stay planted and everything above sinks one pixel, so nothing
    falls off the bottom."""
    feet = frame.height - max(1, frame.height * 5 // 24)
    out = Image.new("RGBA", frame.size, (0, 0, 0, 0))
    out.alpha_composite(frame.crop((0, 0, frame.width, feet)), (0, 1))
    out.alpha_composite(frame.crop((0, feet, frame.width, frame.height)), (0, feet))
    return out


def _same_picture(path: Path, frames: list[Image.Image]) -> bool:
    return path.is_file() and [f.tobytes() for f in read_frames(path)] == [f.tobytes() for f in frames]


def save_sprite(frames: list[Image.Image], path: Path) -> None:
    sheet = Image.new("RGBA", (frames[0].width * len(frames), frames[0].height), (0, 0, 0, 0))
    for i, frame in enumerate(frames):
        sheet.paste(frame, (i * frame.width, 0))
    info = PngInfo()
    info.add_text("frames", str(len(frames)))
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(path, pnginfo=info)


def ascii_art(frame: Image.Image) -> str:
    """A rough ASCII picture of a sprite for the ASCII art mode: one character per two pixels, brighter is denser."""
    ramp = ".:-=+*#%@"
    lines = []
    for y in range(0, frame.height, 2):
        line = ""
        for x in range(frame.width):
            pixels = [frame.getpixel((x, yy)) for yy in (y, y + 1) if yy < frame.height]
            solid = [p for p in pixels if p[3] >= 128]
            if not solid:
                line += " "
                continue
            light = sum(0.3 * r + 0.59 * g + 0.11 * b for r, g, b, _ in solid) / len(solid)
            line += ramp[min(len(ramp) - 1, int(light / 256 * len(ramp)))]
        lines.append(line.rstrip())
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    indent = min((len(line) - len(line.lstrip()) for line in lines if line.strip()), default=0)
    return "\n".join(line[indent:] for line in lines)


# --- export -------------------------------------------------------------------------------------------------------

def _credits(text: str, section: str) -> dict[str, dict]:
    """Who drew what, from "# drawn by Name (date)" lines just above each entry."""
    found, pending = {}, None
    for line in text.splitlines():
        match = CREDIT.match(line.strip())
        if match:
            pending = {"by": match.group(1), "made": match.group(2) or ""}
        elif line.startswith(f"[{section}."):
            if pending:
                found[line.strip()[len(section) + 2:-1]] = pending
            pending = None
        elif line.strip() and not line.startswith("#"):
            pending = None
    return found


def credits(folder: Path | None = None) -> dict[str, dict[str, dict]]:
    """Who drew which monsters and items: {"monster": {key: {"by": ..., "made": ...}}, "item": {...}}."""
    folder = folder or data_folder()
    return {kind: _credits((folder / f"{kind}s.toml").read_text(encoding="utf-8"), kind)
            for kind in ("monster", "item")}


def lives(key: str, tags: list[str], ghost: bool, themes, tier: int = 1) -> list[str]:
    """The dungeons a monster turns up in: the one it rules as boss, or every one that calls for its tags (never, for
    a ghost or an `npc` such as a shopkeeper; a floor of its own, such as Norfell, only draws tier 3 and up)."""
    return ([t.name for t in themes if t.boss == key] or
            [t.name for t in themes if set(tags) & set(t.monster_tags) and not ghost and "npc" not in tags
             and (not t.floor or tier >= DUNGEONS)])


def reference(monsters: dict, items: dict) -> dict:
    """Typical numbers for each tier, so new things fit the game's balance."""
    pool = [m for m in monsters.values() if not (m.get("boss") or m.get("ghost") or "npc" in m.get("tags", []))]
    monster = {}
    for tier in (1, 2, 3):
        same = [m for m in pool if m["tier"] == tier] or pool
        damage = max({m["damage"] for m in same}, key=[m["damage"] for m in same].count)
        monster[str(tier)] = {f: round(median(m[f] for m in same)) for f in ("hp", "defense", "attack", "xp")}
        monster[str(tier)]["damage"] = damage
    item = {"weapon": {}, "armor": {}, "consumable": {}}
    defaults = {"weapon": ["1d8", "1d10", "2d6"], "armor": [1, 2, 3], "consumable": [8, 16, 24]}
    field = {"weapon": "damage", "armor": "defense", "consumable": "heal"}
    for kind in item:
        for tier in (1, 2, 3):
            values = [i[field[kind]] for i in items.values() if i["kind"] == kind and i.get("tier") == tier
                      and i.get(field[kind])]
            item[kind][str(tier)] = {field[kind]: values[0] if values else defaults[kind][tier - 1]}
    return {"monster": monster, "item": item}


def export_library(folder: Path | None = None) -> dict:
    folder = folder or data_folder()
    content = build_content(lambda name: (folder / name).read_text(encoding="utf-8"))
    monsters_text = (folder / "monsters.toml").read_text(encoding="utf-8")
    items_text = (folder / "items.toml").read_text(encoding="utf-8")
    monsters = tomllib.loads(monsters_text)["monster"]
    items = tomllib.loads(items_text)["item"]
    credits = {"monster": _credits(monsters_text, "monster"), "item": _credits(items_text, "item")}
    themes = list(content.themes.values())

    def entry(kind: str, key: str, fields: dict) -> dict:
        path = sprite_file(kind, key, folder)
        out = {"key": key, "fields": fields, "art": encode_art(read_frames(path)) if path.is_file() else None}
        if kind == "item" and small_file(key, folder).is_file():
            out["small"] = encode_art(read_frames(small_file(key, folder)))
        out.update(credits[kind].get(key, {}))
        if kind == "monster":
            out["lives"] = lives(key, fields.get("tags", []), fields.get("ghost", False), themes, fields.get("tier", 1))
            out["special"] = ("boss" if fields.get("boss") else "ghost" if fields.get("ghost")
                              else "shopkeeper" if "shopkeeper" in fields.get("tags", []) else "")
        return out

    kinds: dict[str, list[str]] = {}
    for theme in themes:
        for tag in theme.monster_tags:
            kinds.setdefault(tag, []).append(theme.name)
    tags = sorted({t for i in items.values() for t in i.get("tags", [])} |
                  {t for words in content.keyword_tags.values() for t in words} |
                  {t for m in monsters.values() for t in m.get("weak", [])})
    return {
        "version": 1,
        "exported": date.today().isoformat(),
        "monsters": [entry("monster", k, v) for k, v in monsters.items()],
        "items": [entry("item", k, v) for k, v in items.items()],
        "reference": reference(monsters, items),
        "kinds": kinds,
        "tags": tags,
    }


def write_library(path: Path | None = None, folder: Path | None = None) -> Path | None:
    target = path or (maker_folder() / "library.json" if maker_folder() else None)
    if target is None:
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(export_library(folder), ensure_ascii=False, separators=(",", ":")) + "\n",
                      encoding="utf-8")
    return target


# --- import -------------------------------------------------------------------------------------------------------

def read_source(source: str) -> list[dict]:
    """Creations from a maker link (or just its code), a .json file the maker saved, or a URL that serves one."""
    if _is_file(source):
        data = json.loads(Path(source).expanduser().read_text(encoding="utf-8"))
    elif re.match(r"https?://", source) and "#c=" not in source:  # an inbox's export, say
        import httpx

        try:
            data = httpx.get(source, timeout=20, follow_redirects=True).raise_for_status().json()
        except (httpx.HTTPError, ValueError) as error:
            raise ValueError(f"couldn't fetch creations from {source}: {error}") from None
    else:
        code = source.strip().split("#", 1)[-1]
        code = code[2:] if code.startswith("c=") else code
        if not re.fullmatch(r"[zj][A-Za-z0-9_-]+=*", code):
            raise ValueError("that doesn't look like a link from the Monster & Item Maker")
        try:
            packed = base64.urlsafe_b64decode(code[1:] + "=" * (-len(code[1:]) % 4))
            data = json.loads((zlib.decompress(packed, -15) if code[0] == "z" else packed).decode("utf-8"))
        except (ValueError, zlib.error) as error:
            raise ValueError(f"that link is damaged (was it cut short?): {error}") from None
    creations = data.get("creations", [data]) if isinstance(data, dict) else data
    if not isinstance(creations, list) or not all(isinstance(c, dict) and c.get("type") in ("monster", "item")
                                                  for c in creations):
        raise ValueError("there's no monster or item in that")
    return creations


def _is_file(source: str) -> bool:
    try:
        return Path(source).expanduser().is_file()
    except (OSError, ValueError):  # a long link isn't a path
        return False


def slug(name: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:24].strip("_") or "creation"
    return key if key[0].isalpha() else f"x_{key}"


def _clean(fields: dict, schema: dict) -> dict:
    out = {}
    for name, kind in schema.items():
        if name not in fields or fields[name] in (None, "", []):
            continue
        value = fields[name]
        if kind is list:
            value = [str(v).strip().lower() for v in value if str(v).strip()]
        elif kind is bool:
            value = bool(value)
        elif kind is int:
            value = int(value)
        else:
            value = str(value).strip()
        if value is False or value == []:
            continue
        out[name] = value
    return out


def _toml_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(json.dumps(v, ensure_ascii=False) for v in value) + "]"
    if isinstance(value, dict):  # an inline table, such as an item's stats
        return "{" + ", ".join(f"{_toml_key(k)} = {_toml_value(v)}" for k, v in value.items()) + "}"
    return json.dumps(value, ensure_ascii=False)


def _toml_key(key: str) -> str:
    return key if re.fullmatch(r"[A-Za-z0-9_-]+", key) else json.dumps(key, ensure_ascii=False)


def _section(kind: str, key: str, fields: dict, by: str, made: str) -> list[str]:
    lines = [f"# drawn by {by} ({made})"] if by else []
    lines.append(f"[{kind}.{key}]")
    lines += [f"{name} = {_toml_value(value)}" for name, value in fields.items()]
    return lines


def replace_section(text: str, kind: str, key: str, new: list[str]) -> str:
    """Put an entry's lines in place of the old ones (with any "# drawn by" line above it), or at the end."""
    lines = text.splitlines()
    header = f"[{kind}.{key}]"
    if header not in (line.strip() for line in lines):
        return text.rstrip("\n") + "\n\n" + "\n".join(new) + "\n"
    start = next(i for i, line in enumerate(lines) if line.strip() == header)
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("[")), len(lines))
    while end > start + 1 and (not lines[end - 1].strip() or lines[end - 1].startswith("#")):
        end -= 1  # comments and blank lines just above the next entry belong to it
    while start > 0 and CREDIT.match(lines[start - 1].strip()):
        start -= 1
    return "\n".join(lines[:start] + new + lines[end:]) + "\n"


def _palette_note(name: str, custom: set[str]) -> str:
    """A note for whoever imports it (never the thank-you to its maker): colours from outside the maker's palette
    show, but each is one more for the game."""
    shown = sorted(custom)
    listed = ", ".join(shown[:6]) + (f" and {len(shown) - 6} more" if len(shown) > 6 else "")
    return (f"Colours: {name}'s picture uses {len(shown)} colour{'s' * (len(shown) != 1)} from outside the maker's "
            f"palette ({listed}): they show, but the nearest palette colours would keep the game's art in step.")


def _replace_art(text: str, key: str, art: str) -> str:
    block = f"=== {key} ===\n{art}\n"
    pattern = re.compile(rf"^=== {re.escape(key)} ===\n.*?(?=^=== |\Z)", re.M | re.S)
    return pattern.sub(lambda _: block, text, count=1) if pattern.search(text) else text.rstrip("\n") + "\n" + block


def apply(creations: list[dict], folder: Path | None = None, dry_run: bool = False) -> list[str]:
    """Bring creations into the game's data. Nothing is written unless all of it still loads."""
    folder = folder or data_folder()
    texts = {name: (folder / name).read_text(encoding="utf-8") for name in ("monsters.toml", "items.toml", "art.txt")}
    sprites: dict[Path, list[Image.Image]] = {}
    stale: list[Path] = []  # small versions drawn for a picture that's being replaced
    messages = []
    for creation in creations:
        kind = creation["type"]
        file = "monsters.toml" if kind == "monster" else "items.toml"
        existing = tomllib.loads(texts[file]).get(kind, {})
        taken = set(tomllib.loads(texts["monsters.toml"]).get("monster", {})) | \
            set(tomllib.loads(texts["items.toml"]).get("item", {}))
        schema = MONSTER_FIELDS if kind == "monster" else ITEM_FIELDS
        fields = _clean(creation.get("fields", {}), schema)
        name = fields.get("name", "")
        if not name:
            raise ValueError(f"a {kind} needs a name")
        base = creation.get("base")
        if base and base in existing:
            key, verb = base, "Updated"
            for special in ("boss", "ghost"):  # what a thing is for stays as it was
                fields.pop(special, None)
                if existing[base].get(special):
                    fields[special] = True
            if kind == "item" and existing[base].get("kind") == "key":
                fields["kind"] = "key"
            # Set in the game's own data, which the maker doesn't know, so they stay as they were: everything the
            # maker doesn't send (an item's powers, stats and where it's found, a monster's tricks), and what a
            # thrown trinket does.
            game_only = [field for field in existing[base] if field not in schema]
            if existing[base].get("kind") == "trinket":
                game_only.append("damage")
            for field in game_only:
                if field not in fields and field in existing[base]:
                    fields[field] = existing[base][field]
            order = {field: n for n, field in enumerate(existing[base])}  # its own order, so only changes show
            fields = dict(sorted(fields.items(), key=lambda pair: order.get(pair[0], len(order))))
        else:
            key, verb, n = slug(name), "Added", 2
            while key in taken:
                key, n = f"{slug(name)}_{n}", n + 1
            fields.pop("boss", None)
            fields.pop("ghost", None)
        by = str(creation.get("by", "")).strip()[:40]
        made = str(creation.get("made") or date.today().isoformat())[:10]
        texts[file] = replace_section(texts[file], kind, key, _section(kind, key, fields, by, made))
        with_small = stale_note = ""
        custom: set[str] = set()  # colours from outside the maker's palette
        if creation.get("art"):
            frames = decode_art(creation["art"])
            custom.update(off_palette(frames))
            picture = sprite_file(kind, key, folder)
            if (kind == "item" and not creation.get("small") and small_file(key, folder).is_file()
                    and not _same_picture(picture, frames)):
                stale.append(small_file(key, folder))
                stale_note = " Its small version was drawn for the old picture, so it's halved until there's a new one."
            sprites[picture] = frames
            if kind == "monster" and not re.search(rf"^=== {re.escape(key)} ===$", texts["art.txt"], re.M):
                texts["art.txt"] = _replace_art(texts["art.txt"], key, ascii_art(frames[0]))
        elif kind == "monster" and verb == "Added":
            raise ValueError(f"{name} needs a drawing")
        if kind == "item" and creation.get("small"):
            small = decode_art(creation["small"])
            if small[0].size != (SMALL, SMALL):
                raise ValueError(f"{name}'s small version should be {SMALL}x{SMALL} pixels, not "
                                 f"{small[0].width}x{small[0].height}")
            sprites[small_file(key, folder)] = small
            with_small = ", with a small version drawn by hand"
            custom.update(off_palette(small))
        where = ""
        if kind == "monster" and "npc" in fields.get("tags", []):
            where = ", who keeps out of fights (tagged npc)"
        elif kind == "monster":
            homes = lives(key, fields.get("tags", []), fields.get("ghost", False), load_content().themes.values(),
                          fields.get("tier", 1))
            where = f", lives in {' and '.join(homes)}" if homes else ", but no dungeon has its kind of creature"
        messages.append(f"{verb} {kind} {name} ({key}){' by ' + by if by else ''}{where}{with_small}.{stale_note}")
        if custom:  # (a message of its own: a thank-you comment only ever quotes the Added/Updated ones)
            messages.append(_palette_note(name, custom))

    def read(name: str) -> str:
        return texts.get(name) if name in texts else (folder / name).read_text(encoding="utf-8")

    try:
        build_content(read)
    except ContentError as error:
        raise ValueError(f"the game wouldn't load with that, so nothing was changed.\n{error}") from None
    if dry_run:
        return messages + ["(dry run: nothing written)"]
    for name, text in texts.items():
        (folder / name).write_text(text, encoding="utf-8")
    for path in stale:
        path.unlink(missing_ok=True)
    for path, frames in sprites.items():
        save_sprite(frames, path)
    integrity.sign(folder)
    if folder == data_folder() and (target := write_library()):
        messages.append(f"Refreshed {target}.")
    return messages


# --- submissions on GitHub -------------------------------------------------------------------------------------------

CODE = re.compile(r"(?:#c=|```ptg-creation\s*\n)([zj][A-Za-z0-9_-]{16,})")


def repo_name(explicit: str | None = None) -> str:
    """owner/name: as given, from the maker's config.json, or from this checkout's git remote."""
    if explicit:
        return explicit
    folder = maker_folder()
    if folder and (folder / "config.json").is_file():
        repo = json.loads((folder / "config.json").read_text(encoding="utf-8")).get("repo")
        if repo:
            return repo
    url = subprocess.run(["git", "remote", "get-url", "origin"], capture_output=True, text=True,
                         cwd=Path(__file__).resolve().parents[2]).stdout.strip()
    match = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$", url)
    if not match:
        raise ValueError("can't tell which GitHub repository to read: pass --repo owner/name")
    return match.group(1)


def github_submissions(repo: str, numbers: list[int] | None = None, run=subprocess.run) -> list[dict]:
    """Open issues made by the maker's "Submit on GitHub": [{number, title, author, codes}]."""
    if shutil.which("gh") or run is not subprocess.run:
        result = run(["gh", "issue", "list", "--repo", repo, "--state", "open", "--limit", "100",
                      "--search", "[maker] in:title", "--json", "number,title,body,author"],
                     capture_output=True, text=True)
        if result.returncode != 0:
            raise ValueError(f"gh couldn't list issues: {result.stderr.strip() or result.stdout.strip()}")
        issues = [{**i, "author": (i.get("author") or {}).get("login", "")} for i in json.loads(result.stdout or "[]")]
    else:  # no GitHub CLI: a public repository can still be read
        import httpx

        response = httpx.get(f"https://api.github.com/repos/{repo}/issues", params={"state": "open", "per_page": 100},
                             timeout=20)
        issues = [{"number": i["number"], "title": i["title"], "body": i.get("body") or "",
                   "author": (i.get("user") or {}).get("login", "")}
                  for i in response.raise_for_status().json() if "pull_request" not in i]
    found = []
    for issue in sorted(issues, key=lambda i: i["number"]):
        if not issue["title"].startswith("[maker]") or (numbers and issue["number"] not in numbers):
            continue
        found.append({**issue, "codes": list(dict.fromkeys(CODE.findall(issue.get("body") or "")))})
    return found


def import_github(repo: str, numbers: list[int] | None = None, dry_run: bool = False, close: bool = True,
                  folder: Path | None = None, run=subprocess.run) -> list[str]:
    """Import open maker issues one at a time (one bad submission doesn't stop the rest), then thank and close."""
    lines = []
    submissions = github_submissions(repo, numbers, run)
    if not submissions:
        return [f"No open [maker] issues on {repo}."]
    for issue in submissions:
        head = f"#{issue['number']} {issue['title'].removeprefix('[maker]').strip()} (from {issue['author'] or 'someone'})"
        if not issue["codes"]:
            lines.append(f"{head}: no maker data in it, skipped.")
            continue
        try:
            creations = [c for code in issue["codes"] for c in read_source(code)]
            for creation in creations:
                creation["by"] = creation.get("by") or issue["author"]
            messages = apply(creations, folder, dry_run)
        except (ValueError, KeyError, json.JSONDecodeError, zlib.error) as error:
            lines.append(f"{head}: couldn't import it: {error}")
            continue
        lines += [f"{head}: {m}" for m in messages if not m.startswith("(dry run")]
        if dry_run or not close:
            continue
        thanks = "Imported into the game, thank you!\n\n" + "\n".join(f"- {m}" for m in messages
                                                                       if m.startswith(("Added", "Updated")))
        run(["gh", "issue", "close", str(issue["number"]), "--repo", repo, "--comment", thanks],
            capture_output=True, text=True)
    if dry_run:
        lines.append("(dry run: nothing written, nothing closed)")
    return lines


# --- the maker's shared library ------------------------------------------------------------------------------------

def saves_url(explicit: str | None = None) -> str:
    """Where the maker's Save button puts things: as given, or docs/maker/config.json's saves.url."""
    if explicit:
        return explicit
    folder = maker_folder()
    if folder and (folder / "config.json").is_file():
        saves = json.loads((folder / "config.json").read_text(encoding="utf-8")).get("saves") or {}
        if saves.get("url"):
            return saves["url"]
    raise ValueError("there's no shared library to read: set one up (tools/maker_saves.gs) and put its URL in "
                     "docs/maker/config.json as saves.url, or pass --url")


def saved_creations(url: str, get=None) -> list[dict]:
    """Everything saved in the shared library, by number. A library that doesn't number them counts oldest first."""
    if get is None:
        import httpx

        def get(address: str):
            try:
                return httpx.get(address, timeout=30, follow_redirects=True).raise_for_status().json()
            except (httpx.HTTPError, ValueError) as error:
                raise ValueError(f"couldn't read the shared library at {address}: {error}") from None
    data = get(url)
    creations = [c for c in (data.get("creations") if isinstance(data, dict) else None) or []
                 if isinstance(c, dict) and c.get("type") in ("monster", "item") and isinstance(c.get("fields"), dict)]
    creations.sort(key=lambda c: str(c.get("saved", "")))
    if not all(type(c.get("no")) is int for c in creations):
        for n, creation in enumerate(creations, 1):
            creation["no"] = n
    return sorted(creations, key=lambda c: c["no"])


def _folded(text) -> str:
    """A name or a maker's handle as it's compared: "King Mouses Vest" is the game's "King Mouse's Vest" (cleaned up
    when it came in), whatever the punctuation and spacing."""
    return re.sub(r"[^a-z0-9]+", "", str(text or "").lower())


def in_the_game(folder: Path | None = None) -> set[tuple[str, str, str]]:
    """(kind, name, who drew it) for everything in the game: a save matching one is in already, as the maker sees it."""
    folder = folder or data_folder()
    drawn = credits(folder)
    return {(kind, _folded(fields.get("name")), _folded(drawn[kind].get(key, {}).get("by")))
            for kind in ("monster", "item")
            for key, fields in tomllib.loads((folder / f"{kind}s.toml").read_text(encoding="utf-8"))
            .get(kind, {}).items()}


def _title(creation: dict) -> str:
    return f"{creation['type'].capitalize()} {creation['fields'].get('name', '?')} by {creation.get('by') or 'someone'}"


def _about(creation: dict) -> str:
    """One line on a save: what it is, who made it and when, and the numbers that matter."""
    f = creation["fields"]
    if creation["type"] == "monster":
        stats = [f"tier {f.get('tier', '?')}", f"{f.get('hp', '?')} HP", str(f.get("damage", "?"))]
    else:
        power = (f.get("damage") or (f"+{f['defense']} defense" if f.get("defense") else "") or
                 ("escape" if f.get("escape") else f"heals {f['heal']}" if f.get("heal") else ""))
        stats = [str(f.get("kind", "item")), f"tier {f.get('tier', 0)}", power]
    if creation.get("base"):
        stats.append(f"a change to {creation['base']}")
    made = f" ({creation['made']})" if creation.get("made") else ""
    return f"{_title(creation)}{made}: " + ", ".join(s for s in stats if s)


def import_saves(url: str, numbers: list[int] | None = None, dry_run: bool = False, folder: Path | None = None,
                 get=None) -> list[str]:
    """List what's been saved in the maker but isn't in the game yet, or bring in the ones picked by number (one at
    a time, so one that doesn't load doesn't stop the rest)."""
    creations = saved_creations(url, get)
    have = in_the_game(folder)
    waiting = [c for c in creations if (c["type"], _folded(c["fields"].get("name")), _folded(c.get("by"))) not in have]
    if not numbers:
        if not creations:
            return ["Nothing's been saved in the maker yet."]
        if not waiting:
            return ["Nothing waiting: everything saved in the maker is in the game already."]
        lines = ["Saved in the maker, not in the game yet:"] + [f"  #{c['no']}  {_about(c)}" for c in waiting]
        if (more := len(creations) - len(waiting)):
            lines.append(f"({more} more {'is' if more == 1 else 'are'} in the game already.)")
        return lines + [f"Bring some in with: uv run ptg import --saves {' '.join(str(c['no']) for c in waiting[:2])}"]
    lines, refreshed = [], ""
    numbered, still_waiting = {c["no"]: c for c in creations}, {c["no"] for c in waiting}
    for number in numbers:
        creation = numbered.get(number)
        if creation is None:
            lines.append(f"#{number}: there's no save with that number.")
            continue
        if number not in still_waiting:
            lines.append(f"#{number} {_title(creation)}: it's in the game already.")
            continue
        try:
            messages = apply([creation], folder, dry_run)
        except (ValueError, KeyError, IndexError, TypeError) as error:
            lines.append(f"#{number} {_title(creation)}: couldn't import it: {error}")
            continue
        lines += [f"#{number}: {m}" for m in messages if m.startswith(("Added", "Updated", "Colours"))]
        refreshed = next((m for m in messages if m.startswith("Refreshed")), refreshed)
    return lines + ([refreshed] if refreshed else []) + (["(dry run: nothing written)"] if dry_run else [])


def main(argv: list[str]) -> int:
    command, rest = (argv[0], argv[1:]) if argv else ("", [])
    if command == "export":
        target = write_library(Path(rest[0]) if rest else None)
        print(f"Wrote the library to {target}." if target else "Not a checkout of the game: pass a path to write to.")
        return 0 if target else 1
    if command == "import" and rest:
        dry_run = "--dry-run" in rest
        try:
            if "--saves" in rest:
                explicit = rest[rest.index("--url") + 1] if "--url" in rest[:-1] else None
                numbers = [int(a.lstrip("#")) for a in rest if a.lstrip("#").isdigit()]
                for line in import_saves(saves_url(explicit), numbers or None, dry_run):
                    print(line)
                return 0
            if "--github" in rest:
                explicit = rest[rest.index("--repo") + 1] if "--repo" in rest else None
                numbers = [int(a.lstrip("#")) for a in rest if a.lstrip("#").isdigit()]
                for line in import_github(repo_name(explicit), numbers or None, dry_run, "--keep-open" not in rest):
                    print(line)
                return 0
            sources = [a for a in rest if not a.startswith("--")]
            for message in apply([c for source in sources for c in read_source(source)], dry_run=dry_run):
                print(message)
        except (ValueError, KeyError, json.JSONDecodeError, zlib.error) as error:
            print(f"Couldn't import that: {error}")
            return 1
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
