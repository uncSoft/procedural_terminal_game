"""The built-in sound effects: a tiny 8-bit synthesizer and the sounds it plays, written to src/ptg/data/sounds.

Like the sprites, the sounds are made from code rather than recorded, so they belong to the game (CC0) and anyone
can tweak one and rebuild. The synthesizer works the way old consoles did:

    square     the classic chip tone; duty 0.5 is full and round, 0.25 and 0.125 get thinner and buzzier
    triangle   soft and flute-like, stepped in 16 levels like the NES's
    saw        bright and rough
    noise      a 15-bit shift register like the NES's: hiss, thumps and crashes; `metallic` rings instead
    sine       pure (used sparingly; it doesn't sound very 8-bit)

Each sound is a list of Tones mixed together: a waveform with a pitch (optionally sliding to another), a length,
a start time, a volume, a short attack and release, optional vibrato, and an optional low-pass filter (`cutoff`)
that takes the top end off: the chip tones are bright, and a filtered one is warm, soft or far away. Files are 8-bit,
22050 Hz mono WAV: tiny, crunchy, and playable everywhere. A softened sound (one with a filtered tone) and music
(LOOPS) are 16-bit: 8 bits hiss in a quiet tail, and grind a long fade down in audible steps. A moment with several
variants (hit, hit_2, hit_3) picks one at random: each fighting sound has a bright one and a softer, duller one.

    uv run python tools/build_sounds.py              # rebuild every sound
    uv run python tools/build_sounds.py coin crit    # rebuild some, and play them
"""

from __future__ import annotations

import math
import random
import re
import sys
import wave
from dataclasses import dataclass, replace
from pathlib import Path

RATE = 22050
WHITE = RATE  # noise changing every sample: a plain hiss, for a filter to shape (a thud, a whoosh, a rumble)
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
    cutoff: float | None = None  # a low-pass filter (Hz): the top end taken off, warmer and softer (None: as it is)
    cutoff_to: float | None = None  # the filter sliding to this by the end (a boom darkening into a rumble)


def note(name: str, length: float, at: float = 0.0, **kwargs) -> Tone:
    return Tone(freq=hz(name), length=length, at=at, **kwargs)


def arp(names: list[str], step: float, at: float = 0.0, hold: float = 0.0, **kwargs) -> list[Tone]:
    """Notes one after another, `step` seconds each; the last one rings for `hold` more."""
    return [note(n, step + (hold if i == len(names) - 1 else 0.0), at + i * step, **kwargs) for i, n in enumerate(names)]


def _corner(cutoff: float) -> float:
    """How far a filter stage moves toward each new sample, for a cutoff in Hz."""
    return 1.0 - math.exp(-2 * math.pi * min(cutoff, RATE / 2) / RATE)


def _voice(tone: Tone) -> list[float]:
    count = int(tone.length * RATE)
    attack, release = max(1, int(tone.attack * RATE)), max(1, int(tone.release * RATE))
    out, phase, lfsr, level = [0.0] * count, 0.0, 1, 1.0
    low = lower = 0.0  # the filter: two gentle stages, one after the other
    corner = _corner(tone.cutoff) if tone.cutoff else 0.0
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
        if tone.cutoff:
            if tone.wave == "square":  # (centred: a thin pulse sits off zero, a thump under every note)
                value -= 2 * tone.duty - 1
            if tone.cutoff_to is not None:
                corner = _corner(tone.cutoff * (tone.cutoff_to / tone.cutoff) ** progress)
            low += corner * (value - low)
            lower += corner * (low - lower)
            value = lower
        envelope = min(1.0, i / attack, (count - i) / release)
        out[i] = value * envelope * tone.volume
    return out


def _sum(tones: list[Tone]) -> list[float]:
    """The tones mixed, as loud as they come."""
    length = int((max(t.at + t.length for t in tones) + 0.02) * RATE)
    out = [0.0] * length
    for tone in tones:
        start = int(tone.at * RATE)
        for i, value in enumerate(_voice(tone)):
            if start + i < length:
                out[start + i] += value
    return out


def mix(tones: list[Tone]) -> list[float]:
    """The tones mixed, as samples in -1..1."""
    return [max(-1.0, min(1.0, v)) for v in _sum(tones)]


def render(tones: list[Tone]) -> bytes:
    """Mix the tones and quantize to 8-bit unsigned samples."""
    return bytes(round(128 + 127 * v) for v in mix(tones))


def render16(samples: list[float]) -> bytes:
    """Samples in -1..1 as 16-bit signed little-endian: for music, whose long fades 8 bits would grind into steps."""
    return b"".join(max(-32767, min(32767, round(32767 * v))).to_bytes(2, "little", signed=True) for v in samples)


def fold(samples: list[float], loop: float) -> list[float]:
    """A loop exactly `loop` seconds long: whatever rings on past its end is mixed back in at its start, so it
    repeats without a seam."""
    size = int(loop * RATE)
    out = samples[:size] + [0.0] * max(0, size - len(samples))
    for i, v in enumerate(samples[size:]):
        out[i % size] += v
    return out


def level(samples: list[float], loudness: float) -> list[float]:
    """Music made `loudness` loud on average (RMS), its loudest moments eased in under full scale, not clipped."""
    gain = loudness / (math.sqrt(sum(v * v for v in samples) / len(samples)) or 1.0)
    knee = 0.85
    return [v * gain if abs(v * gain) <= knee else
            math.copysign(knee + (1 - knee) * math.tanh((abs(v * gain) - knee) / (1 - knee)), v) for v in samples]


def write(path: Path, samples: bytes, width: int = 1) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(width)
        w.setframerate(RATE)
        w.writeframes(samples)


# --- the sounds -------------------------------------------------------------------------------------------------

def _rattle(times: list[float], seed: int, volume: float = 0.35, cutoff: float | None = None) -> list[Tone]:
    """Dice clattering: a click at each time, at a slightly different pitch; `cutoff`, duller, wood on wood."""
    rng = random.Random(seed)
    tones = []
    for t in times:
        if cutoff:
            tones.append(Tone("noise", WHITE, length=0.022, at=t, volume=volume * 1.3, release=0.014,
                              cutoff=cutoff * rng.uniform(0.8, 1.2)))
        else:
            tones.append(Tone("noise", rng.uniform(5000, 9000), length=0.018, at=t, volume=volume, release=0.01))
        tones.append(Tone("triangle", rng.uniform(900, 1700) * (0.6 if cutoff else 1), length=0.012, at=t,
                          volume=volume * 0.6))
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


def _thud(pitch: float, seed: int, volume: float = 0.5) -> list[Tone]:
    """A blow that lands dull and heavy (_hit's softer cousin): a knock of filtered noise and a body's thump."""
    rng = random.Random(seed)
    return [Tone("noise", WHITE, length=0.1, volume=volume * 1.1, release=0.08, cutoff=rng.uniform(1000, 1500),
                 cutoff_to=280),
            Tone("triangle", pitch, to=pitch / 3, length=0.13, volume=volume * 0.6, release=0.09, cutoff=900)]


def _whoosh(low: float, high: float, length: float, volume: float) -> list[Tone]:
    """Air moving past: noise swelling as its filter opens, from `low` to `high` Hz, and dying away."""
    return [Tone("noise", WHITE, length=length, volume=volume, attack=length * 0.4, release=length * 0.55,
                 cutoff=low, cutoff_to=high)]


def _sparkle(names: list[str], step: float, volume: float = 0.3, at: float = 0.0) -> list[Tone]:
    """Twinkling: each note with a quieter echo just after it."""
    tones = []
    for i, n in enumerate(names):
        tones.append(note(n, step * 2, at + i * step, wave="triangle", volume=volume, release=step * 1.5))
        tones.append(note(n, step * 2, at + i * step + step * 0.6, wave="square", duty=0.125, volume=volume * 0.3,
                          release=step * 1.5))
    return tones


def _boom(volume: float, bright: float = 900, at: float = 0.0, length: float = 1.6) -> list[Tone]:
    """A deep BOOM: a thump you feel, its pitch falling away, and the roar of the air it shoved, filtered dark and
    closing darker as it fades (`bright`: how bright it starts, in Hz). Nothing in it cracks or hisses."""
    return [Tone("sine", 74, to=33, length=length, at=at, volume=volume * 0.5, attack=0.005, release=length * 0.8),
            Tone("triangle", 125, to=44, length=length * 0.45, at=at, volume=volume * 0.28, attack=0.004,
                 release=length * 0.4, cutoff=420),
            Tone("noise", RATE, length=length * 1.2, at=at, volume=volume * 1.2, attack=0.006,
                 release=length * 1.05, cutoff=bright, cutoff_to=90)]


def _thunder(seed: int, distance: float) -> list[Tone]:
    """Thunder: a BOOM where it struck, then a low rumble rolling on for a few seconds, swelling and fading as it
    goes. The further away it struck, the softer and duller the boom, and the lower and later the rolls. (It once
    began with a crack of bright noise: harsh, and on small speakers nearly all you heard.)"""
    rng = random.Random(seed)
    near = 1.0 - distance
    tones = _boom(0.4 + 0.22 * near, bright=300 + 650 * near, length=1.3 + 0.6 * distance)
    for i in range(8):  # the rolls: overlapping rumbles, each a little lower and softer
        at = 0.3 + 0.25 * distance + i * rng.uniform(0.28, 0.48)
        corner = rng.uniform(170, 300) * (1 - 0.35 * distance) * (0.93 ** i)
        tones.append(Tone("noise", RATE, length=rng.uniform(1.0, 1.6), at=at,
                          volume=(0.72 + 0.29 * near) * (0.88 ** i) * rng.uniform(0.7, 1.0),
                          attack=rng.uniform(0.18, 0.4), release=0.8, cutoff=corner, cutoff_to=corner * 0.6))
    tones.append(Tone("sine", 50, to=31, length=3.0, at=0.35, volume=0.09 + 0.04 * near, attack=0.7,
                      release=1.8))  # the ground's own long, low shudder under the rolls
    return tones


# The title screen's music: a short loop that repeats while the title shows (sound.music). An original piece, in
# the spirit of the minimal, hypnotic horror themes of the seventies: a bell-like figure that never changes, in 7/8
# (2+2+3), over a bass that moves underneath it every two bars (A, F, D, E: the floor dropping away), then a slow
# line above, then tubular bells. 16 bars, folded so it loops without a seam (LOOPS).
EIGHTH = 0.178
BAR = 7 * EIGHTH
FIGURE = (["A4", "E5", "C5", "E5", "B4", "E5", "F5"], ["A4", "E5", "C5", "E5", "G4", "E5", "D5"])
BASS = ["A2", "F2", "D2", "E2"]  # two bars each, twice over
LINE = ["E5", "C5", "F5", "E5", "D5", "C5", "B4", "G#4"]  # the line above: a bar each, from bar 9


def _bell(name: str, at: float, volume: float) -> list[Tone]:
    """A tubular bell: a struck, metallic attack, its note and the clangorous partial above it, ringing long."""
    pitch = hz(name)
    return [Tone("noise", 6000, length=0.04, at=at, volume=volume * 0.5, metallic=True, release=0.03),
            Tone("sine", pitch, length=2.4, at=at, volume=volume, attack=0.002, release=2.2),
            Tone("sine", pitch * 2.76, length=1.2, at=at, volume=volume * 0.35, attack=0.002, release=1.1),
            Tone("triangle", pitch / 2, length=1.6, at=at, volume=volume * 0.4, attack=0.002, release=1.4)]


def _title_music() -> list[Tone]:
    tones: list[Tone] = []
    for bar in range(16):
        start = bar * BAR
        for i, name in enumerate(FIGURE[bar % 2]):  # the figure: a thin, glassy pulse, every bar
            tones.append(note(name, EIGHTH * 0.9, start + i * EIGHTH, duty=0.125, volume=0.13, release=0.08))
            if bar >= 4:  # (doubled an octave down, softly, once the bass is in)
                tones.append(note(name[:-1] + str(int(name[-1]) - 1), EIGHTH * 0.8, start + i * EIGHTH,
                                  wave="triangle", volume=0.07, release=0.06))
        if bar >= 2:  # the bass, on the 2+2+3
            root = BASS[(bar // 2) % 4]
            for beat, length in ((0, 2), (2, 2), (4, 3)):
                tones.append(note(root, EIGHTH * length * 0.85, start + beat * EIGHTH, wave="triangle",
                                  volume=0.3 if beat == 0 else 0.22, release=0.1))
    for i, name in enumerate(LINE):  # the line above, from bar 9, falling to the leading note (and home: bar 1)
        tones.append(note(name, BAR * 0.97, (8 + i) * BAR, duty=0.25, volume=0.11, attack=0.15, release=0.6,
                          vibrato=0.15, vibrato_rate=4.5))
    for bar, name in ((12, "E4"), (14, "A3"), (15, "E4")):  # the bells
        tones += _bell(name, bar * BAR, 0.22)
    return tones


# --- the game's music ---------------------------------------------------------------------------------------------
# Played while you're down there (ui/game_screen.py picks it): the floor's, slow and atmospheric, and a fight's, fast,
# the way the old console RPGs fought. All original, each a loop folded like the title's, and levelled (LOUDNESS): a
# floor's sits low under everything, a fight's comes up.

def _octave(name: str, by: int = 1) -> str:
    """ "A3" -> "A4" """
    return name[:-1] + str(int(name[-1]) + by)


def _phrase(text: str, at: float, beat: float, gap: float = 0.92, **kwargs) -> list[Tone]:
    """A tune written out: "E5:1.5 D5:.5 - C5" is E for a beat and a half, D for half a beat, a beat's rest, then C for
    a beat, from `at` (`beat`: how long a beat is, in seconds). Each note is held `gap` of its length."""
    tones, t = [], at
    for word in text.split():
        name, _, beats = word.partition(":")
        length = float(beats or 1) * beat
        if name != "-":
            tones.append(note(name, length * gap, t, **kwargs))
        t += length
    return tones


def _pad(names: list[str], at: float, length: float, volume: float, wave: str = "saw", cutoff: float = 1000,
         attack: float = 0.8, release: float = 1.2, duty: float = 0.5) -> list[Tone]:
    """A chord held, soft: each note twice, a shade out of tune with itself so it shimmers, and filtered warm."""
    return [Tone(wave, hz(name) * detune, length=length, at=at, volume=volume, duty=duty, attack=attack,
                 release=release, cutoff=cutoff) for name in names for detune in (0.996, 1.004)]


def _echoes(tones: list[Tone], delay: float, repeats: int = 2, decay: float = 0.4) -> list[Tone]:
    """Tones and their echoes off the walls: each again `delay` seconds later, softer and duller each time."""
    return tones + [replace(tone, at=tone.at + k * delay, volume=tone.volume * decay ** k,
                            cutoff=(tone.cutoff or 6000) * 0.6 ** k, cutoff_to=None)
                    for tone in tones for k in range(1, repeats + 1)]


def _chime(name: str, at: float, volume: float) -> list[Tone]:
    """A bell far off: _bell without its strike, its partials soft, ringing long."""
    pitch = hz(name)
    return [Tone("sine", pitch, length=4.0, at=at, volume=volume, attack=0.004, release=3.8),
            Tone("sine", pitch * 2.76, length=1.8, at=at, volume=volume * 0.3, attack=0.004, release=1.7),
            Tone("sine", pitch * 5.4, length=0.7, at=at, volume=volume * 0.1, attack=0.004, release=0.65)]


def _kick(at: float, volume: float) -> list[Tone]:
    return [Tone("sine", 150, to=48, length=0.17, at=at, volume=volume, attack=0.001, release=0.13),
            Tone("noise", WHITE, length=0.015, at=at, volume=volume * 0.6, release=0.01, cutoff=1800)]


def _snare(at: float, volume: float) -> list[Tone]:
    return [Tone("noise", WHITE, length=0.15, at=at, volume=volume * 1.4, release=0.12, cutoff=4200, cutoff_to=2000),
            Tone("triangle", 200, to=150, length=0.08, at=at, volume=volume * 0.7, release=0.05)]


def _hat(at: float, volume: float) -> list[Tone]:
    return [Tone("noise", WHITE, length=0.03, at=at, volume=volume, release=0.025, cutoff=6500)]


def _tom(at: float, pitch: float, volume: float) -> list[Tone]:
    return [Tone("sine", pitch, to=pitch * 0.6, length=0.22, at=at, volume=volume, attack=0.002, release=0.18),
            Tone("triangle", pitch, to=pitch * 0.6, length=0.12, at=at, volume=volume * 0.4, release=0.1, cutoff=900)]


def _crash(at: float, volume: float) -> list[Tone]:
    return [Tone("noise", WHITE, length=1.4, at=at, volume=volume, attack=0.002, release=1.3, cutoff=5000,
                 cutoff_to=1800)]


# A floor's music: dark and slow, like air moving through a crypt. A soft pad of chords, two bars each, D minor
# falling to its dominant (Dm, B♭, Gm, A; then Dm, C, B♭, A), a slow bass under them, notes dripping from the chord and
# echoing off the walls, a far-off chime, a draught; and from bar 5 a lonely tune on top. 16 bars.
CRYPT_BEAT = 0.7
CRYPT_BAR = 4 * CRYPT_BEAT
CRYPT = [("D2", ["A3", "D4", "F4"], ["A4", "D5", "E5", "F5"]),  # (the bass, the pad, the notes that drip)
         ("A#1", ["A#3", "D4", "F4"], ["F4", "A#4", "D5", "F5"]),
         ("G1", ["G3", "A#3", "D4"], ["G4", "A#4", "D5", "G5"]),
         ("A1", ["A3", "C#4", "E4"], ["A4", "C#5", "E5", "A5"]),
         ("D2", ["A3", "D4", "F4"], ["A4", "D5", "E5", "F5"]),
         ("C2", ["G3", "C4", "E4"], ["G4", "C5", "E5", "G5"]),
         ("A#1", ["A#3", "D4", "F4"], ["F4", "A#4", "D5", "F5"]),
         ("A1", ["A3", "C#4", "E4"], ["A4", "C#5", "E5", "A5"])]
CRYPT_DRIPS = ((0, 0), (3, 2), (6, 1), (8, 3), (11, 1), (13, 2))  # (which eighth of the two bars, which note)
CRYPT_TUNE = ("D5:2 A#4 C5 D5:3 -  E5:2 D5 E5 C#5:3 -  F5:2 E5 D5 A4:2 D5:2  E5:2 G5 F5 E5:3 -  "
              "F5:1.5 G5:.5 A5:2 A#5 A5 F5:2  E5:2 D5:2 C#5:2 A4:2")  # from bar 5, two bars to a chord


def _explore_music() -> list[Tone]:
    tones: list[Tone] = []
    eighth = CRYPT_BEAT / 2
    for i, (bass, pad, drips) in enumerate(CRYPT):
        start = 2 * i * CRYPT_BAR
        tones += [note(bass, 2 * CRYPT_BAR * 0.95, start, wave="triangle", volume=0.2, attack=0.2, release=1.2,
                       cutoff=500),
                  note(_octave(bass), 2 * CRYPT_BAR * 0.95, start, wave="triangle", volume=0.1, attack=0.4,
                       release=1.2, cutoff=600)]  # (its octave, so small speakers have it too)
        tones += _pad(pad, start, 2 * CRYPT_BAR, 0.045, cutoff=900, attack=1.2, release=1.6)
        tones += _echoes([note(drips[n], 2 * eighth, start + e * eighth, wave="triangle", volume=0.14,
                               release=1.6 * eighth, cutoff=2600) for e, n in CRYPT_DRIPS], 1.5 * eighth)
    tones += _echoes(_phrase(CRYPT_TUNE, 4 * CRYPT_BAR, CRYPT_BEAT, gap=0.96, duty=0.5, volume=0.12, attack=0.06,
                             release=0.4, vibrato=0.12, vibrato_rate=5, cutoff=1500), 1.5 * eighth, decay=0.35)
    tones += _chime("D4", 0.0, 0.12) + _chime("A3", 8 * CRYPT_BAR, 0.12)
    for i in range(4):  # the draught: air breathing through every four bars, its filter opening and closing
        tones.append(Tone("noise", WHITE, length=4 * CRYPT_BAR, at=4 * i * CRYPT_BAR, volume=0.3, attack=4.5,
                          release=5.0, cutoff=250, cutoff_to=600 if i % 2 == 0 else 350))
    return tones


# The boss floors' music: slower and lower, something breathing down there. E minor and its dark neighbours (Em, F,
# Em, Cm, Am, B: two bars each), a choir of filtered pulses, a heartbeat, a music box's few notes echoing away, a low
# line from bar 5, a bell. 12 bars.
DEEP_BEAT = 0.8
DEEP_BAR = 4 * DEEP_BEAT
DEEP = [("E2", ["E3", "B3", "G4"], "- - B5:.5 G5:.5 E5 D#5:3 -"),  # (the bass, the choir, the music box)
        ("F2", ["F3", "C4", "A4"], "- - C6:.5 A5:.5 F5 E5:3 -"),
        ("E2", ["E3", "B3", "G4"], "- - B5:.5 G5:.5 E5 F#5:3 -"),
        ("C2", ["C3", "G3", "D#4"], "- - G5:.5 D#5:.5 C5 D5:3 -"),
        ("A1", ["A2", "E3", "C4"], "- - E6:.5 C6:.5 A5 B5:3 -"),
        ("B1", ["B2", "F#3", "D#4"], "- - D#6:.5 B5:.5 F#5 A5:3 -")]
DEEP_TUNE = "G4:6 F#4:2  G4:4 D#4:4  E4:4 C4:4  D#4:4 F#4:2 B3:2"  # from bar 5


def _deep_music() -> list[Tone]:
    tones: list[Tone] = []
    for i, (bass, choir, box) in enumerate(DEEP):
        start = 2 * i * DEEP_BAR
        tones += [note(bass, 2 * DEEP_BAR * 0.97, start, wave="triangle", volume=0.22, attack=0.4, release=1.4,
                       cutoff=400),
                  note(_octave(bass), 2 * DEEP_BAR * 0.97, start, wave="triangle", volume=0.08, attack=0.6,
                       release=1.4, cutoff=500)]
        tones += _pad(choir, start, 2 * DEEP_BAR, 0.05, wave="square", cutoff=700, attack=1.6, release=2.0)
        tones += _echoes(_phrase(box, start, DEEP_BEAT, wave="triangle", volume=0.14, release=0.5, cutoff=3000), 0.6,
                         repeats=3, decay=0.42)
        for beat in (0, 2, 4, 6):  # the heartbeat
            at = start + beat * DEEP_BEAT
            tones += [Tone("triangle", 62, to=40, length=0.2, at=at, volume=0.32, attack=0.004, release=0.15,
                           cutoff=300),
                      Tone("triangle", 58, to=38, length=0.18, at=at + 0.26, volume=0.22, attack=0.004, release=0.14,
                           cutoff=300)]
        tones.append(Tone("noise", WHITE, length=2 * DEEP_BAR, at=start, volume=0.22, attack=2.5, release=3.0,
                          cutoff=180, cutoff_to=320))  # the cave's air
    tones += _echoes(_phrase(DEEP_TUNE, 4 * DEEP_BAR, DEEP_BEAT, gap=0.97, duty=0.25, volume=0.1, attack=0.3,
                             release=0.8, vibrato=0.18, vibrato_rate=4, cutoff=900), 0.6, repeats=1, decay=0.3)
    tones += _chime("E3", 0.0, 0.14) + _chime("C3", 6 * DEEP_BAR, 0.12)
    return tones


# A fight's music: fast, in A minor, the way the old console RPGs fought: a bass pumping octaves, strings racing round
# the chord, brass stabbing at the off-beats, drums, and a bold tune over all of it. 16 bars at 160.
FIGHT_BEAT = 0.375
FIGHT_BAR = 4 * FIGHT_BEAT
FIGHT = ["Am", "Am", "F", "G", "Am", "Am", "F", "E", "Dm", "Em", "F", "G", "Am", "F", "Bb", "E"]  # a chord a bar
CHORDS = {"Am": ("A2", ["A3", "C4", "E4"]), "F": ("F2", ["F3", "A3", "C4"]), "G": ("G2", ["G3", "B3", "D4"]),
          "E": ("E2", ["E3", "G#3", "B3"]), "Dm": ("D2", ["D3", "F3", "A3"]), "Em": ("E2", ["E3", "G3", "B3"]),
          "Bb": ("A#2", ["A#3", "D4", "F4"]), "C": ("C2", ["C3", "E3", "G3"]), "D": ("D2", ["D3", "F#3", "A3"]),
          "B": ("B1", ["B2", "D#3", "F#3"])}  # (the bass's root, the chord)
FIGHT_RUNS = {3: "G2 G3 G2 G3 G2 F2 E2 D2", 7: "E2 E3 E2 E3 G#2 B2 D3 E3", 11: "G2 G3 G2 G3 A2 B2 C3 D3",
              15: "E2 E3 E2 E3 E2 F#2 G#2 B2"}  # the bass's way into each next phrase, in eighths
FIGHT_TUNE = ("E5:1.5 D5:.5 C5 B4:.5 C5:.5  A4 E5 A5:1.5 G5:.5  F5:1.5 E5:.5 C5 A4  G4:.5 A4:.5 B4:.5 D5:.5 G5:2  "
              "E5:1.5 D5:.5 C5 B4:.5 C5:.5  A4 E5 C6:1.5 B5:.5  A5 F5 G5:.5 A5:.5 G5:.5 F5:.5  E5:2 G#5 B5  "
              "D5 F5 A5 G5:.5 F5:.5  E5 G5 B5:1.5 A5:.5  A5:1.5 G5:.5 F5 C6  B5:1.5 A5:.5 G5 D5  "
              "E5:3 C6:.5 B5:.5  A5:3 C6:.5 A5:.5  A#5:1.5 A5:.5 F5 D5  E5:.5 F5:.5 G#5:.5 B5:.5 E6:2")
STRINGS = [0, 1, 2, 3, 2, 1, 2, 1]  # the strings' way round the chord (its notes, and the root an octave up)


def _tune(text: str, beat: float, volume: float, duty: float, cutoff: float, body: str, body_volume: float,
          body_cutoff: float | None) -> list[Tone]:
    """A fight's tune: a pulse singing it, vibrato on its long notes only, and `body` under it an octave down."""
    tune = [replace(t, vibrato=0.0) if t.length < beat else t
            for t in _phrase(text, 0.0, beat, gap=0.94, duty=duty, volume=volume, release=0.06, vibrato=0.15,
                             vibrato_rate=6, cutoff=cutoff)]
    return tune + [replace(t, freq=t.freq / 2, wave=body, volume=body_volume, vibrato=0.0, cutoff=body_cutoff)
                   for t in tune]


def _fight_music() -> list[Tone]:
    tones: list[Tone] = []
    eighth = FIGHT_BEAT / 2
    for bar, chord in enumerate(FIGHT):
        start = bar * FIGHT_BAR
        root, triad = CHORDS[chord]
        bass = FIGHT_RUNS.get(bar) or " ".join([root, _octave(root)] * 4)
        tones += _phrase(bass, start, eighth, gap=0.8, wave="triangle", volume=0.28, release=0.03)
        tones += _phrase(bass, start, eighth, gap=0.6, duty=0.5, volume=0.07, release=0.03, cutoff=800)  # its growl
        ring = triad + [_octave(triad[0])]
        tones += [note(ring[STRINGS[i % 8]], eighth / 2 * 0.85, start + i * eighth / 2, wave="saw", volume=0.09,
                       release=0.03, cutoff=1800) for i in range(16)]
        for beat, length in ((0, 0.75), (1.5, 0.4), (3, 0.75)):  # the brass
            tones += _pad([_octave(n) for n in triad], start + beat * FIGHT_BEAT, length * FIGHT_BEAT, 0.04,
                          wave="square", duty=0.25, cutoff=1500, attack=0.01, release=0.08)
        if bar >= 8:  # the second half: the strings hold the chord under it all too
            tones += _pad(triad, start, FIGHT_BAR, 0.03, cutoff=1200, attack=0.1, release=0.3)
        fill = bar in (7, 15)
        for beat in (0, 1.5, 2):
            tones += _kick(start + beat * FIGHT_BEAT, 0.36)
        for beat in (1, 3) if not fill else (1,):
            tones += _snare(start + beat * FIGHT_BEAT, 0.22)
        if fill:  # a roll into the next phrase
            for k in range(4):
                tones += _snare(start + (3 + k / 4) * FIGHT_BEAT, 0.12 + 0.04 * k)
        for e in range(8):
            tones += _hat(start + e * eighth, 0.035 if e % 2 == 0 else 0.05)
    tones += _tune(FIGHT_TUNE, FIGHT_BEAT, 0.17, 0.25, 3200, "triangle", 0.1, None)
    return tones + _crash(0.0, 0.1) + _crash(8 * FIGHT_BAR, 0.1)


# A boss's music: heavier and darker, in E minor at 150: a galloping bass riff with a dark half-step in it, an organ
# grinding out power chords, drums pounding every beat and toms rolling into each phrase, and a slow, menacing tune
# that breaks into a run. 16 bars.
BOSS_BEAT = 0.4
BOSS_BAR = 4 * BOSS_BEAT
BOSS = ["Em", "Em", "C", "D", "Em", "Em", "C", "B", "Am", "Am", "Em", "Em", "F", "F", "B", "B"]
BOSS_RIFF = [0, 0, 0, 0, 0, 12, 0, 0, 0, 1, 0, 7]  # semitones over the root: each beat an eighth and two sixteenths
BOSS_TUNE = ("B4:3 C5  B4:2 G4 A4  G4:2 E4:2  F#4:2 A4 D5  E5:3 F5  E5:2 D5 B4  C5:2 E5 G5  F#5:2 D#5 B4  "
             "A5:1.5 G5:.5 E5 C5  B4:.5 C5:.5 E5:.5 A5:.5 C6:2  B5:1.5 A5:.5 G5 E5  F#5:.5 G5:.5 F#5:.5 E5:.5 B4:2  "
             "A5:1.5 G5:.5 F5 C5  C6:2 A5 F5  D#5 F#5 A5 B5  B5:.5 A5:.5 G5:.5 F#5:.5 E5:.5 D#5:.5 E5:.5 F#5:.5")


def _boss_music() -> list[Tone]:
    tones: list[Tone] = []
    for bar, chord in enumerate(BOSS):
        start = bar * BOSS_BAR
        root, triad = CHORDS[chord]
        for i, semitones in enumerate(BOSS_RIFF):  # the gallop
            beat, part = divmod(i, 3)
            at = start + (beat + (0, 0.5, 0.75)[part]) * BOSS_BEAT
            length = (0.5, 0.25, 0.25)[part] * BOSS_BEAT * 0.85
            pitch = hz(root) * 2 ** (semitones / 12)
            tones += [Tone("triangle", pitch, length=length, at=at, volume=0.24, release=0.02),
                      Tone("square", pitch, length=length, at=at, volume=0.1, release=0.02, cutoff=900)]
        for half in (0, 2):  # the organ, struck every two beats: root, fifth and octave
            tones += _pad([triad[0], triad[2], _octave(triad[0])], start + half * BOSS_BEAT, 2 * BOSS_BEAT, 0.055,
                          cutoff=1400, attack=0.02, release=0.25)
        if bar >= 8:  # and higher, the whole chord, from the second half
            tones += _pad([_octave(n) for n in triad], start, BOSS_BAR, 0.035, wave="square", duty=0.25, cutoff=1600,
                          attack=0.3, release=0.5)
        fill = bar in (7, 15)
        for beat in (0, 1) if fill else (0, 1, 2, 2.5, 3):
            tones += _kick(start + beat * BOSS_BEAT, 0.36 if beat == int(beat) else 0.28)
        tones += _snare(start + BOSS_BEAT, 0.24)
        if fill:  # toms rolling down into the next phrase
            for k, pitch in enumerate((220, 196, 165, 147, 131, 110, 98, 82)):
                tones += _tom(start + (2 + k / 4) * BOSS_BEAT, pitch, 0.3)
        else:
            tones += _snare(start + 3 * BOSS_BEAT, 0.24)
        for e in range(8):
            tones += _hat(start + e * BOSS_BEAT / 2, 0.04)
    tones += _tune(BOSS_TUNE, BOSS_BEAT, 0.17, 0.5, 3000, "saw", 0.08, 1300)  # (brass under it)
    return tones + _crash(0.0, 0.1) + _crash(8 * BOSS_BAR, 0.1)


# A sound that loops, and how long a loop is: what rings past it, folded back in
LOOPS = {"title_music": 16 * BAR, "explore_music": 16 * CRYPT_BAR, "deep_music": 12 * DEEP_BAR,
         "battle_music": 16 * FIGHT_BAR, "boss_music": 16 * BOSS_BAR}
LOUDNESS = {"explore_music": 0.12, "deep_music": 0.12, "battle_music": 0.16, "boss_music": 0.17}  # (RMS, of 1)


SOUNDS: dict[str, list[list[Tone]]] = {
    # the interface: small, quiet, out of the way
    "select": [[note("A5", 0.03, duty=0.25, volume=0.22), note("E6", 0.05, 0.03, duty=0.25, volume=0.22)]],
    "open": [[note("E5", 0.03, duty=0.125, volume=0.18), note("B5", 0.05, 0.03, duty=0.125, volume=0.18)]],
    "close": [[note("B5", 0.03, duty=0.125, volume=0.18), note("E5", 0.05, 0.03, duty=0.125, volume=0.18)]],

    # dice
    "dice_roll": [_rattle(_tumble_times(), seed=1), _rattle(_tumble_times(), seed=4, cutoff=2600)],
    "dice_small": [_rattle([0.0, 0.05, 0.11, 0.19], seed=2, volume=0.25),
                   _rattle([0.0, 0.06, 0.12, 0.21], seed=3, volume=0.25, cutoff=2400)],
    "dice_land": [[Tone("noise", 2500, length=0.05, volume=0.38, metallic=True, release=0.03),
                   Tone("square", 150, to=60, length=0.1, duty=0.5, volume=0.3)],
                  [Tone("noise", WHITE, length=0.06, volume=0.5, release=0.04, cutoff=1700, cutoff_to=500),
                   Tone("triangle", 150, to=60, length=0.11, volume=0.34, release=0.06, cutoff=700)]],
    "dice_tick": [[note("C6", 0.035, duty=0.25, volume=0.22)]],

    # how a roll went (ptg/outcome.py)
    "great": [arp(["C5", "E5", "G5", "C6"], 0.06, duty=0.5, volume=0.32)
              + [note("C6", 0.4, 0.24, duty=0.25, volume=0.3, vibrato=0.25, release=0.25),
                 note("E6", 0.4, 0.24, wave="triangle", volume=0.3, release=0.25)]],
    "good": [[note("G5", 0.07, duty=0.5, volume=0.42), note("C6", 0.2, 0.07, duty=0.5, volume=0.42, release=0.12)],
             [note("G5", 0.07, wave="triangle", volume=0.45, cutoff=3500),
              note("C6", 0.24, 0.07, wave="triangle", volume=0.45, release=0.16, cutoff=3500),
              note("C5", 0.24, 0.07, duty=0.5, volume=0.14, release=0.16, cutoff=1400)]],
    "neutral": [[note("E5", 0.1, wave="triangle", volume=0.4), note("E5", 0.16, 0.12, wave="triangle", volume=0.3,
                                                                      release=0.1)]],
    "bad": [[note("E4", 0.1, duty=0.5, volume=0.42), note("C4", 0.24, 0.1, duty=0.5, volume=0.42, release=0.14)],
            [note("E4", 0.1, duty=0.5, volume=0.5, cutoff=1100),
             note("C4", 0.28, 0.1, duty=0.5, volume=0.5, release=0.18, cutoff=800),
             note("C3", 0.28, 0.1, wave="triangle", volume=0.25, release=0.18)]],
    "awful": [[Tone("square", 330, to=82, length=0.7, duty=0.5, volume=0.3, vibrato=0.6, vibrato_rate=7,
                    release=0.2),
               Tone("noise", 300, length=0.2, at=0.55, volume=0.2)]],

    # fighting
    "hit": [_hit(260, 1), _hit(230, 2), _hit(290, 3), _thud(210, 5), _thud(175, 6, volume=0.55)],
    "crit_hit": [_hit(300, 4) + [note("E7", 0.18, 0.05, wave="triangle", volume=0.3, release=0.15),
                                 note("B6", 0.2, 0.09, duty=0.125, volume=0.15, release=0.15)],
                 _thud(230, 7, volume=0.6) + [note("E6", 0.24, 0.05, wave="triangle", volume=0.28, release=0.2,
                                                   cutoff=3000),
                                              note("B5", 0.26, 0.09, wave="triangle", volume=0.18, release=0.2,
                                                   cutoff=2400)]],
    "miss": [[Tone("noise", 9000, to=1500, length=0.17, volume=0.28, attack=0.04, release=0.08)],
             _whoosh(450, 2200, 0.2, 0.6), _whoosh(300, 1500, 0.24, 0.7)],
    "hurt": [[Tone("square", 280, to=70, length=0.18, duty=0.5, volume=0.35),
              Tone("noise", 2500, length=0.1, volume=0.3, metallic=True)],
             [Tone("triangle", 240, to=75, length=0.2, volume=0.42, release=0.1, cutoff=900),
              Tone("noise", WHITE, length=0.11, volume=0.55, release=0.08, cutoff=1100, cutoff_to=250)],
             [Tone("square", 220, to=60, length=0.2, duty=0.5, volume=0.34, release=0.1, cutoff=700),
              Tone("noise", WHITE, length=0.09, volume=0.55, release=0.07, cutoff=900, cutoff_to=200)]],
    "dodge": [[Tone("triangle", 300, to=1300, length=0.12, volume=0.4, release=0.05)],
              _whoosh(350, 1800, 0.16, 0.5) + [Tone("triangle", 260, to=750, length=0.12, volume=0.3, release=0.05,
                                                    cutoff=1600)]],
    "windup": [[Tone("square", 170, to=520, length=0.45, duty=0.125, volume=0.34, vibrato=0.5, vibrato_rate=13,
                     release=0.05)],
               [Tone("square", 130, to=400, length=0.5, duty=0.25, volume=0.42, vibrato=0.5, vibrato_rate=10,
                     release=0.06, cutoff=1100)]],
    "stun": [[note("A5", 0.5, wave="triangle", volume=0.35, vibrato=2.0, vibrato_rate=9, release=0.15),
              note("E6", 0.3, 0.15, duty=0.125, volume=0.12, vibrato=2.0, vibrato_rate=9, release=0.15)]],
    "kill": [[Tone("noise", 1500, to=150, length=0.4, volume=0.3, release=0.2)]
             + arp(["C5", "G4", "C4"], 0.07, duty=0.25, volume=0.25, hold=0.1),
             [Tone("noise", WHITE, length=0.45, volume=0.6, release=0.3, cutoff=1300, cutoff_to=120)]
             + arp(["A4", "E4", "A3"], 0.08, wave="triangle", volume=0.34, hold=0.14, cutoff=1600)],
    # a fight beginning (the foe sweeps onto the stage): a stab and a rising minor run, then the battle music
    "encounter": [[Tone("noise", WHITE, length=0.18, volume=0.5, release=0.14, cutoff=5200, cutoff_to=1600),
                   Tone("square", 98, to=49, length=0.2, duty=0.5, volume=0.3, release=0.12)]
                  + arp(["E4", "G4", "B4", "E5"], 0.045, at=0.04, duty=0.25, volume=0.3)
                  + [note("D#5", 0.32, 0.22, duty=0.125, volume=0.24, vibrato=0.35, vibrato_rate=9, release=0.2)],
                  [Tone("noise", WHITE, length=0.2, volume=0.55, release=0.16, cutoff=2400, cutoff_to=600),
                   Tone("triangle", 110, to=52, length=0.22, volume=0.42, release=0.14, cutoff=800)]
                  + arp(["E4", "G4", "B4", "E5"], 0.05, at=0.04, wave="triangle", volume=0.36, cutoff=3000)
                  + [note("D#5", 0.36, 0.24, duty=0.25, volume=0.22, vibrato=0.3, vibrato_rate=8, release=0.24,
                          cutoff=2200)]],
    # a boss's: toms rolling in, a falling tritone over a boom, the crash
    "boss_encounter": [_tom(0.0, 140, 0.45) + _tom(0.09, 120, 0.45) + _tom(0.18, 100, 0.5) + _boom(0.45, 1200, 0.3, 1.2)
                       + [note("A#4", 0.5, 0.3, duty=0.25, volume=0.3, vibrato=0.3, release=0.3),
                          note("E4", 0.7, 0.3, duty=0.5, volume=0.26, vibrato=0.3, release=0.45),
                          note("E3", 0.8, 0.3, wave="triangle", volume=0.4, release=0.5)]
                       + _crash(0.3, 0.3)],
    # a foe breaking apart: glass, then its bits tinkling down
    "shatter": [[Tone("noise", 6500, length=0.12, volume=0.4, metallic=True, release=0.1),
                 Tone("noise", WHITE, length=0.4, volume=0.35, release=0.3, cutoff=7000, cutoff_to=2500)]
                + _sparkle(["E7", "B6", "G6", "E6", "B5"], 0.045, volume=0.22, at=0.08)],
    # something rare drops: a bright run up, and a glitter on top
    "rare_drop": [arp(["C6", "E6", "G6", "C7"], 0.05, duty=0.25, volume=0.3)
                  + _sparkle(["G7", "E7", "C7"], 0.05, volume=0.2, at=0.2)
                  + [note("C7", 0.5, 0.2, wave="triangle", volume=0.26, vibrato=0.2, release=0.4)]],
    "bomb": [[Tone("noise", 4000, length=0.06, volume=0.35),
              Tone("noise", 1100, to=40, length=0.7, volume=0.45, release=0.45),
              Tone("square", 110, to=28, length=0.45, duty=0.5, volume=0.3, release=0.3)],
             [Tone("noise", WHITE, length=0.05, volume=0.35, release=0.04, cutoff=2200)] + _boom(0.4, 1500, length=0.9)],

    # exploring
    "step": [[Tone("noise", 800, length=0.035, volume=0.22), Tone("noise", 650, length=0.035, at=0.16, volume=0.18)],
             [Tone("noise", 700, length=0.035, volume=0.22), Tone("noise", 850, length=0.035, at=0.15, volume=0.18)],
             [Tone("noise", WHITE, length=0.05, volume=0.42, release=0.04, cutoff=650),
              Tone("noise", WHITE, length=0.05, at=0.17, volume=0.36, release=0.04, cutoff=550)],
             [Tone("noise", WHITE, length=0.05, volume=0.4, release=0.04, cutoff=500),
              Tone("triangle", 90, to=60, length=0.04, volume=0.12),
              Tone("noise", WHITE, length=0.05, at=0.15, volume=0.36, release=0.04, cutoff=700)]],
    "locked": [[Tone("square", 98, length=0.06, volume=0.35), Tone("square", 92, length=0.09, at=0.09, volume=0.35)],
               [Tone("noise", WHITE, length=0.05, volume=0.6, release=0.03, cutoff=900),
                Tone("triangle", 110, length=0.06, volume=0.35, cutoff=600),
                Tone("noise", WHITE, length=0.06, at=0.09, volume=0.6, release=0.04, cutoff=800),
                Tone("triangle", 100, length=0.08, at=0.09, volume=0.35, cutoff=600)]],
    "unlock": [[Tone("noise", 5000, length=0.02, volume=0.3, metallic=True),
                note("C5", 0.05, 0.04, duty=0.25, volume=0.28), note("G5", 0.12, 0.09, duty=0.25, volume=0.28)]],
    "item": [arp(["C6", "E6", "G6"], 0.045, wave="triangle", volume=0.38, hold=0.06),
             arp(["A5", "C#6", "E6"], 0.05, wave="triangle", volume=0.4, hold=0.08, cutoff=3200)],
    "coin": [[note("B5", 0.07, duty=0.5, volume=0.34), note("E6", 0.3, 0.07, duty=0.5, volume=0.34, release=0.25)],
             [note("A5", 0.07, duty=0.5, volume=0.4, cutoff=2600),
              note("D6", 0.32, 0.07, duty=0.5, volume=0.4, release=0.27, cutoff=2600)],
             [note("B5", 0.07, wave="triangle", volume=0.42, cutoff=4000),
              note("E6", 0.34, 0.07, wave="triangle", volume=0.42, release=0.3, cutoff=4000)]],
    "heal": [arp(["C5", "E5", "G5", "C6", "E6"], 0.06, wave="triangle", volume=0.38, attack=0.01, hold=0.15),
             arp(["D5", "F#5", "A5", "D6", "F#6"], 0.06, wave="triangle", volume=0.4, attack=0.01, hold=0.15,
                 cutoff=3000)],
    "secret": [_sparkle(["A6", "E6", "C#6", "A5", "E6", "A6"], 0.06)],
    # a floor's secret room: two rising runs a step apart, then a bright chord that rings and glitters
    "secret_room": [arp(["G5", "B5", "D6", "G6"], 0.055, duty=0.25, volume=0.3)
                    + arp(["A5", "C#6", "E6", "A6"], 0.055, at=0.24, duty=0.25, volume=0.3)
                    + [note("B6", 0.8, 0.48, duty=0.5, volume=0.24, vibrato=0.25, release=0.5),
                       note("D#6", 0.8, 0.48, wave="triangle", volume=0.3, release=0.5),
                       note("B4", 0.8, 0.48, wave="triangle", volume=0.3, release=0.5)]
                    + _sparkle(["F#7", "D#7", "B6", "F#7", "B7"], 0.07, volume=0.14, at=0.62)],
    # a shop: a coin's chime, then a merry run up and a little bow
    "shop": [[note("B5", 0.06, duty=0.5, volume=0.3), note("E6", 0.16, 0.06, duty=0.5, volume=0.3, release=0.12)]
             + arp(["C6", "E6", "G6", "E6", "C7"], 0.055, at=0.26, wave="triangle", volume=0.32, hold=0.18)],
    # the rare shop: the same, then a long shimmer climbing out of it
    "shop_shiny": [[note("B5", 0.06, duty=0.5, volume=0.3), note("E6", 0.16, 0.06, duty=0.5, volume=0.3,
                                                                   release=0.12)]
                   + arp(["C6", "E6", "G6", "E6", "C7"], 0.055, at=0.26, wave="triangle", volume=0.32, hold=0.18)
                   + _sparkle(["G6", "C7", "E7", "G7", "C8", "G7", "C8"], 0.07, volume=0.16, at=0.62)],
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
    # the title screen
    "thunder": [_thunder(1, distance=0.0), _thunder(2, distance=0.4), _thunder(3, distance=0.9)],  # close, near, far
    "title_music": [_title_music()],

    # down there (ui/game_screen.py: the floor's, then a fight's while a monster's after you)
    "explore_music": [_explore_music()],
    "deep_music": [_deep_music()],
    "battle_music": [_fight_music()],
    "boss_music": [_boss_music()],

    "victory": [arp(["G4", "C5", "E5", "G5"], 0.1, duty=0.5, volume=0.3)
                + arp(["E5", "G5"], 0.1, at=0.45, duty=0.5, volume=0.3)
                + [note("C6", 0.8, 0.65, duty=0.5, volume=0.3, vibrato=0.25, release=0.4),
                   note("C4", 0.8, 0.65, wave="triangle", volume=0.4, release=0.4)]],
}


def files_for(name: str) -> list[str]:
    return [f"{name}.wav" if i == 0 else f"{name}_{i + 1}.wav" for i in range(len(SOUNDS[name]))]


def soft(variant: list[Tone]) -> bool:
    """Whether a sound's softened (a filtered tone in it): written 16-bit, and played smoothly resampled."""
    return any(tone.cutoff for tone in variant)


def build(names: list[str] | None = None) -> list[Path]:
    OUT.mkdir(parents=True, exist_ok=True)
    written = []
    for name in names or SOUNDS:
        for stale in OUT.glob(f"{name}_*.wav"):  # (a variant that's gone mustn't linger and still play)
            if re.fullmatch(rf"{name}_\d+", stale.stem) and stale.name not in files_for(name):
                stale.unlink()
        for variant, filename in zip(SOUNDS[name], files_for(name)):
            path = OUT / filename
            if name in LOOPS:  # music: 16-bit, folded to loop, and levelled
                samples = fold(_sum(variant), LOOPS[name])
                write(path, render16(level(samples, LOUDNESS[name]) if name in LOUDNESS else samples), width=2)
            elif soft(variant):
                write(path, render16(mix(variant)), width=2)
            else:
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
