"""User settings and save files live in ~/.ptg (override with PTG_HOME), never in the repo."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from .models import GameState

Backend = Literal["openai", "anthropic", "offline"]

# Apple Intelligence's on-device model, through apfel (brew install apfel; apfel --serve), an OpenAI-compatible server
# on Ollama's port: written 127.0.0.1 so Settings can tell the two apart by their URL.
DEFAULT_URLS = {"lmstudio": "http://localhost:1234/v1", "ollama": "http://localhost:11434/v1",
                "apple": "http://127.0.0.1:11434/v1"}
APPLE_HELP = "Needs macOS 26 or later with Apple Intelligence on, and apfel: brew install apfel, then apfel --serve"
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
    layout: Literal["tabs", "grid", "classic"] = "tabs"  # the game screen: tabs beside the story (ui/tabs.py), a
    # fixed grid with big buttons (ui/grid.py), or the classic
    sound: bool = True
    volume: int = 70  # percent
    boss_intros: bool = True  # a boss (or a guardian) comes in big over the whole screen first (ui/boss_intro.py)
    tone: str = "darkly funny, vivid and fair, like a game master who loves the players"


def hosted() -> bool:
    """Played from a server several people share (`ptg serve` sets PTG_HOSTED=1): the narrator is the server's to
    choose, and the debug screen, which shows the model log and can point the server elsewhere, is off."""
    return os.environ.get("PTG_HOSTED") == "1"


def touch() -> bool:
    """Played with a finger (`ptg serve`'s page sets PTG_TOUCH=1 when the browser's pointer is a touch screen):
    things to tap want to be bigger. It follows the input, not the size: a phone turned sideways is still a finger,
    and a small window on a laptop is still a mouse."""
    return os.environ.get("PTG_TOUCH") == "1"


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


def read_save(slot: str = "autosave") -> tuple[GameState | None, str]:
    """The run in progress saved in `slot`, if there is one. If there's one that can't be continued, why not (to
    say so, not just grey out Continue); a finished run needs no reason."""
    path = save_path(slot)
    if not path.exists():
        return None, ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("not a saved game")
        if data.get("status", "playing") != "playing":
            return None, ""
        if data.get("version", 0) < GameState.model_fields["version"].default:
            return None, "an older version of the game saved it"
        return GameState.model_validate(data), ""
    except ValueError:
        return None, "its save is damaged"


def load_game(slot: str = "autosave") -> GameState | None:
    return read_save(slot)[0]


def log_path() -> Path:
    return home() / "llm.log"
