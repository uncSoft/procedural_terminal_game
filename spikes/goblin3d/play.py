"""Spike: a 3D model played in the terminal as flat sprite frames, drawn the game's half-block way.

Point it at frames laid out as <clip>/<direction>/<frame>.png (what pixelate.py writes; 3D Sprite Studio's
"individual frames" export, sorted into folders the same way) or at one sprite sheet with a row per direction.
Turning through the directions while a clip plays makes the flat frames read as a model.

    uv run python spikes/goblin3d/play.py                        # the stand-in goblin, spikes/goblin3d/frames
    uv run python spikes/goblin3d/play.py --spin                 # a turntable: it turns as it goes
    uv run python spikes/goblin3d/play.py walk.png --frame 32    # a sheet of 32 px frames, a row per direction
    uv run python spikes/goblin3d/play.py --still                # every direction side by side, printed once
    uv run python spikes/goblin3d/play.py spikes/goblin3d/king/frames_64 --fps 24 --start entrance --once entrance
                                                                 # the King arrives, then stands ready

Keys: left/right turn it, up/down change clip, space pauses, s spins, +/- speed, z zoom, q quits.
"""

from __future__ import annotations

import argparse
import os
import select
import sys
import termios
import time
import tty
from contextlib import contextmanager
from pathlib import Path

from PIL import Image
from rich.console import Console, Group
from rich.live import Live
from rich.text import Text

from ptg.sprites import image_text, side_by_side

HERE = Path(__file__).parent


def _order(path: Path):
    return (0, int(path.stem)) if path.stem.isdigit() else (1, path.stem)


def _pngs(folder: Path) -> list:
    return [Image.open(p).convert("RGBA") for p in sorted(folder.glob("*.png"), key=_order)]


def load_folder(root: Path) -> dict[str, list[list]]:
    """Clip name -> its directions -> their frames. A clip folder of plain PNGs is one direction; a folder of plain
    PNGs is one clip."""
    clips = {}
    for clip in sorted((p for p in root.iterdir() if p.is_dir()), key=_order):
        turns = [d for d in sorted(clip.iterdir(), key=_order) if d.is_dir()]
        clips[clip.name] = [_pngs(d) for d in turns] if turns else [_pngs(clip)]
    return clips or {root.name: [_pngs(root)]}


def load_sheet(path: Path, frame: str) -> dict[str, list[list]]:
    """A sprite sheet cut into frames (`frame` is "32" or "32x48"): each row a direction, empty cells dropped."""
    w, _, h = frame.partition("x")
    w, h = int(w), int(h or w)
    sheet = Image.open(path).convert("RGBA")
    rows = []
    for top in range(0, sheet.height - h + 1, h):
        cells = [sheet.crop((left, top, left + w, top + h)) for left in range(0, sheet.width - w + 1, w)]
        cells = [c for c in cells if c.getbbox()]
        if cells:
            rows.append(cells)
    return {path.stem: rows}


@contextmanager
def keys():
    """Single keypresses without waiting for Enter; read(timeout) gives "left", "up", "q" and so on, or None."""
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    tty.setcbreak(fd)

    def read(timeout: float) -> str | None:
        if not select.select([fd], [], [], max(timeout, 0))[0]:
            return None
        ch = os.read(fd, 1).decode(errors="ignore")
        if ch != "\x1b":
            return ch
        seq = ""
        while select.select([fd], [], [], 0.01)[0] and len(seq) < 2:
            seq += os.read(fd, 1).decode(errors="ignore")
        return {"[A": "up", "[B": "down", "[C": "right", "[D": "left"}.get(seq, "esc")

    try:
        yield read
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)


class Player:
    def __init__(self, clips: dict, fps: float, zoom: int, spin: bool, start: str = "idle", once: tuple = ()):
        self.clips, self.names = clips, list(clips)
        self.turn = self.frame = 0
        self.idle = next((i for i, name in enumerate(self.names) if name.lower() == "idle"), 0)
        self.clip = next((i for i, name in enumerate(self.names) if name.lower() == start.lower()), self.idle)
        self.once = {name.lower() for name in once}  # clips that play through once and hand over to idle
        self.fps, self.zoom, self.spin, self.paused = fps, zoom, spin, False
        self.ticks = 0

    @property
    def turns(self) -> list:
        return self.clips[self.names[self.clip]]

    def press(self, key: str) -> bool:
        """Acts on a key; False means quit."""
        if key in ("q", "esc"):
            return False
        if key in ("left", "right"):
            self.turn = (self.turn + (1 if key == "right" else -1)) % len(self.turns)
        elif key in ("up", "down"):
            self.clip = (self.clip + (1 if key == "down" else -1)) % len(self.names)
            self.turn %= len(self.turns)
            self.frame = 0
        elif key == " ":
            self.paused = not self.paused
        elif key == "s":
            self.spin = not self.spin
        elif key in ("+", "="):
            self.fps = min(self.fps * 1.5, 60)
        elif key in ("-", "_"):
            self.fps = max(self.fps / 1.5, 1)
        elif key == "z":
            self.zoom = self.zoom % 3 + 1
        return True

    def tick(self):
        frames = self.turns[self.turn]
        if self.frame + 1 == len(frames) and self.names[self.clip].lower() in self.once:
            self.clip, self.frame = self.idle, 0
            self.turn %= len(self.turns)
            return
        self.frame = (self.frame + 1) % len(frames)
        self.ticks += 1
        if self.spin and self.ticks % 2 == 0:  # a direction every other frame
            self.turn = (self.turn + 1) % len(self.turns)

    def view(self) -> Group:
        frames = self.turns[self.turn]
        img = frames[self.frame % len(frames)]
        if self.zoom > 1:
            img = img.resize((img.width * self.zoom, img.height * self.zoom), Image.NEAREST)
        title = Text.assemble(
            (self.names[self.clip], "bold"), "  ", (f"facing {self.turn + 1}/{len(self.turns)}", "cyan"),
            "  ", f"frame {self.frame % len(frames) + 1}/{len(frames)}", "  ", f"{self.fps:.0f} fps",
            ("  spinning" if self.spin else "", "magenta"), ("  paused" if self.paused else "", "yellow"))
        help_line = Text("←/→ turn  ↑/↓ clip  space pause  s spin  +/- speed  z zoom  q quit", style="dim")
        return Group(title, Text(""), image_text(img), Text(""), help_line)


def play(player: Player) -> None:
    console = Console()
    with keys() as read, Live(player.view(), console=console, screen=True, auto_refresh=False) as live:
        due = time.monotonic()
        while True:
            key = read(due - time.monotonic())
            if key is not None:
                if not player.press(key):
                    return
                live.update(player.view(), refresh=True)
                continue
            if not player.paused:
                player.tick()
            live.update(player.view(), refresh=True)
            due = time.monotonic() + 1 / player.fps


def still(clips: dict, zoom: int) -> None:
    """Every clip's first frame from each direction, side by side: a quick look without the keys."""
    console = Console()
    for name, turns in clips.items():
        imgs = [t[0] for t in turns]
        if zoom > 1:
            imgs = [i.resize((i.width * zoom, i.height * zoom), Image.NEAREST) for i in imgs]
        console.print(f"[bold]{name}[/]  {len(turns)} directions, {len(turns[0])} frames")
        console.print(side_by_side([image_text(i) for i in imgs], gap=1))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", nargs="?", default=str(HERE / "frames"), help="a frames folder or a sprite sheet")
    parser.add_argument("--frame", help="cut a sprite sheet into frames this size: 32 or 32x48")
    parser.add_argument("--fps", type=float, default=8)
    parser.add_argument("--zoom", type=int, default=1, help="draw each pixel this many times bigger (1-3)")
    parser.add_argument("--spin", action="store_true", help="turn through the directions as it plays")
    parser.add_argument("--still", action="store_true", help="print every direction once and exit")
    parser.add_argument("--start", default="idle", help="the clip to start on")
    parser.add_argument("--once", action="append", default=[], help="a clip that plays once, then hands over to idle")
    args = parser.parse_args()
    source = Path(args.source)
    if source.is_file():
        if not args.frame:
            parser.error("a sprite sheet needs --frame, the size of one frame")
        clips = load_sheet(source, args.frame)
    else:
        clips = load_folder(source)
    if args.still:
        still(clips, args.zoom)
    else:
        try:
            play(Player(clips, args.fps, args.zoom, args.spin, args.start, tuple(args.once)))
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
