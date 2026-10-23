"""The built-in sound effects: a tiny 8-bit synthesizer and the sounds it plays, written to src/ptg/data/sounds.

Like the sprites, the sounds are made from code rather than recorded, so they belong to the game (CC0) and anyone
can tweak one and rebuild. The synthesizer works the way old consoles did:

    square     the classic chip tone; duty 0.5 is full and round, 0.25 and 0.125 get thinner and buzzier
    triangle   soft and flute-like, stepped in 16 levels like the NES's
    saw        bright and rough
    noise      a 15-bit shift register like the NES's: hiss, thumps and crashes; `metallic` rings instead
    sine       pure (used sparingly; it doesn't sound very 8-bit)

Each sound is a list of Tones mixed together: a waveform with a pitch (optionally sliding to another), a length,
a start time, a volume, a short attack and release, and optional vibrato. Files are 8-bit, 22050 Hz mono WAV: tiny,
crunchy, and playable everywhere. A moment with several variants (hit, hit_2, hit_3) picks one at random.

    uv run python tools/build_sounds.py              # rebuild every sound
    uv run python tools/build_sounds.py coin crit    # rebuild some, and play them
"""

from __future__ import annotations

import math
import random
import sys
import wave
from dataclasses import dataclass
from pathlib import Path

RATE = 22050
OUT = Path(__file__).resolve().parent.parent / "src" / "ptg" / "data" / "sounds"
SEMITONES = {"C": -9, "C#": -8, "D": -7, "D#": -6, "E": -5, "F": -4, "F#": -3, "G": -2, "G#": -1, "A": 0, "A#": 1,
             "B": 2}


def hz(note: str) -> float:
    """"A4" -> 440.0"""
    return 440.0 * 2 ** ((SEMITONES[note[:-1]] + 12 * (int(note[-1]) - 4)) / 12)


@dataclass
class Tone:
    wave: str = "square"
    freq: float = 440.0  # Hz (for noise: how fast it changes; high is hiss, low is rumble)
    to: float | None = None  # slide to this pitch by the end
    length: float = 0.1
    at: float = 0.0
    volume: float = 0.4
    duty: float = 0.5
    attack: float = 0.003
    release: float = 0.03
    vibrato: float = 0.0  # semitones
    vibrato_rate: float = 6.0
    metallic: bool = False


def note(name: str, length: float, at: float = 0.0, **kwargs) -> Tone:
    return Tone(freq=hz(name), length=length, at=at, **kwargs)


def arp(names: list[str], step: float, at: float = 0.0, hold: float = 0.0, **kwargs) -> list[Tone]:
    """Notes one after another, `step` seconds each; the last one rings for `hold` more."""
    return [note(n, step + (hold if i == len(names) - 1 else 0.0), at + i * step, **kwargs) for i, n in enumerate(names)]


def _voice(tone: Tone) -> list[float]:
    count = int(tone.length * RATE)
    attack, release = max(1, int(tone.attack * RATE)), max(1, int(tone.release * RATE))
    out, phase, lfsr, level = [0.0] * count, 0.0, 1, 1.0
    for i in range(count):
        progress = i / count
        freq = tone.freq if tone.to is None else tone.freq * (tone.to / tone.freq) ** progress
        if tone.vibrato:
            freq *= 2 ** (tone.vibrato * math.sin(2 * math.pi * tone.vibrato_rate * i / RATE) / 12)
        phase += freq / RATE
        if phase >= 1.0:
            phase -= int(phase)
            if tone.wave == "noise":  # clock the shift register once per period
                bit = (lfsr ^ (lfsr >> (6 if tone.metallic else 1))) & 1
                lfsr = (lfsr >> 1) | (bit << 14)
                level = 1.0 if lfsr & 1 else -1.0
        if tone.wave == "square":
            value = 1.0 if phase < tone.duty else -1.0
        elif tone.wave == "triangle":
            value = round((1.0 - 4.0 * abs(phase - 0.5)) * 7.5) / 7.5
        elif tone.wave == "saw":
            value = 2.0 * phase - 1.0
        elif tone.wave == "noise":
            value = level
        else:
            value = math.sin(2 * math.pi * phase)
        envelope = min(1.0, i / attack, (count - i) / release)
        out[i] = value * envelope * tone.volume
    return out


def render(tones: list[Tone]) -> bytes:
    """Mix the tones and quantize to 8-bit unsigned samples."""
    length = int((max(t.at + t.length for t in tones) + 0.02) * RATE)
    mix = [0.0] * length
    for tone in tones:
        start = int(tone.at * RATE)
        for i, value in enumerate(_voice(tone)):
            if start + i < length:
                mix[start + i] += value
    return bytes(max(0, min(255, round(128 + 127 * max(-1.0, min(1.0, v))))) for v in mix)


def write(path: Path, samples: bytes) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(1)
        w.setframerate(RATE)
        w.writeframes(samples)


# --- the sounds -------------------------------------------------------------------------------------------------

def _rattle(times: list[float], seed: int, volume: float = 0.35) -> list[Tone]:
    """Dice clattering: a wooden click at each time, at a slightly different pitch."""
    rng = random.Random(seed)
    tones = []
    for t in times:
        tones.append(Tone("noise", rng.uniform(5000, 9000), length=0.018, at=t, volume=volume, release=0.01))
        tones.append(Tone("triangle", rng.uniform(900, 1700), length=0.012, at=t, volume=volume * 0.6))
    return tones


def _tumble_times(frames: int = 14) -> list[float]:
    """When the big d20's tumble frames change (ui/dice.py: 0.03 + 0.012 * i seconds apart), so clicks line up."""
    times, t = [], 0.0
    for i in range(frames):
        times.append(t)
        t += 0.03 + 0.012 * i
    return times


def _hit(pitch: float, seed: int) -> list[Tone]:
    rng = random.Random(seed)
    return [Tone("noise", rng.uniform(5000, 7000), length=0.07, volume=0.38, release=0.04),
            Tone("square", pitch, to=pitch / 3, length=0.09, duty=0.25, volume=0.3)]


def _sparkle(names: list[str], step: float, volume: float = 0.3) -> list[Tone]:
    """Twinkling: each note with a quieter echo just after it."""
    tones = []
    for i, n in enumerate(names):
        tones.append(note(n, step * 2, i * step, wave="triangle", volume=volume, release=step * 1.5))
        tones.append(note(n, step * 2, i * step + step * 0.6, wave="square", duty=0.125, volume=volume * 0.3,
                          release=step * 1.5))
    return tones


SOUNDS: dict[str, list[list[Tone]]] = {
    # the interface: small, quiet, out of the way
    "select": [[note("A5", 0.03, duty=0.25, volume=0.22), note("E6", 0.05, 0.03, duty=0.25, volume=0.22)]],
    "open": [[note("E5", 0.03, duty=0.125, volume=0.18), note("B5", 0.05, 0.03, duty=0.125, volume=0.18)]],
    "close": [[note("B5", 0.03, duty=0.125, volume=0.18), note("E5", 0.05, 0.03, duty=0.125, volume=0.18)]],

    # dice
    "dice_roll": [_rattle(_tumble_times(), seed=1)],
    "dice_small": [_rattle([0.0, 0.05, 0.11, 0.19], seed=2, volume=0.25)],
    "dice_land": [[Tone("noise", 2500, length=0.05, volume=0.38, metallic=True, release=0.03),
                   Tone("square", 150, to=60, length=0.1, duty=0.5, volume=0.3)]],
    "dice_tick": [[note("C6", 0.035, duty=0.25, volume=0.22)]],

    # how a roll went (ptg/outcome.py)
    "great": [arp(["C5", "E5", "G5", "C6"], 0.06, duty=0.5, volume=0.32)
              + [note("C6", 0.4, 0.24, duty=0.25, volume=0.3, vibrato=0.25, release=0.25),
                 note("E6", 0.4, 0.24, wave="triangle", volume=0.3, release=0.25)]],
    "good": [[note("G5", 0.07, duty=0.5, volume=0.42), note("C6", 0.2, 0.07, duty=0.5, volume=0.42, release=0.12)]],
    "neutral": [[note("E5", 0.1, wave="triangle", volume=0.4), note("E5", 0.16, 0.12, wave="triangle", volume=0.3,
                                                                      release=0.1)]],
    "bad": [[note("E4", 0.1, duty=0.5, volume=0.42), note("C4", 0.24, 0.1, duty=0.5, volume=0.42, release=0.14)]],
    "awful": [[Tone("square", 330, to=82, length=0.7, duty=0.5, volume=0.3, vibrato=0.6, vibrato_rate=7,
                    release=0.2),
               Tone("noise", 300, length=0.2, at=0.55, volume=0.2)]],

    # fighting
    "hit": [_hit(260, 1), _hit(230, 2), _hit(290, 3)],
    "crit_hit": [_hit(300, 4) + [note("E7", 0.18, 0.05, wave="triangle", volume=0.3, release=0.15),
                                 note("B6", 0.2, 0.09, duty=0.125, volume=0.15, release=0.15)]],
    "miss": [[Tone("noise", 9000, to=1500, length=0.17, volume=0.28, attack=0.04, release=0.08)]],
    "hurt": [[Tone("square", 280, to=70, length=0.18, duty=0.5, volume=0.35),
              Tone("noise", 2500, length=0.1, volume=0.3, metallic=True)]],
    "dodge": [[Tone("triangle", 300, to=1300, length=0.12, volume=0.4, release=0.05)]],
    "windup": [[Tone("square", 170, to=520, length=0.45, duty=0.125, volume=0.34, vibrato=0.5, vibrato_rate=13,
                     release=0.05)]],
    "stun": [[note("A5", 0.5, wave="triangle", volume=0.35, vibrato=2.0, vibrato_rate=9, release=0.15),
              note("E6", 0.3, 0.15, duty=0.125, volume=0.12, vibrato=2.0, vibrato_rate=9, release=0.15)]],
    "kill": [[Tone("noise", 1500, to=150, length=0.4, volume=0.3, release=0.2)]
             + arp(["C5", "G4", "C4"], 0.07, duty=0.25, volume=0.25, hold=0.1)],

    # exploring
    "step": [[Tone("noise", 800, length=0.035, volume=0.22), Tone("noise", 650, length=0.035, at=0.16, volume=0.18)],
             [Tone("noise", 700, length=0.035, volume=0.22), Tone("noise", 850, length=0.035, at=0.15, volume=0.18)]],
    "locked": [[Tone("square", 98, length=0.06, volume=0.35), Tone("square", 92, length=0.09, at=0.09, volume=0.35)]],
    "unlock": [[Tone("noise", 5000, length=0.02, volume=0.3, metallic=True),
                note("C5", 0.05, 0.04, duty=0.25, volume=0.28), note("G5", 0.12, 0.09, duty=0.25, volume=0.28)]],
    "item": [arp(["C6", "E6", "G6"], 0.045, wave="triangle", volume=0.38, hold=0.06)],
    "coin": [[note("B5", 0.07, duty=0.5, volume=0.34), note("E6", 0.3, 0.07, duty=0.5, volume=0.34, release=0.25)]],
    "heal": [arp(["C5", "E5", "G5", "C6", "E6"], 0.06, wave="triangle", volume=0.38, attack=0.01, hold=0.15)],
    "secret": [_sparkle(["A6", "E6", "C#6", "A5", "E6", "A6"], 0.06)],
    "story": [[note("C6", 0.6, wave="triangle", volume=0.32, release=0.45),
               note("G6", 0.5, 0.12, wave="triangle", volume=0.22, release=0.4),
               note("C7", 0.4, 0.24, duty=0.125, volume=0.08, release=0.3)]],
    "chest": [[Tone("saw", 170, to=250, length=0.28, volume=0.18, vibrato=0.8, vibrato_rate=17, attack=0.03),
               note("B5", 0.07, 0.3, duty=0.5, volume=0.34), note("E6", 0.3, 0.37, duty=0.5, volume=0.34,
                                                                 release=0.25)]],
    "fountain": [[note(n, 0.05, t, wave="triangle", volume=0.3, release=0.03)
                  for n, t in (("G5", 0.0), ("D6", 0.07), ("B5", 0.13), ("E6", 0.2), ("A5", 0.28), ("D6", 0.34))]
                 + [Tone("noise", 3000, length=0.45, volume=0.06, attack=0.1, release=0.2)]],
    "shrine": [[note("A2", 0.7, wave="triangle", volume=0.4, attack=0.08, release=0.3),
                note("E6", 0.5, 0.25, wave="triangle", volume=0.25, release=0.4),
                note("A6", 0.4, 0.35, duty=0.125, volume=0.08, release=0.3)]],
    "descend": [arp(["C6", "G5", "E5", "C5", "G4", "C4"], 0.075, duty=0.25, volume=0.38, hold=0.15)],
    "fate": [[note(n, 0.06, i * 0.05, wave="triangle", volume=0.3 - i * 0.025, release=0.04)
              for i, n in enumerate(["E6", "B6", "E6", "B6", "E6", "B6", "E7"])]],
    "level_up": [arp(["C5", "E5", "G5", "C6"], 0.07, duty=0.5, volume=0.42)
                 + arp(["G5", "C6"], 0.07, at=0.32, duty=0.5, volume=0.42)
                 + [note("E6", 0.4, 0.46, duty=0.25, volume=0.42, vibrato=0.2, release=0.25)]],
    "death": [arp(["E4", "D#4", "D4"], 0.24, duty=0.5, volume=0.3, release=0.06)
              + [note("C#4", 0.8, 0.72, duty=0.5, volume=0.3, vibrato=0.4, vibrato_rate=5, release=0.5),
                 note("C#3", 0.8, 0.72, wave="triangle", volume=0.35, release=0.5)]],
    "victory": [arp(["G4", "C5", "E5", "G5"], 0.1, duty=0.5, volume=0.3)
                + arp(["E5", "G5"], 0.1, at=0.45, duty=0.5, volume=0.3)
                + [note("C6", 0.8, 0.65, duty=0.5, volume=0.3, vibrato=0.25, release=0.4),
                   note("C4", 0.8, 0.65, wave="triangle", volume=0.4, release=0.4)]],
}


def files_for(name: str) -> list[str]:
    return [f"{name}.wav" if i == 0 else f"{name}_{i + 1}.wav" for i in range(len(SOUNDS[name]))]


def build(names: list[str] | None = None) -> list[Path]:
    OUT.mkdir(parents=True, exist_ok=True)
    written = []
    for name in names or SOUNDS:
        for variant, filename in zip(SOUNDS[name], files_for(name)):
            path = OUT / filename
            write(path, render(variant))
            written.append(path)
    return written


def main() -> None:
    names = sys.argv[1:]
    unknown = [n for n in names if n not in SOUNDS]
    if unknown:
        sys.exit(f"No such sound: {', '.join(unknown)}. Sounds: {', '.join(SOUNDS)}")
    written = build(names or None)
    print(f"Wrote {len(written)} sound files to {OUT}")
    if names:
        sys.path.insert(0, str(OUT.parent.parent.parent))
        from ptg import sound

        sound.audition(names)


if __name__ == "__main__":
    main()
