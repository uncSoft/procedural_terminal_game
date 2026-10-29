"""Spike: Blender's raw renders made into sprite frames, standing in for 3D Sprite Studio's palette and outline.

The renders are unlit, in the sprite's own colours. They're shaded the way the goblin's artist shaded it, a darker
green or brown down the right-hand edge, and the game's dark outline goes round, one pixel, as the sprites are drawn.
Any colour that isn't the sprite's own is snapped to the nearest that is.

    uv run python spikes/goblin3d/pixelate.py      # frames_raw/<clip>/<direction>/*.png -> frames/...
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

HERE = Path(__file__).parent
SPRITE = HERE.parents[1] / "src" / "ptg" / "data" / "sprites" / "goblin.png"
OUTLINE = (24, 20, 37)
SHADE = {(99, 199, 77): (62, 137, 72), (184, 111, 80): (116, 63, 57)}  # green and brown, and their darker shades


def palette() -> list[tuple]:
    sheet = Image.open(SPRITE).convert("RGBA")
    return sorted({p[:3] for p in sheet.get_flattened_data() if p[3] >= 128})


def nearest(rgb: tuple, colours: list[tuple]) -> tuple:
    """The closest colour by eye ("redmean": red and blue weighted by how red the pair is)."""
    def distance(c):
        r = (rgb[0] + c[0]) / 2
        dr, dg, db = rgb[0] - c[0], rgb[1] - c[1], rgb[2] - c[2]
        return (2 + r / 256) * dr * dr + 4 * dg * dg + (2 + (255 - r) / 256) * db * db
    return min(colours, key=distance)


def pixelate(img: Image.Image, colours: list[tuple]) -> Image.Image:
    img = img.convert("RGBA")
    w, h = img.size
    src = img.load()
    out = Image.new("RGBA", (w, h))
    dst = out.load()
    solid = {(x, y) for y in range(h) for x in range(w) if src[x, y][3] >= 128}
    for x, y in solid:
        rgb = nearest(src[x, y][:3], colours)
        if (x + 1, y) not in solid:
            rgb = SHADE.get(rgb, rgb)
        dst[x, y] = (*rgb, 255)
    for y in range(h):
        for x in range(w):
            if (x, y) not in solid and any((x + dx, y + dy) in solid for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                dst[x, y] = (*OUTLINE, 255)
    return out


def main() -> None:
    colours = palette()
    raw, done = HERE / "frames_raw", HERE / "frames"
    count = 0
    for path in sorted(raw.rglob("*.png")):
        target = done / path.relative_to(raw)
        target.parent.mkdir(parents=True, exist_ok=True)
        pixelate(Image.open(path), colours).save(target)
        count += 1
    print(f"{count} frames in {len(colours)} colours -> {done}")


if __name__ == "__main__":
    main()
