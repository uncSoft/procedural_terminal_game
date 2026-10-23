"""Sound: short 8-bit effects for the moments that matter, played without ever holding up the game.

A terminal can only beep, so the game plays its own sound. The good way is a small mixer on a thread of its own,
streaming straight to the speakers through sounddevice (PortAudio): it's quick (about 60 ms), sounds overlap, and
the volume works. If sounddevice can't load, the system's player is used instead (afplay on macOS, pw-play, paplay
or aplay on Linux, winsound on Windows), which is slower to start. With no player, with sound off in Settings, or
with PTG_SOUND=0, the game is simply quiet. A sound can never crash or stall it.

The game plays sounds by moment (MOMENTS below). The built-in ones are synthesized by tools/build_sounds.py into
ptg/data/sounds. To use your own, put WAV files (8- or 16-bit PCM, any rate) in ~/.ptg/sounds:

    great.wav, great_2.wav    replace the sound for a natural 20 (with several, one is picked at random)
    sounds.toml               point moments at any file names, set volumes, and note where sounds came from:

        [great]
        files = ["fanfare.wav"]
        volume = 0.8
        credit = "Jane Doe, opengameart.org"
        license = "CC0"

        [hit]
        volume = 0.5          # no files: just turn a built-in sound down

    uv run python -m ptg.sound              # every moment, where its sound comes from, and any problems
    uv run python -m ptg.sound great coin   # play some
"""

from __future__ import annotations

import os
import random
import re
import shutil
import subprocess
import sys
import threading
import time
import tomllib
import wave
from array import array
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

MOMENTS = {
    "select": "choosing an option",
    "open": "a panel opens",
    "close": "a panel closes",
    "dice_roll": "the big d20 tumbles",
    "dice_small": "an attack's little dice roll",
    "dice_land": "the d20 lands",
    "dice_tick": "a bonus adds up",
    "great": "a natural 20",
    "good": "a roll goes your way",
    "neutral": "a roll that changes nothing much",
    "bad": "a roll goes against you",
    "awful": "a natural 1, or a monster's critical hit",
    "hit": "you hit a monster",
    "crit_hit": "you land a critical hit",
    "miss": "you miss",
    "hurt": "you take damage",
    "dodge": "a monster misses you",
    "windup": "a monster winds up a heavy blow",
    "stun": "a monster is stunned",
    "kill": "a monster falls",
    "step": "you walk into a room",
    "locked": "a locked door",
    "unlock": "you unlock a door",
    "item": "you pick something up",
    "coin": "you find gold",
    "heal": "you heal",
    "secret": "a secret is found",
    "story": "a story card appears",
    "chest": "a chest opens",
    "fountain": "you drink from a fountain",
    "shrine": "you make an offering",
    "descend": "you go down the stairs",
    "fate": "you spend Fate to reroll",
    "level_up": "you level up",
    "death": "you die",
    "victory": "you win",
}

BUILTIN_CREDIT = "made for ptg (tools/build_sounds.py)"
VARIANT = re.compile(r"^(.+?)(?:_(\d+))?$")


@dataclass
class Clip:
    """One sound file for a moment."""

    moment: str
    source: object  # a Path, or the package's own file
    volume: float = 1.0
    credit: str = BUILTIN_CREDIT
    license: str = "CC0"
    builtin: bool = True


def _moment(filename: str) -> str:
    return VARIANT.match(filename.rsplit(".", 1)[0]).group(1)


def user_folder() -> Path:
    from .config import home

    return home() / "sounds"


def load_bank(folder: Path | None = None) -> tuple[dict[str, list[Clip]], list[str]]:
    """Each moment's clips: the built-in ones, replaced moment by moment by any in `folder`. Also returns any
    problems found there, for `python -m ptg.sound` to show."""
    bank: dict[str, list[Clip]] = {}
    for item in sorted(resources.files("ptg").joinpath("data", "sounds").iterdir(), key=lambda i: i.name):
        if item.name.endswith(".wav"):
            bank.setdefault(_moment(item.name), []).append(Clip(_moment(item.name), item))
    problems: list[str] = []
    if folder is None or not folder.is_dir():
        return bank, problems
    spec: dict = {}
    manifest = folder / "sounds.toml"
    if manifest.is_file():
        try:
            spec = tomllib.loads(manifest.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as error:
            problems.append(f"sounds.toml: {error}")
    listed = {name for entry in spec.values() if isinstance(entry, dict)
              for name in entry.get("files") or ([entry["file"]] if entry.get("file") else [])}
    yours: dict[str, list[Clip]] = {}
    for path in sorted(folder.glob("*.wav")):
        if path.name not in listed:  # named after its moment
            yours.setdefault(_moment(path.name), []).append(Clip(_moment(path.name), path, credit="yours",
                                                                 license="", builtin=False))
    if spec:
        for moment, entry in spec.items():
            if not isinstance(entry, dict):
                problems.append(f"sounds.toml: [{moment}] should be a table, like [{moment}] files = [...]")
                continue
            volume = float(entry.get("volume", 1.0))
            names = entry.get("files") or ([entry["file"]] if entry.get("file") else [])
            clips = []
            for name in names:
                if (folder / name).is_file():
                    clips.append(Clip(moment, folder / name, volume, entry.get("credit", "yours"),
                                      entry.get("license", ""), builtin=False))
                else:
                    problems.append(f"sounds.toml: [{moment}] {name} isn't in {folder}")
            if clips:
                yours[moment] = clips
            elif not names:  # just a volume for whatever plays now
                for clip in yours.get(moment) or bank.get(moment, []):
                    clip.volume = volume
    for moment in yours:
        if moment not in MOMENTS:
            problems.append(f"{moment}: the game never plays this moment (python -m ptg.sound lists them)")
    bank.update(yours)
    return bank, problems


def decode(source) -> tuple[array, int]:
    """A WAV file as mono 16-bit samples, and its sample rate."""
    with source.open("rb") as f, wave.open(f) as w:
        channels, width, rate = w.getnchannels(), w.getsampwidth(), w.getframerate()
        frames = w.readframes(w.getnframes())
    if width == 1:
        samples = array("h", ((b - 128) << 8 for b in frames))
    elif width == 2:
        samples = array("h")
        samples.frombytes(frames)
        if sys.byteorder == "big":
            samples.byteswap()
    else:
        raise ValueError(f"{width * 8}-bit audio: save it as an 8- or 16-bit PCM WAV")
    if channels > 1:
        samples = array("h", (sum(samples[i:i + channels]) // channels for i in range(0, len(samples), channels)))
    return samples, rate


def resample(samples: array, rate: int, target: int) -> array:
    """Change the sample rate by holding each sample (no smoothing, so 8-bit sounds keep their crunch)."""
    if rate == target:
        return samples
    step = rate / target
    return array("h", (samples[int(i * step)] for i in range(int(len(samples) / step))))


# --- players ----------------------------------------------------------------------------------------------------

class Mixer:
    """Mixes overlapping sounds on its own thread and streams them to the speakers. The stream sleeps after two
    quiet seconds and wakes for the next sound."""

    name = "sounddevice"
    BLOCK = 512
    VOICES = 8

    def __init__(self, sd) -> None:
        self.rate = int(sd.query_devices(kind="output")["default_samplerate"])
        self.stream = sd.RawOutputStream(samplerate=self.rate, channels=1, dtype="int16", latency="low")
        self.voices: list[list] = []  # [samples, position, gain]
        self.cache: dict[str, array] = {}
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.closed = False
        threading.Thread(target=self._run, name="ptg-sound", daemon=True).start()

    def play(self, clip: Clip, gain: float) -> None:
        key = str(clip.source)
        if key not in self.cache:
            self.cache[key] = resample(*decode(clip.source), self.rate)
        with self.lock:
            if len(self.voices) >= self.VOICES:
                self.voices.pop(0)
            self.voices.append([self.cache[key], 0, gain])
        self.wake.set()

    def _mix(self) -> bytes | None:
        with self.lock:
            if not self.voices:
                return None
            out = [0] * self.BLOCK
            for voice in self.voices:
                samples, position, gain = voice
                for i, value in enumerate(samples[position:position + self.BLOCK]):
                    out[i] += int(value * gain)
                voice[1] = position + self.BLOCK
            self.voices = [v for v in self.voices if v[1] < len(v[0])]
        return array("h", (max(-32768, min(32767, v)) for v in out)).tobytes()

    def _run(self) -> None:
        try:
            self._loop()
        except Exception:  # the device went away: go quiet rather than print over the game
            self.closed = True

    def _loop(self) -> None:
        running, quiet = False, 0.0
        while not self.closed:
            if not running:
                self.wake.wait()
                self.wake.clear()
                if self.closed:
                    break
                self.stream.start()
                running, quiet = True, 0.0
            block = self._mix()
            if block is None:
                quiet += self.BLOCK / self.rate
                if quiet > 2.0:
                    self.stream.stop()
                    running = False
                    continue
                block = bytes(self.BLOCK * 2)
            else:
                quiet = 0.0
            self.stream.write(block)

    def close(self) -> None:
        self.closed = True
        self.wake.set()


class Command:
    """Plays each sound with the system's own player, in the background."""

    def __init__(self, name: str, argv) -> None:
        self.name = name
        self.argv = argv
        self.running: list[subprocess.Popen] = []

    def play(self, clip: Clip, gain: float) -> None:
        self.running = [p for p in self.running if p.poll() is None]
        if len(self.running) < 4:
            self.running.append(subprocess.Popen(self.argv(str(clip.source), gain), stdin=subprocess.DEVNULL,
                                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))

    def close(self) -> None:
        pass


COMMANDS = [
    ("afplay", lambda path, gain: ["afplay", "-v", f"{gain:.2f}", path]),
    ("pw-play", lambda path, gain: ["pw-play", f"--volume={gain:.2f}", path]),
    ("paplay", lambda path, gain: ["paplay", f"--volume={int(gain * 65536)}", path]),
    ("aplay", lambda path, gain: ["aplay", "-q", path]),
]


class Winsound:
    name = "winsound"

    def play(self, clip: Clip, gain: float) -> None:
        import winsound

        winsound.PlaySound(str(clip.source), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)

    def close(self) -> None:
        pass


def open_player():
    """The best way to play sound here, or None."""
    try:
        import sounddevice

        return Mixer(sounddevice)
    except Exception:  # no PortAudio, no output device, ...
        pass
    if sys.platform == "win32":
        return Winsound()
    for name, argv in COMMANDS:
        if shutil.which(name):
            return Command(name, argv)
    return None


# --- the engine ---------------------------------------------------------------------------------------------------

class Sound:
    """The game's sound: on or off, how loud, and which clip plays for each moment."""

    COOLDOWN = 0.05  # the same moment twice this close together plays once

    def __init__(self, enabled: bool = True, volume: float = 0.7, folder: Path | None = None, player=None) -> None:
        self.enabled = enabled and os.environ.get("PTG_SOUND", "1") != "0"
        self.volume = volume
        self.bank, self.problems = load_bank(folder)
        self.player = player
        self.last: dict[str, float] = {}
        self._opening = False

    def start(self) -> None:
        """Open the audio device in the background (it takes a moment), so it's ready for the first sound."""
        if self.enabled and self.player is None and not self._opening:
            self._opening = True
            threading.Thread(target=self._open, name="ptg-sound-open", daemon=True).start()

    def _open(self) -> None:
        self.player = open_player() or Silent()

    def play(self, moment: str) -> bool:
        if not self.enabled or self.volume <= 0 or not self.bank.get(moment):
            return False
        now = time.monotonic()
        if now - self.last.get(moment, -1.0) < self.COOLDOWN:
            return False
        self.last[moment] = now
        if self.player is None:
            self.start()
            return False
        clip = random.choice(self.bank[moment])
        try:
            self.player.play(clip, self.volume * clip.volume)
        except Exception:  # a broken file or a vanished device never stops the game
            return False
        return True


class Silent:
    name = "none"

    def play(self, clip: Clip, gain: float) -> None:
        pass

    def close(self) -> None:
        pass


_sound = Sound(enabled=False)


def configure(enabled: bool, volume: float) -> Sound:
    """Set the game's sound up (again, after Settings change), keeping the audio device if it's already open."""
    global _sound
    _sound = Sound(enabled, volume, user_folder(), player=_sound.player)
    _sound.start()
    return _sound


def play(moment: str) -> bool:
    """Play the sound for a moment, if sound is on. Never blocks."""
    return _sound.play(moment)


def engine() -> Sound:
    return _sound


def audition(moments: list[str]) -> None:
    """Play some moments one after another, waiting for each (for trying sounds out)."""
    player = open_player()
    if player is None:
        print("No way to play sound here.")
        return
    bank, _ = load_bank(user_folder())
    for moment in moments:
        for clip in bank.get(moment, []):
            samples, rate = decode(clip.source)
            print(f"  {moment}: {getattr(clip.source, 'name', clip.source)}")
            player.play(clip, 0.8 * clip.volume)
            time.sleep(len(samples) / rate + 0.25)
    time.sleep(0.2)


def main() -> None:
    folder = user_folder()
    bank, problems = load_bank(folder)
    if sys.argv[1:]:
        unknown = [m for m in sys.argv[1:] if m not in bank]
        if unknown:
            sys.exit(f"No sound for: {', '.join(unknown)}")
        audition(sys.argv[1:])
        return
    print(f"Your sounds go in {folder} (see the top of ptg/sound.py for how).\n")
    for moment, what in MOMENTS.items():
        clips = bank.get(moment, [])
        files = ", ".join(getattr(c.source, "name", str(c.source)) for c in clips) or "(none)"
        source = "built in" if all(c.builtin for c in clips) else "; ".join(
            sorted({f"{c.credit}" + (f", {c.license}" if c.license else "") for c in clips}))
        print(f"  {moment:<11} {what:<42} {files}  [{source}]")
        for clip in clips:
            try:
                decode(clip.source)
            except (ValueError, wave.Error, EOFError, OSError) as error:
                problems.append(f"{getattr(clip.source, 'name', clip.source)}: {error}")
    if problems:
        print("\nProblems:")
        for problem in problems:
            print(f"  - {problem}")


if __name__ == "__main__":
    main()
