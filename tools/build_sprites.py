"""Builds the pixel-art sprite sheets in src/ptg/data/sprites/ from the hand-drawn maps below.

Each map is drawn with fill colours only; the build adds a dark outline, shades the lower-right edges
and makes an idle "bob" frame, then writes <key>.png as a horizontal strip of frames.

    uv run python tools/build_sprites.py            # rebuild all sprites
    uv run python tools/build_sprites.py --sheet x  # also write an 8x contact sheet to x.png

Any PNG in data/sprites/ can be replaced with your own art (Aseprite, Piskel, an image model...):
frames side by side, square, transparent background. The game scales it to fit.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

OUT = Path(__file__).resolve().parent.parent / "src" / "ptg" / "data" / "sprites"
SIZE = 24

PALETTE = {
    "k": (24, 20, 37), "w": (255, 255, 255), "W": (192, 203, 220), "g": (139, 155, 180), "G": (90, 105, 136),
    "H": (58, 68, 102), "r": (228, 59, 68), "R": (162, 38, 51), "o": (247, 118, 34), "O": (190, 74, 47),
    "y": (254, 231, 97), "Y": (254, 174, 52), "e": (99, 199, 77), "E": (62, 137, 72), "F": (38, 92, 66),
    "c": (44, 232, 245), "b": (0, 153, 219), "B": (18, 78, 137), "p": (181, 80, 136), "P": (104, 56, 108),
    "n": (184, 111, 80), "N": (116, 63, 57), "M": (63, 40, 50), "s": (232, 183, 150), "S": (194, 133, 105),
    "t": (234, 212, 170), "T": (194, 160, 120), "q": (38, 43, 68), "l": (180, 255, 214), "v": (139, 109, 156),
}
SHADE = {"e": "E", "E": "F", "n": "N", "N": "M", "t": "T", "T": "N", "g": "G", "G": "H", "W": "g", "w": "W",
         "r": "R", "R": "M", "o": "O", "O": "R", "y": "Y", "Y": "O", "s": "S", "p": "P", "P": "q", "c": "b",
         "b": "B", "B": "q", "l": "c", "v": "P"}
OUTLINE = PALETTE["k"]

# Mirrored sprites are drawn as the left half (12 columns); the build mirrors them.
SPRITES: dict[str, dict] = {
    "goblin": {"mirror": True, "rows": [
        "............",
        "............",
        "............",
        ".........eee",
        "........eeee",
        ".ee....eeeee",
        "..eee.eeeeee",
        "...eeeeeeeee",
        "....eeeeeeee",
        "....eeyykeee",
        ".....eeeeeee",
        ".....eekkkkk",
        "......ewkwkw",
        ".......eeeee",
        "......nnnnnn",
        ".....nnnnnnn",
        "....ennnNnnn",
        "....e.nnnnnn",
        "....e.nnnnnn",
        "......nnnnnn",
        ".......ee...",
        ".......ee...",
        "......nnn...",
        "............",
    ]},
    "hobgoblin": {"mirror": True, "rows": [
        "............",
        "............",
        "........gggg",
        ".......ggggg",
        "......gggggg",
        "......gWgggg",
        ".o....oooooo",
        ".oo..ooooooo",
        "..oooooyykoo",
        "....oooooooo",
        "....ooookkkk",
        ".....oowkkkw",
        "......oooooo",
        "....GGGGGGGG",
        "...GGgggggGG",
        "...oGgggggGg",
        "...o.ggGgggg",
        "...o.ggggggg",
        "...oo.nnnnnn",
        "......GGG...",
        "......GGG...",
        "......GGG...",
        ".....nnnn...",
        "............",
    ]},
    "orc": {"mirror": True, "rows": [
        "............",
        "............",
        "........EEEE",
        ".......EEEEE",
        "......EEEEEE",
        "......EkkEEE",
        "..EE..ErrEEE",
        ".EEEEEEEEEEE",
        "..EEEEEEEEEE",
        "....EEEEkkkk",
        "....EEEwkkkk",
        ".....EEwEEEE",
        "......EEEEEE",
        "...nnnnnnnnn",
        "..nnnNnnnnnn",
        ".EEnnnnnnggg",
        ".EE.nnnnnggg",
        ".EE.nnnnnnnn",
        ".EE..NNNNNNN",
        "......nnn...",
        "......nnn...",
        "......EEE...",
        ".....kkkk...",
        "............",
    ]},
    "goblin_king": {"mirror": True, "rows": [
        "........y..y",
        ".......yyyyy",
        ".......yryyy",
        "........eeee",
        ".......eeeee",
        "ee....eeeeee",
        ".eee.eeeeeee",
        "..eeeeeeeeee",
        "....eeyykeee",
        ".....eeeeeee",
        ".....eekkkkk",
        "......ewkwkw",
        ".....rreeeee",
        "....rrrryyyy",
        "...rrrnnnnnn",
        "...rr.nnnynn",
        "...rr.nnnnnn",
        "..rre.nnnnnn",
        "..rr..nnnnnn",
        "..rr...ee...",
        ".rrr...ee...",
        ".rr...nnn...",
        "............",
        "............",
    ]},
    "skeleton": {"mirror": True, "rows": [
        "............",
        "............",
        ".........ttt",
        "........tttt",
        ".......ttttt",
        ".......ttttt",
        ".......tkkkt",
        ".......tkrkt",
        ".......ttttt",
        "........tttk",
        "........tktk",
        ".........ttt",
        "...........t",
        ".......ttttt",
        "......t.tttt",
        ".....t..t.tt",
        ".....t..tttt",
        ".....t..t.tt",
        "....t...tttt",
        ".........ttt",
        "........tt..",
        "........t...",
        "........t...",
        ".......tt...",
    ]},
    "ghoul": {"mirror": True, "rows": [
        "............",
        "............",
        "............",
        "........gggg",
        ".......ggggg",
        "......gggggg",
        "......gkgggg",
        "......kyygkg",
        "......gggggg",
        ".......gkkkk",
        ".......kwkwk",
        ".......kkkkk",
        ".....ggggggg",
        "....gggggggg",
        "...ggg.ggggg",
        "..ggg..gGggg",
        "..gg...ggggg",
        ".gg....gggGg",
        ".w.w...ggggg",
        "w.w....nnnnn",
        ".......gg.gg",
        "......gg...g",
        ".....ggg....",
        "............",
    ]},
    "wight": {"mirror": True, "rows": [
        "..........yy",
        "........yyyy",
        ".......yyyyy",
        "........WWWW",
        ".......WWWWW",
        ".......WkkWW",
        ".......WckWW",
        ".......WWWWW",
        "........WkkW",
        ".........WWW",
        ".....PPPPPPP",
        "....PPPPPPPP",
        "...PPPGGGGGG",
        "...PP.GgggGG",
        "..PPP.GGGGGG",
        "..PP..GgggGG",
        "..PP..GGGGGG",
        "..W...PPPPPP",
        ".WW..PPPPPPP",
        ".....PPPPPPP",
        "....PPPPPPPP",
        "....PP.PP.PP",
        "...P..P..P..",
        "............",
    ]},
    "ghost": {"mirror": True, "rows": [
        "............",
        "............",
        "........llll",
        "......llllll",
        ".....lllllll",
        "....llllllll",
        "....lllkklll",
        "....llkkkkll",
        "....llkkkkll",
        "...llllkklll",
        "...lllllllll",
        "...llllllkkk",
        "..lllllllkkk",
        "..llllllllll",
        ".l.lllllllll",
        "l..lllllllll",
        "...lllllllll",
        "...lllllllll",
        "...lllllllll",
        "...lllllllll",
        "...ll.lll.ll",
        "...l...l...l",
        "............",
        "............",
    ]},
    "bog_lurker": {"mirror": True, "rows": [
        "............",
        "............",
        "............",
        "............",
        "............",
        "............",
        ".........bbb",
        ".......bbbbb",
        "......bbbbbb",
        "......bykbbb",
        ".....bbyybbb",
        ".....bbbbbbb",
        "....bbbbbbbb",
        "....bbkkkkkk",
        "....bbkrrrrr",
        "...bbbkwkwkw",
        "...bbbbbbbbb",
        "..bbbbbbbbbb",
        "..bbbbbbbbbb",
        "ccccccbbcccc",
        "cBBBcccccBBc",
        "ccccBBBccccc",
        "............",
        "............",
    ]},
    "vine_horror": {"mirror": True, "rows": [
        "............",
        "..e.........",
        "...e.....rrr",
        "...e....rryy",
        "....e...rryy",
        "....ee..Errr",
        "..e..eEEEEEE",
        "...eEEEEEEEE",
        "....EEyEEEEE",
        "e...EEEEEEEE",
        ".e..EEEEkkkk",
        "..eEEEEEkwkw",
        "...EEEEEEEEE",
        "..EEEEEeEEEE",
        ".EE.EEEEEEEE",
        "EE..EEEEeEEE",
        "E...EEEEEEEE",
        "....EEEeEEEE",
        "...EE.EEE.EE",
        "..EE..EE...E",
        ".EE..EE....E",
        "EE...E.....E",
        "............",
        "............",
    ]},
    "thorn_sprite": {"mirror": True, "rows": [
        "............",
        "............",
        "............",
        "...........p",
        "..........pp",
        "...........e",
        "......e....e",
        ".......e..ee",
        "....e..eeeee",
        ".....eeeeeee",
        "......eeEeee",
        "...eeeEeeeee",
        ".....eeeykee",
        "......eeeeee",
        "....eeeEeeee",
        "......eeekke",
        ".....eeeeeee",
        "...e..eEeeee",
        "......e.eeee",
        ".....e...e.e",
        "........e...",
        "............",
        "............",
        "............",
    ]},
    "thornmother": {"mirror": True, "rows": [
        ".......pp...",
        "......pppp.p",
        ".....ppppppp",
        "...pppppPppp",
        "..ppppPPyyyy",
        "...pppPyyyyy",
        "....pppyykyy",
        "...e.ppyyyyy",
        "..e...EEyykk",
        ".e...EEEEEEE",
        "e...EEEEeEEE",
        "e..EEEEEEEEE",
        ".eEEE.EEEEEE",
        "..EE..EEEeEE",
        "..E..EEEEEEE",
        ".....EEEEEEE",
        "....EEEeEEEE",
        "...EE.EEEEEE",
        "..EE..EE.EEE",
        ".EE..EE...EE",
        "EE..EE....E.",
        "E..EE....E..",
        "..EE........",
        "............",
    ]},
    "drowned_abbot": {"mirror": True, "rows": [
        "...........y",
        ".........yyy",
        "........yyBB",
        ".......yBBBB",
        ".......yBBBy",
        ".......yyyyy",
        "........WWWW",
        ".......WkcWW",
        ".......WWWWW",
        "........WkkW",
        "......BBBBBB",
        ".....BBBBBBy",
        "....BBBBBByy",
        "...BBBBBBByB",
        "...WBBBBBByB",
        "..c.BBBBBByB",
        "..c.BBBBBByB",
        "....BBBBBByB",
        "...BBBBBBByB",
        "...BBBBBBBBB",
        "..BBBBBBBBBB",
        ".cBBcBBBcBBc",
        "..c...c...c.",
        "............",
    ]},
    "cave_crab": {"mirror": True, "rows": [
        "............",
        "............",
        "............",
        "............",
        "............",
        ".rr.........",
        "rrrr........",
        "rr.r.....w..",
        "rrrr.....k..",
        ".rr......r..",
        "..r.....rrrr",
        "...r..rrrrrr",
        "....rrrrrrrr",
        "...rrrrrrrrr",
        "..r.rrrrrrrr",
        ".r..rrrrrrrr",
        "r...r.rrrrrr",
        "...r..r.rr.r",
        "..r..r..r...",
        ".....r..r...",
        "............",
        "............",
        "............",
        "............",
    ]},
    "giant_rat": {"mirror": False, "rows": [
        "........................",
        "........................",
        "........................",
        "........................",
        "........................",
        "........................",
        "........................",
        "........................",
        "........................",
        "......pp................",
        ".....pggg...gggggg......",
        "....ggggggggggggggggg...",
        "..gggkgggggggggggggggg..",
        ".ggggggggggggggggggggg..",
        "pggggggggggggggggggggggn",
        ".gwgggggWWWWWWWggggg..n.",
        "...ggggWWWWWWWWgggg...n.",
        ".....gggg....gggg....n..",
        ".....gg.......gg...nn...",
        ".....pp.......pp........",
        "........................",
        "........................",
        "........................",
        "........................",
    ]},
    "dire_wolf": {"mirror": False, "rows": [
        "........................",
        "........................",
        "........................",
        "........................",
        "...G.G..................",
        "...GGG..................",
        "..GGGGG.................",
        ".GGrGGGG.......GGGGG....",
        "GGGGGGGGGGGGGGGGGGGGGG..",
        "kGGGGGGGGGGGGGGGGGGGGGGG",
        ".wwGGGGGGGGGGGGGGGGGGG.G",
        "..GGGGGGGGGGGGGGGGGGGG..",
        "....GGGGGgggggggGGGGGG..",
        "....GGGG..gggggg..GGGG..",
        "....GG.G.........GG.GG..",
        "....GG.G.........GG.GG..",
        "...GG..GG.......GG..GG..",
        "........................",
        "........................",
        "........................",
        "........................",
        "........................",
        "........................",
        "........................",
    ]},
    "troll": {"mirror": True, "rows": [
        "............",
        ".........ggg",
        ".......ggggg",
        "......gegggg",
        "......gggggg",
        ".....ggykggg",
        ".....gggggGG",
        ".....ggggGGG",
        ".....gggkkkk",
        "......gwgwgw",
        "....gggggggg",
        "...ggggggggg",
        "..gggegggggg",
        ".ggg.ggggggg",
        ".gg..ggggggg",
        ".gg..ggnnnnn",
        ".gg...nnnnnn",
        "ggg...nnnnnn",
        "gg....ggg..g",
        "......ggg...",
        "......ggg...",
        ".....gggg...",
        "............",
        "............",
    ]},
}

FLAMES = [
    [
        "............",
        "............",
        ".........r..",
        "........rr..",
        ".......rrro.",
        ".......rooor",
        "......roooyo",
        "......rooyyy",
        ".....rrooyyy",
        ".....rooyyyy",
    ],
    [
        "............",
        "...........r",
        "..........rr",
        ".........ror",
        "........rroo",
        "........rooy",
        ".......rooyy",
        "......rrooyy",
        ".....rrooyyy",
        ".....rooyyyy",
    ],
    [
        "............",
        "............",
        "............",
        "........r...",
        ".......rrr..",
        "......rrooo.",
        "......roooyy",
        "......rooyyy",
        ".....roooyyy",
        ".....rooyyyy",
    ],
]
LOGS = [
    "....nnnnnnnn",
    "..nnNnnnnnNn",
    ".gggNNnnnnNN",
    "gGgggggNNNNg",
    ".gGGgGGgggGG",
]


def expand(sprite: dict) -> list[str]:
    rows = sprite["rows"]
    width = SIZE // 2 if sprite["mirror"] else SIZE
    assert len(rows) == SIZE, f"{len(rows)} rows"
    for i, row in enumerate(rows):
        assert len(row) == width, f"row {i} is {len(row)} wide: {row!r}"
    return [row + row[::-1] for row in rows] if sprite["mirror"] else list(rows)


def paint(rows: list[str]) -> Image.Image:
    """Fill colours, then shade lower-right edges, then a dark outline round the whole shape."""
    height, width = len(rows), len(rows[0])
    filled = {(x, y) for y, row in enumerate(rows) for x, ch in enumerate(row) if ch != "."}
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    for x, y in filled:
        ch = rows[y][x]
        if ch not in ("k", "w") and ((x + 1, y) not in filled or (x, y + 1) not in filled):
            ch = SHADE.get(ch, ch)
        img.putpixel((x, y), (*PALETTE[ch], 255))
    for y in range(height):
        for x in range(width):
            if (x, y) in filled:
                continue
            if any((x + dx, y + dy) in filled for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                img.putpixel((x, y), (*OUTLINE, 255))
    return img


def bob(img: Image.Image) -> Image.Image:
    """Idle frame: everything above the feet sinks one pixel."""
    out = img.copy()
    feet = img.height - 5
    upper = img.crop((0, 0, img.width, feet))
    out.paste((0, 0, 0, 0), (0, 0, img.width, feet + 1))
    out.alpha_composite(upper, (0, 1))
    out.alpha_composite(img.crop((0, feet, img.width, img.height)), (0, feet))
    return out


def strip(frames: list[Image.Image]) -> Image.Image:
    sheet = Image.new("RGBA", (SIZE * len(frames), SIZE), (0, 0, 0, 0))
    for i, frame in enumerate(frames):
        sheet.paste(frame, (i * SIZE, 0))
    return sheet


def campfire() -> list[Image.Image]:
    frames = []
    for flame in FLAMES:
        rows = ["." * 12] * (SIZE - len(flame) - len(LOGS) - 2) + flame + LOGS + ["." * 12] * 2
        frames.append(paint([row + row[::-1] for row in rows]))
    return frames


def build(sheet_path: Path | None = None) -> list[str]:
    OUT.mkdir(parents=True, exist_ok=True)
    built = []
    sheets = {}
    for key, sprite in SPRITES.items():
        base = paint(expand(sprite))
        sheets[key] = strip([base, bob(base)])
    sheets["campfire"] = strip(campfire())
    for key, sheet in sheets.items():
        sheet.save(OUT / f"{key}.png")
        built.append(key)
    if sheet_path:
        cols = 6
        scale = 8
        cells = list(sheets.items())
        rows = (len(cells) + cols - 1) // cols
        contact = Image.new("RGBA", (cols * SIZE * scale, rows * SIZE * scale), (9, 10, 19, 255))
        for i, (_, sheet) in enumerate(cells):
            frame = sheet.crop((0, 0, SIZE, SIZE)).resize((SIZE * scale, SIZE * scale), Image.NEAREST)
            contact.alpha_composite(frame, ((i % cols) * SIZE * scale, (i // cols) * SIZE * scale))
        contact.save(sheet_path)
    return built


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sheet", type=Path, help="also write an 8x contact sheet of every sprite")
    args = parser.parse_args()
    print("built:", ", ".join(build(args.sheet)))
