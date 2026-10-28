"""A monster's clip for the stage, from frames made elsewhere. The Blender pipeline in spikes/goblin3d turns a sprite
into a model, animates it and renders it back into pixels (its reduce.py shrinks the frames to sprite sizes in the
sprite's own colours, outlined as the game's sprites are). This takes one of its folders, one direction's frames
numbered in order, and writes the strip the game plays: data/clips/<monster>/<clip>.<size>.png, the frames side by
side, with how many there are, the frames a second they were made for, and (an entrance's) the frame its feet land
on, all kept in the PNG.

    uv run python tools/make_clip.py spikes/goblin3d/king/frames_48/Entrance/0 goblin_king entrance --fps 24
    uv run python tools/make_clip.py spikes/goblin3d/king/frames_48/Idle/0 goblin_king idle --fps 24
    uv run python tools/make_clip.py spikes/goblin3d/king/frames_48/Entrance/0 goblin_king attack --fps 24 \
        --frames 53:73 --land 6                       # the swing at the end of his fall, the pan landing on 6

When a fight with the monster starts, the stage plays its `entrance` (encounter.Fight), with the fight's sting on the
frame its feet land, and stands it in its `idle` for the rest of the fight so it keeps the same look: a clip-made
monster needs both. Its `attack`, if it has one, plays each time it goes for you (in place of the lunge), and its
`windup` is how it stands while a heavy blow is coming. `--frames` cuts a clip from part of a folder's frames (a
range, or several: 45:50,53:73, counted from 0, the end left out, as Python slices them). Each is drawn at the
biggest size whose standing art fits the stage, so make them in a few: 40, 48 and 64 pixels cover a laptop's screen
to a big one. Direction 0 (facing you) is the one the stage shows.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, PngImagePlugin

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from ptg import sprites  # noqa: E402

CLIPS = ROOT / "src" / "ptg" / "data" / "clips"


def frames_in(folder: Path) -> list[Image.Image]:
    """A folder's PNGs in the order they're numbered (0000.png, 0001.png...)."""
    paths = sorted(folder.glob("*.png"), key=lambda p: (not p.stem.isdigit(), int(p.stem) if p.stem.isdigit() else 0,
                                                        p.stem))
    return [Image.open(p).convert("RGBA") for p in paths]


def landing(frames: list[Image.Image]) -> int:
    """The frame an entrance's feet land on: the first, after any with nothing in them, whose art reaches down to where
    its last frame stands (0 if it's standing from the start, or never comes down)."""
    boxes = [frame.getbbox() for frame in frames]
    if not boxes or boxes[-1] is None:
        return 0
    feet = boxes[-1][3]
    return next((i for i, box in enumerate(boxes) if box is not None and box[3] >= feet - 1), 0)


def cut(frames: list, spans: str) -> list:
    """The frames in `spans` ("53:73", "45:50,53:73"), in that order."""
    out = []
    for span in spans.split(","):
        start, _, end = span.strip().partition(":")
        out += frames[int(start or 0):int(end) if end else None]
    return out


def make(folder: Path, monster: str, clip: str, fps: float, out: Path = CLIPS, spans: str = "",
         land: int | None = None) -> Path:
    frames = frames_in(folder)
    if spans:
        frames = cut(frames, spans)
    if not frames:
        raise SystemExit(f"No PNG frames in {folder}{' for ' + spans if spans else ''}")
    size = frames[0].size
    if any(frame.size != size for frame in frames):
        raise SystemExit(f"The frames in {folder} aren't all one size")
    strip = Image.new("RGBA", (size[0] * len(frames), size[1]), (0, 0, 0, 0))
    for i, frame in enumerate(frames):
        strip.paste(frame, (i * size[0], 0))
    info = PngImagePlugin.PngInfo()
    info.add_text("frames", str(len(frames)))
    info.add_text("fps", f"{fps:g}")
    land = land if land is not None else landing(frames) if clip == "entrance" else 0
    if land:
        info.add_text("land", str(land))
    target = out / monster / f"{clip}.{size[1]}.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    strip.save(target, pnginfo=info, optimize=True)
    sprites.clips.cache_clear()
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("folder", type=Path, help="one direction's frames, numbered in order")
    parser.add_argument("monster", help="the monster's key (monsters.toml)")
    parser.add_argument("clip", help="entrance, idle...")
    parser.add_argument("--fps", type=float, default=sprites.CLIP_FPS, help="the frames a second it was made for")
    parser.add_argument("--frames", default="", help="only these of the folder's frames: 53:73, or 45:50,53:73")
    parser.add_argument("--land", type=int, help="the frame its moment lands on (an entrance's: found by itself)")
    args = parser.parse_args()
    target = make(args.folder, args.monster, args.clip, args.fps, spans=args.frames, land=args.land)
    made = sprites.clips(args.monster)[args.clip]
    clip = next(c for c in made if c.size == Image.open(target).height)
    print(f"Wrote {target.relative_to(ROOT)}: {len(clip.frames)} frames of {clip.size}px at {clip.fps:g} a second"
          + (f", landing on frame {clip.land}" if clip.land else "") + f" ({target.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
