"""Spike: every model we've made in 3D, playing side by side in the terminal, drawn the game's half-block way.

It finds them itself: each folder here with frames_<size> in it (a boss built by a build_<boss>.py and shrunk by
reduce.py), and the voxel goblin the spike started with (frames/). A new boss turns up as soon as its frames are there.

    uv run --no-sync python spikes/goblin3d/gallery.py              # the biggest size that fits the terminal
    uv run --no-sync python spikes/goblin3d/gallery.py --size 40    # a size of your choosing

They put on a show together, in step: they arrive, stand, wind up, strike, stand, and round again. One without a clip
(the Goblin King has no wind-up or attack yet) stands through it. Their feet are lined up along each row.

Keys: up/down make them all play one clip, a goes back to the show, r starts the show again, space pauses, left/right
turn the ones that turn, z changes size, +/- speed, q quits.
"""

from __future__ import annotations

import argparse
import re
import time
import tomllib
from pathlib import Path

from PIL import Image
from rich.console import Console, Group
from rich.live import Live
from rich.text import Text

from play import keys, load_folder
from ptg.sprites import image_text, side_by_side

HERE = Path(__file__).parent
MONSTERS = HERE.parents[1] / "src" / "ptg" / "data" / "monsters.toml"
TICK = 24  # the show's clock: the bosses were rendered at 24 frames a second
GAP = 3  # characters between models
# The show: each step's clip, how many ticks it lasts, and the frame an attack starts on after a wind-up (by frame 4
# a boss's attack has reached its wind-up pose, so it strikes from there).
SHOW = [("Entrance", 72, 0), ("Idle", 48, 0), ("Windup", 30, 0), ("Attack", 16, 4), ("Idle", 48, 0)]
CLIPS = ["Entrance", "Idle", "Windup", "Attack", "Walk"]


class Model:
    def __init__(self, name: str, sources: dict[int, Path], fps: float = TICK, order: int = 999):
        self.name, self.sources, self.fps, self.order = name, sources, fps, order
        self.sizes: dict[int, tuple] = {}

    def at(self, size: int) -> tuple[dict, tuple, int]:
        """Its frames at the size it has nearest `size`: clips (name -> directions -> frames), the box every frame
        fits in (but for the room above it that only its entrance falls through: it drops in from the top of the
        box), and the row under its feet standing."""
        size = min(self.sources, key=lambda s: abs(s - size))
        if size not in self.sizes:
            clips = load_folder(self.sources[size])

            def boxes(names):
                found = [f.getbbox() for name in names for frames in clips[name] for f in frames]
                return [b for b in found if b]
            every = boxes(list(clips))
            standing = boxes([n for n in clips if n.lower() != "entrance"]) or every
            box = (min(b[0] for b in every), min(b[1] for b in standing), max(b[2] for b in every),
                   max(b[3] for b in every))
            stand = self.clip(clips, "Idle")[0][0].getbbox()
            self.sizes[size] = clips, box, stand[3] if stand else box[3]
        return self.sizes[size]

    @staticmethod
    def clip(clips: dict, name: str) -> list:
        """The clip by that name (any case), or Idle when it hasn't one, or its first."""
        by = {k.lower(): v for k, v in clips.items()}
        return by.get(name.lower()) or by.get("idle") or next(iter(clips.values()))

    @staticmethod
    def has(clips: dict, name: str) -> bool:
        return name.lower() in {k.lower() for k in clips}


def discover() -> list[Model]:
    """Every model with frames here, in the order the game lists its monsters; the voxel goblin last."""
    monsters = tomllib.loads(MONSTERS.read_text())["monster"]
    order = list(monsters)
    models = []
    for folder in sorted(p for p in HERE.iterdir() if p.is_dir()):
        sources = {int(p.name.split("_")[1]): p for p in folder.glob("frames_*")
                   if p.is_dir() and p.name.split("_")[1].isdigit()}
        if not sources:
            continue
        mesh = next(folder.glob("*_mesh.json"), None)
        found = mesh and re.search(r'"sprite":"(\w+)"', mesh.read_text()[:400])
        key = found.group(1) if found else folder.name
        name = monsters.get(key, {}).get("name", folder.name.replace("_", " ").title())
        models.append(Model(name, sources, order=order.index(key) if key in order else 999))
    if (HERE / "frames").is_dir():
        models.append(Model("Goblin (voxel)", {32: HERE / "frames"}, fps=8, order=1000))
    return sorted(models, key=lambda m: m.order)


class Gallery:
    def __init__(self, models: list[Model], size: int | None):
        self.models, self.fixed = models, size
        self.sizes = sorted(set.intersection(*(set(m.sources) for m in models if len(m.sources) > 1)) or {48})
        self.size = size or self.sizes[-1]
        self.chosen: str | None = None  # a clip they all play; None for the show
        self.step = self.t = 0
        self.turn = 0
        self.speed, self.paused = 1.0, False
        self.screen: tuple | None = None
        self.rows: list[list[Model]] = []
        self.cache: dict = {}

    # -- laying them out --------------------------------------------------------------------------------------------

    def arrange(self, width: int) -> list[list[Model]]:
        rows, row, used = [], [], 0
        for m in self.models:
            w = self.width(m)
            if row and used + GAP + w > width:
                rows.append(row)
                row, used = [], 0
            used += (GAP if row else 0) + w
            row.append(m)
        return rows + [row] if row else rows

    def width(self, m: Model) -> int:
        _, box, _ = m.at(self.size)
        return box[2] - box[0]

    def reach(self, row: list[Model]) -> tuple[int, int]:
        """How far the row's frames reach above their feet and below, so every model's feet sit on one line."""
        above = max(stand - box[1] for _, box, stand in (m.at(self.size) for m in row))
        below = max(box[3] - stand for _, box, stand in (m.at(self.size) for m in row))
        return above, below

    def height(self) -> int:
        lines = sum(2 + (sum(self.reach(row)) + 1) // 2 for row in self.rows)
        return lines + 2

    def fit(self, console: Console) -> None:
        """Lays them out for the terminal: at the biggest size that fits it, unless a size was asked for."""
        width, height = console.size
        if self.screen == (width, height, self.size):
            return
        if not self.fixed:
            for size in reversed(self.sizes):
                self.size = size
                self.rows = self.arrange(width)
                if self.height() <= height:
                    break
        self.rows = self.arrange(width)
        self.screen, self.cache = (width, height, self.size), {}

    # -- what each one is doing ------------------------------------------------------------------------------------

    def now(self, m: Model) -> tuple[str, Image.Image]:
        """The clip it's playing and its frame, at this point in the show (or in the chosen clip)."""
        clips, _, _ = m.at(self.size)
        name, skip = (self.chosen, 0) if self.chosen else (SHOW[self.step][0], SHOW[self.step][2])
        if not Model.has(clips, name) or not Model.has(clips, "Windup"):
            skip = 0
        if not Model.has(clips, name):
            name = "Idle"
        turns = Model.clip(clips, name)
        frames = turns[self.turn % len(turns)]
        i = skip + int(self.t * m.fps / TICK)
        if name.lower() == "entrance":  # plays once, then it stands
            if i >= len(frames):
                idle = Model.clip(clips, "Idle")
                frames = idle[self.turn % len(idle)]
                return "Idle", frames[(i - len(turns[0])) % len(frames)]
        return name, frames[i % len(frames)]

    def tick(self) -> None:
        self.t += 1
        if not self.chosen and self.t >= SHOW[self.step][1]:
            self.step, self.t = (self.step + 1) % len(SHOW), 0

    def press(self, key: str) -> bool:
        if key in ("q", "esc"):
            return False
        if key in ("up", "down"):
            at = CLIPS.index(self.chosen) if self.chosen in CLIPS else (-1 if key == "down" else 0)
            self.chosen, self.t = CLIPS[(at + (1 if key == "down" else -1)) % len(CLIPS)], 0
        elif key in ("a", "r"):
            self.chosen = None
            if key == "r":
                self.step = self.t = 0
        elif key in ("left", "right"):
            self.turn += 1 if key == "right" else -1
            self.cache = {}
        elif key == " ":
            self.paused = not self.paused
        elif key in ("+", "="):
            self.speed = min(self.speed * 1.5, 3.0)
        elif key in ("-", "_"):
            self.speed = max(self.speed / 1.5, 0.2)
        elif key == "z":
            self.fixed = self.sizes[(self.sizes.index(self.size) + 1) % len(self.sizes)] \
                if self.size in self.sizes else self.sizes[0]
            self.size, self.screen = self.fixed, None
        return True

    # -- drawing ---------------------------------------------------------------------------------------------------

    def picture(self, m: Model, img: Image.Image, reach: tuple[int, int]) -> Text:
        """Its frame cut to its own width and to the row's height, feet on the row's line."""
        key = (m.name, id(img), reach)
        if key not in self.cache:
            _, box, stand = m.at(self.size)
            above, below = reach
            self.cache[key] = image_text(img.crop((box[0], stand - above, box[2], stand + below)))
        return self.cache[key]

    def view(self) -> Group:
        parts = []
        for row in self.rows:
            reach = self.reach(row)
            heads, pictures = Text(no_wrap=True, overflow="crop"), []
            for n, m in enumerate(row):
                clip, img = self.now(m)
                head = Text.assemble((m.name, "bold"), "  ", (clip, "cyan"))
                head.truncate(self.width(m), overflow="ellipsis", pad=True)
                heads.append_text(head)
                if n < len(row) - 1:
                    heads.append(" " * GAP)
                pictures.append(self.picture(m, img, reach))
            parts += [heads, side_by_side(pictures, gap=GAP), Text("")]
        playing = f"all playing {self.chosen}" if self.chosen else f"the show: {SHOW[self.step][0]}"
        parts.append(Text.assemble((playing, "bold"), "  ", f"{self.size} px", "  ",
                                   f"{TICK * self.speed:.0f} fps", ("  paused" if self.paused else "", "yellow")))
        parts.append(Text("↑/↓ one clip for all  a the show  r from the top  ←/→ turn  space pause  z size  "
                          "+/- speed  q quit", style="dim"))
        return Group(*parts)


def run(gallery: Gallery) -> None:
    console = Console()
    gallery.fit(console)
    with keys() as read, Live(gallery.view(), console=console, screen=True, auto_refresh=False) as live:
        due = time.monotonic()
        while True:
            key = read(due - time.monotonic())
            if key is not None:
                if not gallery.press(key):
                    return
            else:
                if not gallery.paused:
                    gallery.tick()
                due = time.monotonic() + 1 / (TICK * gallery.speed)
            gallery.fit(console)
            live.update(gallery.view(), refresh=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--size", type=int, help="the frame size to show (40, 48, 64); the biggest that fits if not")
    args = parser.parse_args()
    models = discover()
    if not models:
        raise SystemExit("no frames found under spikes/goblin3d")
    try:
        run(Gallery(models, args.size))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
