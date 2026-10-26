"""Sound: short 8-bit effects for the moments that matter, played without ever holding up the game.

A terminal can only beep, so the game plays its own sound. The good way is a small mixer on a thread of its own,
streaming straight to the speakers through sounddevice (PortAudio): it's quick (about 60 ms), sounds overlap, and
the volume works. If sounddevice can't load, the system's player is used instead (afplay on macOS, pw-play, paplay
or aplay on Linux, winsound on Windows), which is slower to start. With no player, with sound off in Settings, or
with PTG_SOUND=0, the game is simply quiet. A sound can never crash or stall it.

The game plays sounds by moment (MOMENTS below), and a moment's sound can also be music: looped until it's stopped,
fading out (music, stop_music: the title screen's). The built-in ones are synthesized by tools/build_sounds.py into
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

The debug screen (F12) lists them too, with a play button for each.
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
    "bomb": "a bomb goes off",
    "step": "you walk into a room",
    "locked": "a locked door",
    "unlock": "you unlock a door",
    "item": "you pick something up",
    "coin": "you find gold",
    "heal": "you heal",
    "secret": "a secret is found",
    "secret_room": "a floor's secret room is found",
    "shop": "you walk into a shop",
    "shop_shiny": "you walk into Granny Kamultruk's shop",
    "story": "a story card appears",
    "chest": "a chest opens",
    "fountain": "you drink from a fountain",
    "shrine": "you make an offering",
    "descend": "you go down the stairs",
    "fate": "you spend Fate to reroll",
    "level_up": "you level up",
    "death": "you die",
    "victory": "you win",
    "thunder": "lightning strikes, on the title screen",
    "title_music": "the title screen's music (it loops while the title shows)",
}
MUSIC_LEVEL = 0.6  # music sits under the sounds

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


def clip_name(clip: Clip) -> str:
    return getattr(clip.source, "name", str(clip.source))


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


def clip_length(clip: Clip) -> float | None:
    """How long a clip plays, in seconds, from its header (None if the file can't be read)."""
    try:
        with clip.source.open("rb") as f, wave.open(f) as w:
            return w.getnframes() / w.getframerate()
    except (wave.Error, EOFError, OSError, ZeroDivisionError):
        return None


BARS = "▁▂▃▄▅▆▇█"


def envelope(clip: Clip, width: int = 32) -> str:
    """The clip's loudness over time, as a row of little bars."""
    samples, _ = decode(clip.source)
    step = max(1, -(-len(samples) // width))
    peaks = [max(abs(v) for v in samples[i:i + step]) for i in range(0, len(samples), step)]
    top = max(peaks, default=0) + 1
    return "".join(BARS[peak * len(BARS) // top] for peak in peaks)


def resample(samples: array, rate: int, target: int, smooth: bool = False) -> array:
    """Change the sample rate by holding each sample (no smoothing, so 8-bit sounds keep their crunch), or, `smooth`,
    between neighbours (music: held, a long pure tone warbles, each sample held two times or three)."""
    if rate == target:
        return samples
    step = rate / target
    count = int(len(samples) / step)
    if not smooth:
        return array("h", (samples[int(i * step)] for i in range(count)))
    last = len(samples) - 1
    out = array("h", bytes(2 * count))
    for i in range(count):
        at = i * step
        j = int(at)
        k = j + 1 if j < last else j
        out[i] = int(samples[j] + (samples[k] - samples[j]) * (at - j))
    return out


# --- players ----------------------------------------------------------------------------------------------------

class Mixer:
    """Mixes overlapping sounds on its own thread and streams them to the speakers. The stream sleeps after two
    quiet seconds and wakes for the next sound."""

    name = "sounddevice"
    BLOCK = 512
    VOICES = 8
    # Seconds of sound queued for the speakers. The mixer is Python on a thread: whenever the screen's thread (or the
    # title's storm, drawn in the background) holds the interpreter for a while, it can't keep up, and with less
    # queued than that the speakers run dry: the music skipped and crackled. A tenth of a second is never noticed.
    LATENCY = 0.12
    LIMIT = 24000  # over this, a mix (music and thunder at once) is squeezed rather than clipped

    def __init__(self, sd) -> None:
        self.rate = int(sd.query_devices(kind="output")["default_samplerate"])
        self.stream = sd.RawOutputStream(samplerate=self.rate, channels=1, dtype="int16", latency=self.LATENCY)
        self.voices: list[list] = []  # [samples, position, gain]
        self.music: list | None = None  # [samples, position, gain, fade]: looped until it fades out
        self.wanted = ""  # the music asked for (it may still be being made ready)
        self.cache: dict[str, array] = {}
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.closed = False
        threading.Thread(target=self._run, name="ptg-sound", daemon=True).start()

    def _samples(self, clip: Clip, smooth: bool = False) -> array:
        key = str(clip.source)
        if key not in self.cache:
            self.cache[key] = resample(*decode(clip.source), self.rate, smooth=smooth)
        return self.cache[key]

    def play(self, clip: Clip, gain: float) -> None:
        samples = self._samples(clip)
        with self.lock:
            if len(self.voices) >= self.VOICES:
                self.voices.pop(0)
            self.voices.append([samples, 0, gain])
        self.wake.set()

    def loop(self, clip: Clip, gain: float) -> None:
        """Music: the clip over and over until stop_loop (the same clip already looping just changes its gain). The
        first time, it's made ready on a thread of its own (smoothly resampled, a moment's work), never the
        caller's."""
        key = str(clip.source)
        self.wanted = key
        if key in self.cache:
            self._start(key, gain)
            return

        def ready() -> None:
            self._samples(clip, smooth=True)
            if self.wanted == key:
                self._start(key, gain)

        threading.Thread(target=ready, name="ptg-music-ready", daemon=True).start()

    def _start(self, key: str, gain: float) -> None:
        samples = self.cache[key]
        with self.lock:
            if self.music and self.music[0] is samples:
                self.music[2], self.music[3] = gain, 0.0
            else:
                self.music = [samples, 0, gain, 0.0]
        self.wake.set()

    def stop_loop(self, fade: float = 0.8) -> None:
        self.wanted = ""
        with self.lock:
            if self.music:
                self.music[3] = self.music[2] / max(1.0, fade * self.rate / self.BLOCK)

    def _mix(self) -> bytes | None:
        with self.lock:
            if not self.voices and not self.music:
                return None
            out = [0] * self.BLOCK
            for voice in self.voices:
                samples, position, gain = voice
                for i, value in enumerate(samples[position:position + self.BLOCK]):
                    out[i] += int(value * gain)
                voice[1] = position + self.BLOCK
            self.voices = [v for v in self.voices if v[1] < len(v[0])]
            if self.music:
                samples, position, gain, fade = self.music
                size = len(samples)
                for i in range(self.BLOCK):
                    out[i] += int(samples[(position + i) % size] * gain)
                self.music[1] = (position + self.BLOCK) % size
                if fade:
                    self.music[2] = gain - fade
                    if self.music[2] <= 0:
                        self.music = None
        limit = self.LIMIT
        return array("h", (v if -limit <= v <= limit else self._squeeze(v) for v in out)).tobytes()

    def _squeeze(self, v: int) -> int:
        """A loud moment, squeezed into what's left above LIMIT rather than clipped (a clip crackles)."""
        over = abs(v) - self.LIMIT
        room = 32767 - self.LIMIT
        squeezed = self.LIMIT + int(room * over / (over + room))
        return squeezed if v > 0 else -squeezed

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
        self.looping: object | None = None  # the music playing now (a token: a new one, or none, ends the old)
        self.music: subprocess.Popen | None = None

    def _start(self, clip: Clip, gain: float) -> subprocess.Popen:
        return subprocess.Popen(self.argv(str(clip.source), gain), stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def play(self, clip: Clip, gain: float) -> None:
        self.running = [p for p in self.running if p.poll() is None]
        if len(self.running) < 4:
            self.running.append(self._start(clip, gain))

    def loop(self, clip: Clip, gain: float) -> None:
        """Music: the player started again each time it finishes, until stop_loop."""
        self.stop_loop()
        token = self.looping = object()

        def again() -> None:
            while self.looping is token:
                self.music = self._start(clip, gain)
                self.music.wait()

        threading.Thread(target=again, name="ptg-music", daemon=True).start()

    def stop_loop(self, fade: float = 0.0) -> None:
        self.looping = None
        if self.music and self.music.poll() is None:
            self.music.terminate()

    def close(self) -> None:
        self.stop_loop()


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

    def loop(self, clip: Clip, gain: float) -> None:  # (winsound plays one thing at a time: a sound stops it)
        import winsound

        winsound.PlaySound(str(clip.source), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_LOOP
                           | winsound.SND_NODEFAULT)

    def stop_loop(self, fade: float = 0.0) -> None:
        import winsound

        winsound.PlaySound(None, 0)

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
        self.wanted: str = ""  # the music that should be playing (started once the player's open)

    def start(self) -> None:
        """Open the audio device in the background (it takes a moment), so it's ready for the first sound."""
        if self.enabled and self.player is None and not self._opening:
            self._opening = True
            threading.Thread(target=self._open, name="ptg-sound-open", daemon=True).start()

    def _open(self) -> None:
        self.player = open_player() or Silent()
        if self.wanted:
            self.music(self.wanted)

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


    def music(self, moment: str) -> bool:
        """Loop a moment's sound as music (one at a time: it takes over from any other), if sound is on."""
        self.wanted = moment
        if not self.enabled or self.volume <= 0 or not self.bank.get(moment):
            return False
        if self.player is None:
            self.start()  # (it starts once the player's open)
            return False
        clip = self.bank[moment][0]
        try:
            self.player.loop(clip, self.volume * clip.volume * MUSIC_LEVEL)
        except Exception:
            return False
        return True

    def stop_music(self, fade: float = 0.8) -> None:
        self.wanted = ""
        if self.player is not None:
            try:
                self.player.stop_loop(fade)
            except Exception:
                pass


class Silent:
    name = "none"

    def play(self, clip: Clip, gain: float) -> None:
        pass

    def loop(self, clip: Clip, gain: float) -> None:
        pass

    def stop_loop(self, fade: float = 0.0) -> None:
        pass

    def close(self) -> None:
        pass


_sound = Sound(enabled=False)


def configure(enabled: bool, volume: float) -> Sound:
    """Set the game's sound up (again, after Settings change), keeping the audio device if it's already open, and
    any music that should be playing (stopped while sound's off, on again after)."""
    global _sound
    wanted = _sound.wanted
    _sound = Sound(enabled, volume, user_folder(), player=_sound.player)
    _sound.start()
    if wanted and enabled:
        _sound.music(wanted)
    elif wanted:
        _sound.stop_music(0.0)
        _sound.wanted = wanted  # (sound back on, it plays again)
    return _sound


def play(moment: str) -> bool:
    """Play the sound for a moment, if sound is on. Never blocks."""
    return _sound.play(moment)


def music(moment: str) -> bool:
    """Loop a moment's sound as music until stop_music, if sound is on. Never blocks."""
    return _sound.music(moment)


def stop_music(fade: float = 0.8) -> None:
    _sound.stop_music(fade)


def engine() -> Sound:
    return _sound


def preview(clip: Clip) -> str | None:
    """Play one clip at the game's volume, even with sound off in Settings (the debug screen's play button).
    Returns why it can't, or None. It may have to open the audio device, so call it off the main thread."""
    if os.environ.get("PTG_SOUND", "1") == "0":
        return "PTG_SOUND=0 is keeping the game quiet"
    if _sound.volume <= 0:
        return "the volume is at 0% (Settings)"
    deadline = time.monotonic() + 3
    while _sound.player is None and _sound._opening and time.monotonic() < deadline:
        time.sleep(0.05)  # the engine is already opening the device
    if _sound.player is None:
        _sound.player = open_player() or Silent()
    if isinstance(_sound.player, Silent):
        return "there's no way to play sound here"
    try:
        _sound.player.play(clip, _sound.volume * clip.volume)
    except Exception as error:  # the same safety net as play()
        return f"{clip_name(clip)}: {error}"
    return None


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
            print(f"  {moment}: {clip_name(clip)}")
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
        files = ", ".join(clip_name(c) for c in clips) or "(none)"
        source = "built in" if all(c.builtin for c in clips) else "; ".join(
            sorted({f"{c.credit}" + (f", {c.license}" if c.license else "") for c in clips}))
        print(f"  {moment:<11} {what:<42} {files}  [{source}]")
        for clip in clips:
            try:
                decode(clip.source)
            except (ValueError, wave.Error, EOFError, OSError) as error:
                problems.append(f"{clip_name(clip)}: {error}")
    if problems:
        print("\nProblems:")
        for problem in problems:
            print(f"  - {problem}")


if __name__ == "__main__":
    main()
