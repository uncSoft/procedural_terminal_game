"""Spike: AI Item & Pixel Art Generation Studio.

A lightweight standalone POC to test live procedural item generation,
balancing, and pixel art creation with LLMs (local via LM Studio / Ollama, or Claude).

Run it:
    uv run python spikes/item_spike.py                               # interactive loop (uses ~/.ptg/config.json)
    uv run python spikes/item_spike.py --backend anthropic           # uses Claude (prompts for key & lists models)
    uv run python spikes/item_spike.py --backend anthropic --models  # list models and choose interactively
    uv run python spikes/item_spike.py --models                      # list local models from LM Studio / Ollama
    uv run python spikes/item_spike.py --offline                     # offline procedural generator
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator

from PIL import Image
from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# Import engine utilities and the exact game connector
from ptg.config import Config, load_config, save_config
from ptg.content import ItemDef
from ptg.llm import LLM
from ptg.llm.anthropic_backend import AnthropicLLM
from ptg.llm.base import LLMError
from ptg.llm.openai_compat import OpenAICompatLLM
from ptg.powers import POWERS, SHORT
from ptg.sprites import image_text

# 32-color authentic PTG palette from tools/build_sprites.py
PALETTE: dict[str, tuple[int, int, int]] = {
    "k": (24, 20, 37),    # near-black outline
    "w": (255, 255, 255),  # white highlight
    "W": (192, 203, 220),  # light silver/steel
    "g": (139, 155, 180),  # mid grey
    "G": (90, 105, 136),   # dark slate
    "H": (58, 68, 102),    # deep navy slate
    "r": (228, 59, 68),    # bright crimson
    "R": (162, 38, 51),    # dark blood red
    "o": (247, 118, 34),   # orange flame
    "O": (190, 74, 47),    # rust / burnt orange
    "y": (254, 231, 97),   # bright yellow
    "Y": (254, 174, 52),   # warm gold
    "e": (99, 199, 77),    # bright emerald
    "E": (62, 137, 72),    # forest green
    "F": (38, 92, 66),     # dark moss green
    "c": (44, 232, 245),   # ice cyan / lightning
    "b": (0, 153, 219),    # azure blue
    "B": (18, 78, 137),    # deep royal blue
    "p": (181, 80, 136),   # magenta / arcane
    "P": (104, 56, 108),   # dark purple / shadow
    "n": (184, 111, 80),   # wood brown / leather
    "N": (116, 63, 57),    # dark leather / mahogany
    "M": (63, 40, 50),     # deep maroon
    "s": (232, 183, 150),  # warm peach
    "S": (194, 133, 105),  # shaded peach
    "t": (234, 212, 170),  # ivory / bone / parchment
    "T": (194, 160, 120),  # weathered bone
    "q": (38, 43, 68),     # void obsidian / midnight
    "l": (180, 255, 214),  # pale mint / celestial glow
    "v": (139, 109, 156),  # lilac / mystic
}

SHADE: dict[str, str] = {
    "e": "E", "E": "F", "n": "N", "N": "M", "t": "T", "T": "N", "g": "G", "G": "H",
    "W": "g", "w": "W", "r": "R", "R": "M", "o": "O", "O": "R", "y": "Y", "Y": "O",
    "s": "S", "p": "P", "P": "q", "c": "b", "b": "B", "B": "q", "l": "c", "v": "P",
}
OUTLINE = PALETTE["k"]

ITEM_SYSTEM_PROMPT_24 = """\
You are the Master Artificer Companion inside a retro dungeon crawler.
The player has invoked a wish at the workshop anvil or in a moment of dire need.
Your job is to fabricate a custom item with balanced stats, rich flavor, and a full 24x24 pixel-art sprite.

Output ONLY valid JSON adhering to the requested schema. No conversational filler outside the JSON.

Rules for item generation:
1. `kind`: one of "weapon", "armor", "consumable", "trinket".
2. `tier`: 1 (common floor 1), 2 (floor 2), or 3 (rare floor 3).
3. Numbers by tier:
   - Weapon damage: tier 1 is "1d6" or "1d8"; tier 2 is "1d10" or "2d4"; tier 3 is "2d6" or "1d12".
   - Armor defense: tier 1 is 1; tier 2 is 2; tier 3 is 3.
   - Consumable heal: tier 1 is 6-10; tier 2 is 12-16; tier 3 is 20-30.
4. `powers`: Pick 0 to 2 legal powers from this exact list:
   - luck (rolls +1), seeker (searching +1), careful (lockpicking +2), unseen (dodge/flee +2),
   - cook (rest +4), goblin_bane (+2 dmg vs goblins), prophecy (Fate token at stairs),
   - cursed (-2 max HP per floor), valuable (+30 souls at end), eloquent (+1 talk),
   - reeks (monsters hit -2 dmg), mapper (maps floor), throw (throwable in fight),
   - distract (monster skips turn once), reveal (lights hidden secrets), dazzle (food makes monster flee).
5. `tags`: 2 to 4 keywords describing material and traits (e.g. sharp, holy, fire, shiny, food, heavy, sticky).
6. `dialogue`: A short 1-line in-character comment from the Companion handing this item to the player.

PIXEL ART RULES (Full 24x24 Grid):
At 24x24, you have room for crisp silhouettes, clean edges, and distinct highlights:
- NEGATIVE SPACE: 50% to 70% of the canvas MUST be empty dots ('.'). Leave 1-2 rows of '.' padding at edges.
- LINE WIDTHS: Blades and handles are 2-3 pixels wide. Crossguards are 1-2 rows high. Potions and shields have an interior cavity.
- DRAWING MODES:
  A) `mirror: true` (RECOMMENDED for symmetrical items: swords, potions, shields, rings, helms, axes, chalices):
     Provide exactly 24 strings, each exactly 12 characters long (representing the LEFT half). The engine mirrors it to 24x24.
     CRITICAL MIRROR RULE: The 12th character (index 11) is the center line!
     - Row ending in `....w`: mirrors to `....ww....` (a 2-pixel wide center line).
     - Row ending in `...wW`: mirrors to `...wWWw...` (a 4-pixel wide bar).
     For a standard 2-pixel wide blade or handle, put exactly 1 letter at column 12!
  B) `mirror: false` (for diagonal or asymmetric items like a sweeping katana or gnarled staff):
     Provide exactly 24 strings, each exactly 24 characters long.

THEMATIC PALETTES (Use these harmonized color combinations):
- Steel & Gold (Martial): w (white highlight), W (silver/steel), g (shadow), Y (gold trim), n/N (leather grip)
- Holy / Solar: w (white shine), y/Y (radiant gold), t (ivory), l (celestial mint glow), r (ruby gem)
- Frost & Starlight: w (pure white), c (ice cyan), b/B (azure/deep blue), l (ghostly mint)
- Volcanic / Ember: y (core flame), o/O (orange flame/rust), r/R (crimson/ember), M (blackened crust)
- Toxic / Necrotic: e/l (acid green), E/F (dark moss), P (purple venom), t (bleached bone)
- Void / Arcane: p/v (magenta/lilac runes), P/B (deep violet/navy), q (midnight void)

BLUEPRINTS (Study how parts connect):
- Vertical Sword (mirror: true, 24 rows x 12 cols):
  ["............", "...........w", "..........wW", "..........wW", "..........wW", "..........wW", "..........wW", "..........wW", "..........wW", "..........wW", "..........wW", "..........wW", "..........wW", "......YYYYYY", ".....YYRRR..", "..........nn", "..........nn", "..........nn", "..........nn", ".........YYY", "..........YY", "............", "............", "............"]
- Potion Decanter (mirror: true, 24 rows x 12 cols):
  ["............", ".....tt.....", "....tttt....", "...WWWWWW...", "....WWWW....", "....WggW....", "....WggW....", "...WeeeeW...", "..WeeeeeeW..", ".WeeeeeeeeW.", ".WeeeeeeeeW.", ".WeeeeelleW.", ".WeeeeeeeeW.", ".WeeeeeeeeW.", ".WeeeeelleW.", ".WeeeeeeeeW.", ".WeeeeeeeeW.", "..WeeeeeeW..", "...WeeeeW...", "....WWWW....", "............", "............", "............", "............"]
- Kite Shield (mirror: true, 24 rows x 12 cols):
  ["..YYYYYYYYYY", ".YYYYYYYYYYY", "YYYYYYYYYYYY", "YYBBBBBBBBBB", "YYBBBBBBBBBB", "YYBBBBBBBBBB", "YYBBBBBBBBBB", "YYBBBBBBBBBB", "YYBBBBBBBBBB", "YYBBBBBBBBBB", ".YYBBBBBBBBB", ".YYBBBBBBBBB", "..YYBBBBBBBB", "..YYBBBBBBBB", "...YYBBBBBBB", "...YYBBBBBBB", "....YYBBBBBB", ".....YYBBBBB", "......YYBBBB", ".......YYBBB", "........YYBB", ".........YYB", "..........YY", "...........Y"]
- Food / Pizza Slice (mirror: true, 24 rows x 12 cols):
  ["............", "..NNNNNNNNNN", "..NNNNNNNNNN", "..NyyyyyyyyY", ".Nyyyryyyyyy", ".Nyyyyyyyyyy", ".Nyyyyyyryyy", "NyyyyyyyyyyY", "NyyyoyyyyyyY", ".Nyyyyyyyyyy", "..Nyyyyyyyyy", "...NyyyyyyyY", "....NyyyyyyY", ".....Nyyyyyy", "......Nyyyyy", "......NyyyyY", ".......NyyyY", "........NyyY", "........NNNY", "..........yN", "............", "............", "............", "............"]
"""

ITEM_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "name": {"type": "string"},
        "kind": {"type": "string", "enum": ["weapon", "armor", "consumable", "trinket"]},
        "tier": {"type": "integer", "enum": [1, 2, 3]},
        "damage": {"type": "string"},
        "defense": {"type": "integer"},
        "heal": {"type": "integer"},
        "powers": {"type": "array", "items": {"type": "string"}},
        "tags": {"type": "array", "items": {"type": "string"}},
        "desc": {"type": "string"},
        "dialogue": {"type": "string"},
        "art": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "mirror": {"type": "boolean"},
                "rows": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["mirror", "rows"],
        },
    },
    "required": [
        "name", "kind", "tier", "damage", "defense", "heal",
        "powers", "tags", "desc", "dialogue", "art"
    ],
}


def paint_grid(rows: list[str], target_size: int = 24, mirror: bool = False, add_outline: bool = True) -> Image.Image:
    """Turn character rows into a PIL RGBA image with shading and outlines. Supports 24x24 and 12x12."""
    if not rows:
        return Image.new("RGBA", (target_size, target_size), (0, 0, 0, 0))

    half_size = target_size // 2
    # Auto-detect mirror if rows are around half target size
    is_mirror = mirror or all(len(r.strip()) <= half_size + 1 for r in rows if r.strip())

    if is_mirror:
        cleaned = [r.strip().ljust(half_size, ".")[:half_size] for r in rows]
        while len(cleaned) < target_size:
            cleaned.append("." * half_size)
        padded = [r + r[::-1] for r in cleaned[:target_size]]
    else:
        cleaned = [r.strip().ljust(target_size, ".")[:target_size] for r in rows]
        while len(cleaned) < target_size:
            cleaned.append("." * target_size)
        padded = cleaned[:target_size]

    h, w = len(padded), len(padded[0])
    filled = {(x, y) for y, row in enumerate(padded) for x, ch in enumerate(row) if ch in PALETTE}
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))

    # Fill base and shaded colors
    for x, y in filled:
        ch = padded[y][x]
        if ch not in ("k", "w") and ((x + 1, y) not in filled or (x, y + 1) not in filled):
            ch = SHADE.get(ch, ch)
        img.putpixel((x, y), (*PALETTE[ch], 255))

    # Add dark outlines around edges
    if add_outline:
        for y in range(h):
            for x in range(w):
                if (x, y) in filled:
                    continue
                if any((x + dx, y + dy) in filled for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                    img.putpixel((x, y), (*OUTLINE, 255))

    return img


def make_sparkle_frame(base: Image.Image) -> Image.Image:
    """Frame 1: Adds a crisp retro diamond glint on the topmost highlight pixel."""
    out = base.copy()
    highlights: list[tuple[float, int, int]] = []
    for y in range(base.height):
        for x in range(base.width):
            p = base.getpixel((x, y))
            if p[3] >= 128:
                lum = 0.3 * p[0] + 0.59 * p[1] + 0.11 * p[2]
                if lum > 160:
                    highlights.append((lum, x, y))

    if highlights:
        # Pick the brightest highlight closest to the top
        highlights.sort(key=lambda item: (-item[0], item[2]))
        _, gx, gy = highlights[0]
        # Cross sparkle: white arms with bright cyan core
        sparkle = [
            (gx, gy - 1, (255, 255, 255, 255)),
            (gx, gy + 1, (255, 255, 255, 255)),
            (gx - 1, gy, (255, 255, 255, 255)),
            (gx + 1, gy, (255, 255, 255, 255)),
            (gx, gy, (44, 232, 245, 255)),
        ]
        for sx, sy, col in sparkle:
            if 0 <= sx < base.width and 0 <= sy < base.height:
                out.putpixel((sx, sy), col)
    return out


def render_sprite_text(img: Image.Image) -> Text:
    """Convert PIL RGBA image to Rich half-block text."""
    return image_text(img)


def offline_fallback_item_24(wish: str) -> dict:
    """Deterministic 24x24 fallback for testing when no LLM is connected."""
    return {
        "name": "Sun-Forged Claymore",
        "kind": "weapon",
        "tier": 3,
        "damage": "2d6",
        "defense": 0,
        "heal": 0,
        "powers": ["reveal", "luck"],
        "tags": ["holy", "fire", "heavy", "sharp"],
        "desc": "A two-handed blade forged in dragonfire and quenched in consecrated oil. Its golden runes pulse warmly.",
        "dialogue": "I drew this from the heart of the furnace. It yearns for darkness to cut through.",
        "art": {
            "mirror": True,
            "rows": [
                "............",
                "...........w",
                "..........wW",
                "..........wW",
                "..........wW",
                "..........wW",
                "..........wW",
                "..........wW",
                "..........wW",
                "..........wW",
                "..........wW",
                "..........wW",
                "..........wW",
                "......YYYYYY",
                ".....YYRRR..",
                "..........nn",
                "..........nn",
                "..........nn",
                "..........nn",
                ".........YYY",
                "..........YY",
                "............",
                "............",
                "............",
            ],
        },
    }


def validate_item(data: dict) -> tuple[ItemDef, list[str]]:
    """Validate model output against PTG engine rules and log warnings."""
    warnings = []
    kind = data.get("kind", "trinket")
    if kind not in ("weapon", "armor", "consumable", "key", "trinket"):
        warnings.append(f"Unknown kind '{kind}' clamped to 'trinket'")
        kind = "trinket"

    tier = data.get("tier", 1)
    if tier not in (0, 1, 2, 3):
        tier = 1

    powers = [p for p in data.get("powers", []) if p in POWERS]
    invalid_powers = [p for p in data.get("powers", []) if p not in POWERS]
    if invalid_powers:
        warnings.append(f"Ignored non-canonical powers: {invalid_powers}")

    key = re.sub(r"[^a-z0-9_]+", "_", data.get("name", "custom_item").lower()).strip("_")
    item_def = ItemDef(
        key=key,
        name=data.get("name", "Unnamed Trinket"),
        kind=kind,
        damage=data.get("damage", "") if kind == "weapon" else "",
        defense=int(data.get("defense", 0)) if kind == "armor" else 0,
        heal=int(data.get("heal", 0)) if kind == "consumable" else 0,
        tier=tier,
        tags=data.get("tags", []),
        desc=data.get("desc", ""),
        powers=powers,
    )
    return item_def, warnings


async def generate_item(llm: LLM | None, wish: str, size: int = 24) -> tuple[dict, float]:
    """Call LLM or fallback, returning (result_dict, elapsed_seconds)."""
    t0 = time.perf_counter()
    if llm is None:
        await asyncio.sleep(0.2)
        return offline_fallback_item_24(wish), time.perf_counter() - t0

    user_prompt = f"The adventurer's wish or predicament: \"{wish}\". Fabricate an appropriate item at {size}x{size} pixel resolution."
    res = await llm.complete_json(ITEM_SYSTEM_PROMPT_24, user_prompt, ITEM_SCHEMA, max_tokens=1200)
    elapsed = time.perf_counter() - t0
    return res, elapsed


def display_item_card(console: Console, raw: dict, item: ItemDef, warnings: list[str], elapsed: float, model_name: str, target_size: int = 24):
    """Draw a split terminal card with animated pixel art frames and engine data."""
    art_data = raw.get("art", {})
    rows = art_data.get("rows", [])
    mirror = art_data.get("mirror", False)
    f0 = paint_grid(rows, target_size=target_size, mirror=mirror, add_outline=True)
    f1 = make_sparkle_frame(f0)

    art_text_0 = render_sprite_text(f0)
    art_text_1 = render_sprite_text(f1)

    # Info side
    info_table = Table.grid(padding=(0, 1))
    info_table.add_column("Key", style="bold cyan", width=12)
    info_table.add_column("Value", style="white")

    kind_badge = f"[bold yellow]{item.kind.upper()}[/] (Tier {item.tier})"
    info_table.add_row("Kind:", kind_badge)

    if item.damage:
        info_table.add_row("Damage:", f"[bold red]{item.damage}[/] + might")
    if item.defense:
        info_table.add_row("Defense:", f"[bold green]+{item.defense}[/] AC")
    if item.heal:
        info_table.add_row("Heals:", f"[bold green]+{item.heal}[/] HP")

    if item.powers:
        powers_str = " · ".join(f"[bold magenta]{p}[/] ({SHORT.get(p, p)})" for p in item.powers)
        info_table.add_row("Powers:", powers_str)
    else:
        info_table.add_row("Powers:", "[dim]None[/dim]")

    if item.tags:
        tags_str = " ".join(f"[dim white]#{t}[/]" for t in item.tags)
        info_table.add_row("Tags:", tags_str)

    info_table.add_row("", "")
    info_table.add_row("Description:", f"[italic white]{item.desc}[/]")
    if raw.get("dialogue"):
        info_table.add_row("Companion:", f"[bold yellow]\"{raw['dialogue']}\"[/]")

    # Engine status
    status_style = "bold green" if not warnings else "bold yellow"
    status_text = "✔ Engine-Ready (100% legal PTG ItemDef)" if not warnings else f"⚠ Adjusted: {'; '.join(warnings)}"
    info_table.add_row("", "")
    info_table.add_row("Engine Check:", f"[{status_style}]{status_text}[/]")
    info_table.add_row("Benchmark:", f"[dim]{model_name} ({target_size}x{target_size}) in {elapsed:.2f}s[/dim]")

    # Dual-frame animation showcase
    frames_table = Table.grid(padding=(0, 2))
    frames_table.add_column("Rest", justify="center")
    frames_table.add_column("Sparkle", justify="center")
    frames_table.add_row(
        Panel(art_text_0, title="[dim]Frame 0: Rest[/dim]", border_style="cyan"),
        Panel(art_text_1, title="[dim]Frame 1: Glint[/dim]", border_style="magenta"),
    )

    content_table = Table.grid(padding=(1, 0))
    content_table.add_column("Content", justify="center")
    content_table.add_row(frames_table)
    content_table.add_row(info_table)

    console.print()
    console.print(Panel(content_table, title=f"[bold white]{item.name}[/]", border_style="gold1", expand=False))
    console.print()


async def list_available_models(backend: str, url: str = "", api_key: str = "") -> list[tuple[str, str]]:
    """Fetch live list of models from backend, returning [(model_id, status_note)]."""
    if backend == "anthropic":
        try:
            import anthropic
            client = anthropic.AsyncAnthropic(api_key=api_key or None)
            models = []
            async for m in client.models.list(limit=25):
                models.append((m.id, "available"))
            await client.close()
            if models:
                return models
        except Exception:
            pass
        # Fallback list of known Anthropic models
        known = [
            ("claude-haiku-5-5", "latest haiku"),
            ("claude-sonnet-5-5", "latest sonnet"),
            ("claude-3-5-haiku-20241022", "fast / 3.5"),
            ("claude-3-5-sonnet-20241022", "smart / 3.5"),
            ("claude-opus-5-5", "deep reasoning"),
        ]
        return known

    if backend == "openai":
        try:
            llm = OpenAICompatLLM(url=url, api_key=api_key)
            catalog = await llm.catalog()
            await llm.client.aclose()
            return [(m, "loaded" if is_loaded else "available") for m, is_loaded in catalog]
        except Exception:
            return []

    return [("offline", "built-in procedural")]


def prompt_choose_model(console: Console, models: list[tuple[str, str]], current: str) -> str:
    """Display interactive numbered table of models and return the chosen model ID."""
    if not models:
        console.print("[dim]No models detected from server.[/dim]\n")
        return current

    table = Table(title="Available Models", border_style="cyan", show_header=True)
    table.add_column("#", style="bold yellow", width=4, justify="right")
    table.add_column("Model ID", style="white")
    table.add_column("State", style="dim cyan")
    table.add_column("Active", style="bold green", justify="center")

    for i, (m_id, status) in enumerate(models, 1):
        is_cur = "✔" if m_id == current else ""
        table.add_row(str(i), m_id, status, is_cur)

    console.print()
    console.print(table)
    console.print("[dim]Press Enter to keep current, or enter number / model name.[/dim]")

    choice = console.input(f"[bold green]Select model [1-{len(models)}]: [/]").strip()
    if not choice:
        return current
    if choice.isdigit() and 1 <= int(choice) <= len(models):
        picked = models[int(choice) - 1][0]
        console.print(f"[bold green]Switched active model to:[/] [bold yellow]{picked}[/]\n")
        return picked
    match = next((m[0] for m in models if m[0].lower() == choice.lower()), None)
    if match:
        console.print(f"[bold green]Switched active model to:[/] [bold yellow]{match}[/]\n")
        return match

    return choice


async def init_backend(cfg: Config, console: Console) -> tuple[LLM | None, str]:
    """Initialize the backend LLM and return (llm_instance, model_description)."""
    if cfg.backend == "anthropic":
        effective_key = cfg.api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not effective_key:
            console.print(Panel(
                "[bold yellow]No Anthropic API key configured.[/]\n"
                "[dim]To use Claude, enter your Anthropic API key below.\n"
                "It will be stored in ~/.ptg/config.json for future runs.[/dim]",
                title="Claude Authentication",
                border_style="yellow"
            ))
            key_input = console.input("[bold green]Enter ANTHROPIC_API_KEY (sk-ant-...): [/]").strip()
            if key_input:
                effective_key = key_input
                cfg.api_key = key_input
                save_config(cfg)
                console.print("[bold green]✔ Stored API key in ~/.ptg/config.json[/]\n")
            else:
                console.print("[dim]No key entered. Switching to offline generator.[/dim]\n")
                cfg.backend = "offline"

    if cfg.backend == "anthropic":
        claude_model = cfg.model or "claude-haiku-5-5"
        llm = AnthropicLLM(model=claude_model, api_key=effective_key, temperature=cfg.temperature)
        try:
            await llm.prepare()
            return llm, f"Claude ({llm.name})"
        except Exception as e:
            console.print(f"[bold red]Claude connection failed ({claude_model}):[/] {e}")
            fallbacks = ["claude-sonnet-5-5", "claude-3-5-haiku-20241022", "claude-3-5-sonnet-20241022"]
            for fb in fallbacks:
                if fb == claude_model:
                    continue
                try:
                    alt = AnthropicLLM(model=fb, api_key=effective_key, temperature=cfg.temperature)
                    await alt.prepare()
                    console.print(f"[bold green]✔ Auto-connected to fallback:[/] [yellow]{fb}[/]\n")
                    return alt, f"Claude ({alt.name})"
                except Exception:
                    continue
            return None, "Offline Procedural Generator"

    if cfg.backend != "offline":
        llm = OpenAICompatLLM(url=cfg.url, model=cfg.model, api_key=cfg.api_key)
        try:
            await llm.prepare()
            return llm, f"{cfg.backend} ({llm.name or cfg.model})"
        except Exception as e:
            console.print(f"[bold red]Could not connect to model:[/] {e}")
            return None, "Offline Procedural Generator"

    return None, "Offline Procedural Generator"


async def main_loop(args: argparse.Namespace):
    console = Console()
    console.clear()

    # Load config or overrides
    cfg = load_config() or Config()
    if args.backend:
        cfg.backend = args.backend
    if args.model:
        cfg.model = args.model
    if args.url:
        cfg.url = args.url
    if args.api_key:
        cfg.api_key = args.api_key
    if args.offline:
        cfg.backend = "offline"

    # Interactive model picker on launch if requested
    if args.models:
        console.print(f"[dim]Fetching available models for {cfg.backend}...[/dim]")
        models = await list_available_models(cfg.backend, url=cfg.url, api_key=cfg.api_key)
        picked = prompt_choose_model(console, models, cfg.model)
        if picked != cfg.model:
            cfg.model = picked
            save_config(cfg)

    llm, model_desc = await init_backend(cfg, console)
    size = args.size

    console.print(Panel.fit(
        f"[bold cyan]PTG AI Item & Pixel Art Studio (Spike)[/] - [bold green]{size}x{size} Mode[/]\n"
        f"[dim]Active Provider:[/] [bold yellow]{model_desc}[/]\n"
        "[dim]Commands: [bold]models[/bold] (switch model), [bold]size[/bold] (switch 12/24), [bold]q[/bold] (quit)[/dim]",
        border_style="cyan"
    ))

    # One-off CLI prompt support
    if args.prompt:
        wish = args.prompt
        console.print(f"\n[bold green]Wish:[/] {wish}")
        try:
            raw, elapsed = await generate_item(llm, wish, size=size)
            item_def, warnings = validate_item(raw)
            display_item_card(console, raw, item_def, warnings, elapsed, model_desc, target_size=size)
        except Exception as err:
            console.print(f"[bold red]Generation error:[/] {err}")
        return

    # Interactive loop
    while True:
        try:
            wish = console.input("[bold green]Wish > [/]").strip()
        except (KeyboardInterrupt, EOFError):
            break

        if not wish:
            continue
        if wish.lower() in ("q", "quit", "exit"):
            break

        # In-app model switcher command
        if wish.lower() in ("models", "model", "/models", "/model"):
            console.print(f"[dim]Fetching available models for {cfg.backend}...[/dim]")
            models = await list_available_models(cfg.backend, url=cfg.url, api_key=cfg.api_key)
            picked = prompt_choose_model(console, models, cfg.model)
            if picked != cfg.model:
                cfg.model = picked
                save_config(cfg)
                if llm:
                    await llm.aclose()
                llm, model_desc = await init_backend(cfg, console)
                console.print(f"[bold green]Now active:[/] {model_desc}\n")
            continue

        # In-app resolution switcher command
        if wish.lower() in ("size", "/size"):
            size = 12 if size == 24 else 24
            console.print(f"[bold green]Switched sprite resolution to:[/] [bold yellow]{size}x{size}[/]\n")
            continue

        with console.status(f"[bold cyan]Companion is fabricating {size}x{size} sprite at the anvil...[/]"):
            try:
                raw, elapsed = await generate_item(llm, wish, size=size)
                item_def, warnings = validate_item(raw)
                display_item_card(console, raw, item_def, warnings, elapsed, model_desc, target_size=size)
            except LLMError as err:
                console.print(f"[bold red]LLM error:[/] {err}")
            except Exception as err:
                console.print(f"[bold red]Error:[/] {err}")

    if llm:
        await llm.aclose()
    console.print("\n[dim]Studio closed.[/dim]")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--prompt", type=str, help="one-off generation prompt")
    parser.add_argument("--backend", type=str, choices=["openai", "anthropic", "offline"], help="backend override")
    parser.add_argument("--model", type=str, help="model override")
    parser.add_argument("--models", "--list-models", action="store_true", dest="models", help="list and pick models on launch")
    parser.add_argument("--url", type=str, help="API URL override")
    parser.add_argument("--api-key", type=str, help="API key override")
    parser.add_argument("--size", type=int, default=24, choices=[12, 24], help="sprite resolution (12 or 24)")
    parser.add_argument("--offline", action="store_true", help="run offline with fallback")
    args = parser.parse_args()

    asyncio.run(main_loop(args))
