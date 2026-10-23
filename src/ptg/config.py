"""User settings and save files live in ~/.ptg (override with PTG_HOME), never in the repo."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from .models import GameState

Backend = Literal["openai", "anthropic", "offline"]

DEFAULT_URLS = {"lmstudio": "http://localhost:1234/v1", "ollama": "http://localhost:11434/v1"}
DEFAULT_CLAUDE_MODEL = "claude-opus-5-5"


class Config(BaseModel):
    player_name: str = "Adventurer"
    backend: Backend = "openai"
    url: str = DEFAULT_URLS["lmstudio"]
    model: str = ""
    api_key: str = ""
    temperature: float = 0.8
    auto_roll: bool = False
    art: Literal["sprites", "ascii"] = "sprites"
    sound: bool = True
    volume: int = 70  # percent
    tone: str = "darkly funny, vivid and fair, like a game master who loves the players"


def home() -> Path:
    path = Path(os.environ.get("PTG_HOME", Path.home() / ".ptg"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_config() -> Config | None:
    path = home() / "config.json"
    if not path.exists():
        return None
    try:
        return Config.model_validate_json(path.read_text(encoding="utf-8"))
    except ValueError:
        return None


def save_config(config: Config) -> None:
    (home() / "config.json").write_text(config.model_dump_json(indent=2), encoding="utf-8")


def save_path(slot: str = "autosave") -> Path:
    saves = home() / "saves"
    saves.mkdir(exist_ok=True)
    return saves / f"{slot}.json"


def save_game(state: GameState, slot: str = "autosave") -> Path:
    path = save_path(slot)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(state.model_dump_json(), encoding="utf-8")
    tmp.replace(path)
    return path


def load_game(slot: str = "autosave") -> GameState | None:
    path = save_path(slot)
    if not path.exists():
        return None
    try:
        state = GameState.model_validate_json(path.read_text(encoding="utf-8"))
    except ValueError:
        return None
    if state.over or state.version < GameState.model_fields["version"].default:
        return None  # finished, or saved by an older version of the game
    return state


def log_path() -> Path:
    return home() / "llm.log"
