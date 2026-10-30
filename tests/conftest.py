from __future__ import annotations

import pytest

from ptg.content import load_content
from ptg.llm.base import LLMError
from ptg.models import MonsterState
from ptg.profile import Profile


@pytest.fixture(autouse=True)
def no_found_cards(request, monkeypatch):
    """The card a thing has the first time it's yours (ui/model_view.py FoundScreen) would pop up over whatever a UI
    test is looking at, in a profile where everything's new: none, unless a test asks for them (found_cards)."""
    if "found_cards" not in request.fixturenames:
        from ptg.game import Game

        monkeypatch.setattr(Game, "first_finds", lambda self, events: [])
        monkeypatch.setattr(Game, "first_statuses", lambda self, events: [])  # (a status's first card, likewise)


@pytest.fixture
def found_cards():
    """A thing's first card, as in play (see no_found_cards)."""


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Keep config, saves, the profile database and logs out of the real ~/.ptg, and the tests quiet."""
    monkeypatch.setenv("PTG_HOME", str(tmp_path))
    monkeypatch.setenv("PTG_SOUND", "0")
    monkeypatch.setenv("PTG_BIG_INTRO", "0")  # (a boss's big entrance over everything: a test that wants it says so)
    monkeypatch.setenv("PTG_GC", "0")  # (the collector as Python has it: hundreds of games start in one process)
    monkeypatch.setenv("PTG_FIGHT_PAUSES", "0")  # (the beat before the foes' goes, the spoils held up: likewise)
    return tmp_path


class Recorder:
    """Stands in for the speakers: remembers what was played, and how loud."""

    name = "recorder"

    def __init__(self) -> None:
        self.played: list[tuple[str, float]] = []
        self.looping: str = ""  # the music playing, if any

    def play(self, clip, gain: float) -> None:
        self.played.append((clip.moment, round(gain, 3)))

    def loop(self, clip, gain: float, fade_in: float = 0.0, fade_out: float = 0.0) -> None:
        self.looping = clip.moment

    def stop_loop(self, fade: float = 0.0) -> None:
        self.looping = ""

    def close(self) -> None:
        pass

    @property
    def moments(self) -> list[str]:
        return [moment for moment, _ in self.played]


@pytest.fixture
def speakers(monkeypatch):
    """Sound on, played into a Recorder."""
    from ptg import sound

    monkeypatch.delenv("PTG_SOUND", raising=False)
    recorder = Recorder()
    monkeypatch.setattr(sound, "_sound", sound.Sound(True, 0.5, player=recorder))
    return recorder


@pytest.fixture
def content():
    return load_content()


@pytest.fixture
def profile():
    p = Profile.open()
    yield p
    p.close()


def put_monster(state, content, key="goblin", hp=None, intent="strike"):
    monster = content.monster(key)
    state.room.monster = MonsterState(key=key, name=monster.name, hp=hp or monster.hp, max_hp=monster.hp, intent=intent)
    return state.room.monster


class FakeLLM:
    """Stands in for a model: returns a canned JSON reply and streams canned narration."""

    name = "fake"

    def __init__(self, reply: dict | None = None, text: str = "Something happens.", fail: bool = False):
        self.reply = reply or {}
        self.text = text
        self.fail = fail
        self.json_calls = 0

    async def prepare(self) -> None:
        pass

    async def complete_json(self, system, user, schema, max_tokens=500):
        self.json_calls += 1
        if self.fail:
            raise LLMError("model is down")
        return self.reply

    async def stream_text(self, system, user, max_tokens=600):
        if self.fail:
            raise LLMError("model is down")
        for word in self.text.split(" "):
            yield word + " "

    async def aclose(self) -> None:
        pass


@pytest.fixture
def fake_llm():
    return FakeLLM
