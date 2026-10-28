import asyncio
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


MUSIC = {"title_music": 21.0, "explore_music": 46.0, "deep_music": 40.0, "battle_music": 25.0, "boss_music": 26.0}


def test_built_in_sounds_are_small_files():
    """8-bit, or 16-bit for music, thunder and the softened sounds (their fades and quiet tails would grind or hiss in
    8); every fighting sound has a softer variant among its bright ones."""
    bank, _ = load_bank()
    for clips in bank.values():
        for clip in clips:
            with clip.source.open("rb") as f, wave.open(f) as w:
                assert (w.getnchannels(), w.getframerate()) == (1, 22050), clip.source.name
                assert w.getsampwidth() == 2 if clip.moment in MUSIC or clip.moment == "thunder" else \
                    w.getsampwidth() in (1, 2), clip.source.name
                longest = MUSIC.get(clip.moment, 5.0 if clip.moment == "thunder" else 2.0)  # (a loop; a rumble)
                assert w.getnframes() / w.getframerate() < longest, clip.source.name
    for moment in ("hit", "crit_hit", "miss", "hurt", "dodge", "kill", "bomb", "step"):
        assert {sound.sample_width(c.source) for c in bank[moment]} == {1, 2}, moment


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

    mixer = quiet_mixer({"x": array("h", [1000] * 300)})
    clip = Clip("title_music", "x")
    mixer.loop(clip, 1.0)
    first = array("h", mixer._mix())
    assert len(first) == Mixer.BLOCK and set(first) == {1000} and mixer.music[1] == Mixer.BLOCK % 300  # (wrapped)
    mixer.stop_loop(fade=0.05)
    for _ in range(10):
        mixer._mix()
    assert mixer.music is None and mixer._mix() is None


def quiet_mixer(cache: dict) -> "sound.Mixer":
    """A Mixer without speakers: just its mixing."""
    from ptg.sound import Mixer

    mixer = Mixer.__new__(Mixer)
    mixer.rate, mixer.voices, mixer.music, mixer.leaving, mixer.lock = 22050, [], None, [], threading.Lock()
    mixer.cache, mixer.wake, mixer.wanted = cache, threading.Event(), ""
    return mixer


def test_the_mixer_crossfades_one_music_into_the_next():
    """Music taking over from other music comes in over its fade while the old fades out under it; the same music
    asked for again just carries on."""
    from ptg.sound import Clip

    mixer = quiet_mixer({"a": array("h", [1000] * 600), "b": array("h", [-1000] * 600)})
    mixer.loop(Clip("explore_music", "a"), 1.0)
    mixer._mix()
    mixer.loop(Clip("battle_music", "b"), 1.0, fade_in=0.1, fade_out=0.05)
    first = array("h", mixer._mix())
    assert mixer.leaving and 0 < mixer.music[2] < 1.0 and first[0] > -1000  # (both playing, the new one rising)
    for _ in range(10):
        last = array("h", mixer._mix())
    assert not mixer.leaving and mixer.music[2] == 1.0 and set(last) == {-1000}
    mixer.loop(Clip("battle_music", "b"), 0.5)
    assert mixer.music[0] is mixer.cache["b"] and mixer.music[2] == 0.5 and not mixer.leaving
    mixer.stop_loop(0.05)
    for _ in range(5):
        mixer._mix()
    assert mixer.music is None and mixer._mix() is None


def test_music_from_a_screen_going_only_stops_its_own(speakers):
    """The title's suspend and the game's unmount can land after the next screen's music has started: they stop only
    their own."""
    sound.music("explore_music")
    sound.stop_music(only=("title_music",))
    assert speakers.looping == "explore_music"
    sound.stop_music(only=("explore_music", "battle_music"))
    assert speakers.looping == "" and not sound.engine().wanted


def test_16_bit_sounds_play_smoothly_and_8_bit_ones_keep_their_crunch(tmp_path):
    from ptg.sound import Clip

    ramp = array("h", [0, 1000, 2000, 3000])
    with wave.open(str(tmp_path / "soft.wav"), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(11025)
        w.writeframes(ramp.tobytes())
    mixer = quiet_mixer({})
    soft = mixer._samples(Clip("hit", tmp_path / "soft.wav"))
    crunchy = mixer._samples(Clip("hit", wav(tmp_path / "crunchy.wav", bytes([128, 136, 144, 152]))))
    assert list(soft)[:4] == [0, 500, 1000, 1500] and list(crunchy)[:4] == [0, 0, 2048, 2048]


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


async def test_served_the_sound_plays_in_the_browser_not_on_the_server(monkeypatch, tmp_path):
    """Under ptg serve (PTG_SOUND=web) the server's own speakers never open: each sound is a message for the page,
    through the web driver (its write_meta), with how loud and, for music, its fades. Only the built-in sounds, which
    the page can load; a player's own music stops whatever was playing rather than leave it on in its place."""
    from ptg.sound import Browser, Clip

    monkeypatch.setenv("PTG_SOUND", "web")
    monkeypatch.setattr(sound, "_sound", Sound(False))
    assert sound.in_browser() and sound.open_player() is None and Sound(True, 0.5).enabled
    sent = []
    sound.to_browser(sent.append)
    engine = sound.configure(True, 0.5)
    assert isinstance(engine.player, Browser) and isinstance(sound.configure(True, 0.5).player, Browser)
    assert sound.play("coin", variant=1) and sound.music("title_music", fade_in=1.0)
    sound.stop_music(0.3)
    assert sent == [
        {"type": "ptg_sound", "do": "play", "file": "coin_2.wav", "gain": 0.5},
        {"type": "ptg_sound", "do": "loop", "file": "title_music.wav", "gain": 0.3, "fade_in": 1.0, "fade_out": 0.8},
        {"type": "ptg_sound", "do": "stop", "fade": 0.3},
    ]
    sent.clear()
    yours = Clip("explore_music", wav(tmp_path / "explore_music.wav"), builtin=False)
    engine.player.play(Clip("coin", yours.source, builtin=False), 0.5)
    engine.player.loop(yours, 0.3, fade_out=1.5)
    assert sent == [{"type": "ptg_sound", "do": "stop", "fade": 1.5}]


async def test_a_sound_from_another_thread_waits_for_the_games_own():
    """The debug screen plays sounds from a thread of its own: its message is written on the game's thread, where
    the driver writes the screen, or it could land in the middle of the screen's writing."""
    from ptg.sound import Browser

    sent = []
    browser = Browser(lambda message: sent.append((message["file"], threading.get_ident())))
    thread = threading.Thread(target=browser.play, args=(sound.engine().bank["coin"][0], 0.5))
    thread.start()
    thread.join()
    assert sent == []
    await asyncio.sleep(0)
    assert sent == [("coin.wav", threading.get_ident())]
