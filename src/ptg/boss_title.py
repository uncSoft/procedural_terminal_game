"""A boss's name called out big as it comes in (ui/boss_intro.py), the way games call out a boss as the fight begins:
its name in big pixel letters over its head, gold, with a dark edge and a shadow, burning in from the left with a
white-hot edge, a glint running along it now and then; and over that, smaller, a line saying what it is (its
MonsterDef.epithet). The letters are drawn once (letter) and then into each frame of the fight's picture
(encounter.Fight.titled), which plays on round them.

The font is 5 pixels by 7, as big as the space over the boss's head and the screen's width allow (3, 2 or 1 screen
pixels a font pixel), on one line or two; "The" before a name a size smaller, sitting on the same line."""

from __future__ import annotations

from dataclasses import dataclass

from .sprites import Image

try:
    from PIL import ImageChops, ImageDraw, ImageFilter
except ImportError:  # (the art is optional: no Pillow, no pictures)
    ImageChops = ImageDraw = ImageFilter = None

CUE = "boss_title"  # its sound as the name starts to burn in (sound.MOMENTS)
TOP, BOTTOM = (255, 246, 204), (228, 122, 34)  # the letters' gold, from the top of a line to its foot
EDGE = (30, 12, 12)
HOT = (255, 252, 238)  # the edge burning in, and the glint
SCALES = (3, 2, 1)
ARTICLES = ("THE", "A", "AN")
# Each glyph 7 rows, "#" lit, as wide as its rows (most 5).
FONT = {
    "A": (".###.", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"),
    "B": ("####.", "#...#", "#...#", "####.", "#...#", "#...#", "####."),
    "C": (".###.", "#...#", "#....", "#....", "#....", "#...#", ".###."),
    "D": ("####.", "#...#", "#...#", "#...#", "#...#", "#...#", "####."),
    "E": ("#####", "#....", "#....", "####.", "#....", "#....", "#####"),
    "F": ("#####", "#....", "#....", "####.", "#....", "#....", "#...."),
    "G": (".###.", "#...#", "#....", "#.###", "#...#", "#...#", ".####"),
    "H": ("#...#", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"),
    "I": ("###", ".#.", ".#.", ".#.", ".#.", ".#.", "###"),
    "J": ("..###", "...#.", "...#.", "...#.", "...#.", "#..#.", ".##.."),
    "K": ("#...#", "#..#.", "#.#..", "##...", "#.#..", "#..#.", "#...#"),
    "L": ("#....", "#....", "#....", "#....", "#....", "#....", "#####"),
    "M": ("#...#", "##.##", "#.#.#", "#.#.#", "#...#", "#...#", "#...#"),
    "N": ("#...#", "#...#", "##..#", "#.#.#", "#..##", "#...#", "#...#"),
    "O": (".###.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."),
    "P": ("####.", "#...#", "#...#", "####.", "#....", "#....", "#...."),
    "Q": (".###.", "#...#", "#...#", "#...#", "#.#.#", "#..#.", ".##.#"),
    "R": ("####.", "#...#", "#...#", "####.", "#.#..", "#..#.", "#...#"),
    "S": (".####", "#....", "#....", ".###.", "....#", "....#", "####."),
    "T": ("#####", "..#..", "..#..", "..#..", "..#..", "..#..", "..#.."),
    "U": ("#...#", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."),
    "V": ("#...#", "#...#", "#...#", "#...#", "#...#", ".#.#.", "..#.."),
    "W": ("#...#", "#...#", "#...#", "#.#.#", "#.#.#", "#.#.#", ".#.#."),
    "X": ("#...#", "#...#", ".#.#.", "..#..", ".#.#.", "#...#", "#...#"),
    "Y": ("#...#", "#...#", ".#.#.", "..#..", "..#..", "..#..", "..#.."),
    "Z": ("#####", "....#", "...#.", "..#..", ".#...", "#....", "#####"),
    "0": (".###.", "#...#", "#..##", "#.#.#", "##..#", "#...#", ".###."),
    "1": ("..#..", ".##..", "..#..", "..#..", "..#..", "..#..", ".###."),
    "2": (".###.", "#...#", "....#", "...#.", "..#..", ".#...", "#####"),
    "3": ("####.", "....#", "....#", ".###.", "....#", "....#", "####."),
    "4": ("...#.", "..##.", ".#.#.", "#..#.", "#####", "...#.", "...#."),
    "5": ("#####", "#....", "####.", "....#", "....#", "#...#", ".###."),
    "6": ("..##.", ".#...", "#....", "####.", "#...#", "#...#", ".###."),
    "7": ("#####", "....#", "...#.", "..#..", ".#...", ".#...", ".#..."),
    "8": (".###.", "#...#", "#...#", ".###.", "#...#", "#...#", ".###."),
    "9": (".###.", "#...#", "#...#", ".####", "....#", "...#.", ".##.."),
    "'": ("#", "#", ".", ".", ".", ".", "."),
    "-": ("...", "...", "...", "###", "...", "...", "..."),
    ".": (".", ".", ".", ".", ".", ".", "#"),
    ",": ("..", "..", "..", "..", "..", ".#", "#."),
    "!": ("#", "#", "#", "#", "#", ".", "#"),
    "?": (".###.", "#...#", "....#", "...#.", "..#..", ".....", "..#.."),
    " ": ("...", "...", "...", "...", "...", "...", "..."),
}
ROWS = 7


def _glyph(ch: str) -> tuple[str, ...]:
    return FONT.get(ch, FONT[" "])


def _word_width(word: str, scale: int) -> int:
    return sum(len(_glyph(ch)[0]) * scale for ch in word) + scale * max(0, len(word) - 1)


def _line_width(line: list[tuple[str, int]]) -> int:
    return sum(_word_width(word, s) for word, s in line) + sum(3 * s for _, s in line[1:])


def _line_height(line: list[tuple[str, int]]) -> int:
    return ROWS * max(s for _, s in line)


def _height(lines: list[list[tuple[str, int]]], scale: int) -> int:
    """Its lines' heights, a gap between them, and a pixel round them for the edge (two under, for the shadow)."""
    return sum(map(_line_height, lines)) + (len(lines) - 1) * 2 * scale + 3


@dataclass
class Lettering:
    """A name laid out in big letters (letter): its picture (gold, its edge and its shadow) and the letters' own
    pixels (`mask`), drawn once; `scale` screen pixels a font pixel."""

    image: object
    mask: object
    scale: int

    @property
    def width(self) -> int:
        return self.image.width

    @property
    def height(self) -> int:
        return self.image.height

    def draw(self, canvas, left: int, top: int, reveal: float = 1.0, glint: float | None = None) -> None:
        """Into `canvas` with its top left at (left, top), all of it on the canvas: only `reveal` of it (0 to 1) from the left, its edge white
        hot as it burns in; and a glint, a slanting stripe of light, over the letters at `glint` pixels along."""
        shown = round(self.width * max(0.0, min(1.0, reveal)))
        if shown <= 0:
            return
        canvas.alpha_composite(self.image.crop((0, 0, shown, self.height)), (left, top))
        hot = Image.new("RGBA", (self.width, self.height), (*HOT, 255))
        if shown < self.width:  # (the edge burning in)
            band = Image.new("L", (self.width, self.height), 0)
            ImageDraw.Draw(band).rectangle((max(0, shown - 2 * self.scale), 0, shown - 1, self.height), fill=255)
            canvas.paste(hot, (left, top), ImageChops.multiply(band, self.mask))
        elif glint is not None:
            band = Image.new("L", (self.width, self.height), 0)
            slant, wide = self.height // 2, 2 * self.scale + 1
            x = round(glint)
            ImageDraw.Draw(band).polygon([(x, 0), (x + wide, 0), (x + wide - slant, self.height),
                                          (x - slant, self.height)], fill=210)
            canvas.paste(hot, (left, top), ImageChops.multiply(band, self.mask))


def layouts(name: str, scale: int) -> list[list[list[tuple[str, int]]]]:
    """The ways `name` can be laid out at `scale`: on one line, then on two broken at each space (the most even
    first). A leading "The" is a size smaller: before the name, or over it on a line of its own."""
    words = name.upper().split()
    if not words:
        return []
    small = max(1, scale - 1)
    sized = [(w, small if i == 0 and w in ARTICLES and len(words) > 1 else scale) for i, w in enumerate(words)]
    out = [[sized]]
    splits = [[sized[:i], sized[i:]] for i in range(1, len(sized))]
    out += sorted(splits, key=lambda two: abs(_line_width(two[0]) - _line_width(two[1])))
    return out


def letter(name: str, width: int, room: int) -> Lettering | None:
    """`name` in big letters, as big as fits `width` pixels across and `room` down (its edge and shadow in it): on one
    line as big as it fits, else on two at twice (never three times: two lines of those would take half the screen),
    else small; None if it doesn't fit even small, or there's no Pillow."""
    if Image is None or ImageDraw is None:
        return None
    for scale, two in [(s, False) for s in SCALES if s > 1] + [(2, True), (1, False), (1, True)]:
        for lines in layouts(name, scale)[1:] if two else layouts(name, scale)[:1]:
            wide, tall = max(_line_width(line) for line in lines) + 3, _height(lines, scale)
            if wide <= width and tall <= room:
                return _drawn(lines, scale, wide, tall)
    return None


def _drawn(lines: list[list[tuple[str, int]]], scale: int, wide: int, tall: int) -> Lettering:
    """The letters drawn: lit pixels in `mask`, each line gold from its top to its foot, a dark edge a pixel round
    them and a shadow under and to the right."""
    mask = Image.new("L", (wide, tall), 0)
    fill = Image.new("RGBA", (wide, tall), (0, 0, 0, 0))
    lit, colours = mask.load(), fill.load()
    widest, foot = max(_line_width(line) for line in lines), 1 - 2 * scale
    for line in lines:
        foot += 2 * scale + _line_height(line)  # (the row under the line's tallest letters)
        x = 1 + (widest - _line_width(line)) // 2
        for word, s in line:
            for ch in word:
                glyph = _glyph(ch)
                for row, bits in enumerate(glyph):
                    for col, bit in enumerate(bits):
                        if bit != "#":
                            continue
                        for dy in range(s):
                            y = foot - (ROWS - row) * s + dy
                            k = (y - (foot - ROWS * s)) / max(1, ROWS * s - 1)
                            colour = tuple(round(a + (b - a) * k) for a, b in zip(TOP, BOTTOM))
                            for dx in range(s):
                                lit[x + col * s + dx, y] = 255
                                colours[x + col * s + dx, y] = (*colour, 255)
                x += len(glyph[0]) * s + s
            x += 2 * s  # (a space: three with the letter gap)
    edge = mask.filter(ImageFilter.MaxFilter(3))
    image = Image.new("RGBA", (wide, tall), (0, 0, 0, 0))
    image.paste(Image.new("RGBA", (wide - 1, tall - 1), (0, 0, 0, 170)), (1, 1), edge.crop((0, 0, wide - 1, tall - 1)))
    image.paste(Image.new("RGBA", (wide, tall), (*EDGE, 255)), (0, 0), edge)
    image.alpha_composite(fill)
    return Lettering(image, mask, scale)


def shade(canvas, bottom: int) -> None:
    """The top of the picture darkened down to `bottom`, most at the top, so the name over it reads."""
    if Image is None or bottom <= 0:
        return
    bottom = min(bottom, canvas.height)
    ramp = Image.new("L", (1, bottom))
    ramp.putdata([round(190 * (1 - (y / bottom) ** 2)) for y in range(bottom)])
    dark = Image.new("RGBA", (canvas.width, bottom), (6, 4, 14, 255))
    dark.putalpha(ramp.resize((canvas.width, bottom)))
    canvas.alpha_composite(dark, (0, 0))
