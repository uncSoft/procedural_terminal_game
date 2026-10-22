from __future__ import annotations

import pytest

from ptg.content import load_content
from ptg.llm.base import LLMError


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Keep config, saves and logs out of the real ~/.ptg."""
    monkeypatch.setenv("PTG_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def content():
    return load_content()


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
