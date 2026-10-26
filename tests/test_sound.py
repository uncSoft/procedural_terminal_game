import builtins
import sys
import threading
import wave
from array import array

from conftest import Recorder
from ptg import sound
from ptg.sound import MOMENTS, Sound, decode, load_bank, resample


def wav(path, frames: bytes = bytes([128, 200, 56, 128]), channels: int = 1, rate: int = 11025):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(1)
        w.setframerate(rate)
        w.writeframes(frames)
    return path


def test_every_moment_has_a_built_in_sound():
    bank, problems = load_bank()
    assert set(MOMENTS) == set(bank) and not problems
    assert all(clip.builtin and clip.license == "CC0" for clips in bank.values() for clip in clips)


def test_built_in_sounds_are_small_8_bit_files():
    bank, _ = load_bank()
    for clips in bank.values():
        for clip in clips:
            with clip.source.open("rb") as f, wave.open(f) as w:
                width = 2 if clip.moment == "title_music" else 1  # (music is 16-bit: its fades would grind in 8)
                assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, width, 22050), clip.source.name
                longest = {"thunder": 4.0, "title_music": 21.0}.get(clip.moment, 2.0)  # (a rumble; a loop)
                assert w.getnframes() / w.getframerate() < longest, clip.source.name


def test_decoding_and_resampling(tmp_path):
    samples, rate = decode(wav(tmp_path / "x.wav", bytes([128, 128, 255, 255, 0, 0]), channels=2))
    assert rate == 11025 and list(samples) == [0, 127 << 8, -128 << 8]  # stereo mixed down, 8-bit made 16-bit
    assert len(resample(samples, 11025, 44100)) == 12 and resample(samples, 11025, 11025) is samples


def test_your_sounds_replace_the_built_in_ones(tmp_path):
    for name in ("great.wav", "great_2.wav", "fanfare.wav", "bogus.wav"):
        wav(tmp_path / name)
    (tmp_path / "sounds.toml").write_text(
        '[coin]\nfiles = ["fanfare.wav"]\nvolume = 0.5\ncredit = "Jane Doe"\nlicense = "CC0"\n\n'
        '[hit]\nvolume = 0.25\n\n[kill]\nfiles = ["missing.wav"]\n')
    bank, problems = load_bank(tmp_path)
    assert [c.source.name for c in bank["great"]] == ["great.wav", "great_2.wav"]
    assert not bank["great"][0].builtin
    coin = bank["coin"][0]
    assert (coin.source.name, coin.volume, coin.credit, coin.license) == ("fanfare.wav", 0.5, "Jane Doe", "CC0")
    assert all(c.builtin and c.volume == 0.25 for c in bank["hit"])  # turned down, still the built-in sound
    assert bank["kill"][0].builtin  # a missing file leaves the built-in sound in place
    assert any("missing.wav" in p for p in problems)
    assert any(p.startswith("bogus:") for p in problems) and not any(p.startswith("fanfare:") for p in problems)


def test_playing_respects_the_switches(speakers, monkeypatch):
    assert sound.play("coin") and speakers.played == [("coin", 0.5)]
    assert not sound.play("coin")  # the same moment twice at once plays once
    assert not sound.play("no_such_moment")
    sound.engine().enabled = False
    assert not sound.play("hit")
    monkeypatch.setenv("PTG_SOUND", "0")
    assert not Sound(True, 1.0, player=Recorder()).play("coin")


def test_without_sounddevice_the_system_player_steps_in(monkeypatch):
    real_import = builtins.__import__

    def no_portaudio(name, *args, **kwargs):
        if name == "sounddevice":
            raise OSError("PortAudio library not found")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_portaudio)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(sound.shutil, "which", lambda name: f"/usr/bin/{name}" if name == "aplay" else None)
    player = sound.open_player()
    assert player.name == "aplay" and player.argv("x.wav", 0.5) == ["aplay", "-q", "x.wav"]
    monkeypatch.setattr(sound.shutil, "which", lambda name: None)
    assert sound.open_player() is None  # and then the game is just quiet


def test_music_loops_until_stopped_and_waits_out_sound_being_off(speakers):
    """The title's music: looped by the player, stopped with a fade; switched off in Settings (or F8) it stops,
    and switched on again while it's still wanted, it plays again."""
    assert sound.music("title_music") and speakers.looping == "title_music"
    sound.stop_music()
    assert speakers.looping == "" and not sound.engine().wanted
    sound.music("title_music")
    sound.configure(False, 0.5)
    assert speakers.looping == "" and sound.engine().wanted == "title_music"
    sound.configure(True, 0.5)
    assert speakers.looping == "title_music"


def test_the_mixer_loops_music_and_fades_it_out():
    """The mixer's music voice wraps around its samples, and fades to nothing when stopped (then the stream may
    sleep)."""
    from ptg.sound import Clip, Mixer

    mixer = Mixer.__new__(Mixer)  # (no speakers here: just its mixing)
    mixer.rate, mixer.voices, mixer.music, mixer.lock, mixer.wanted = 22050, [], None, threading.Lock(), ""
    mixer.cache, mixer.wake = {"x": array("h", [1000] * 300)}, threading.Event()
    clip = Clip("title_music", "x")
    mixer.loop(clip, 1.0)
    first = array("h", mixer._mix())
    assert len(first) == Mixer.BLOCK and set(first) == {1000} and mixer.music[1] == Mixer.BLOCK % 300  # (wrapped)
    mixer.stop_loop(fade=0.05)
    for _ in range(10):
        mixer._mix()
    assert mixer.music is None and mixer._mix() is None


def test_loud_moments_are_squeezed_not_clipped_and_music_resamples_smoothly():
    """Thunder over the music went past the loudest a sample can be, and crackled: over LIMIT, a mix is squeezed
    into what's left. Music is resampled between neighbouring samples (held, a long pure tone warbles)."""
    from ptg.sound import Mixer

    mixer = Mixer.__new__(Mixer)
    assert mixer._squeeze(Mixer.LIMIT + 1) <= 32767 and mixer._squeeze(10 ** 6) <= 32767
    assert mixer._squeeze(-(10 ** 6)) >= -32767 and mixer._squeeze(40000) > mixer._squeeze(30000) > Mixer.LIMIT
    ramp = array("h", [0, 1000, 2000, 3000])
    assert list(resample(ramp, 2, 4, smooth=True))[:6] == [0, 500, 1000, 1500, 2000, 2500]
    assert list(resample(ramp, 2, 4))[:4] == [0, 0, 1000, 1000]  # (the effects keep their crunch)
