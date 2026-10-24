"""The DOS/CRT look: a phosphor palette and the styles for map glyphs."""

from __future__ import annotations

from textual.theme import Theme

CRT = Theme(
    name="crt",
    primary="#6c8cff",
    secondary="#ffb000",
    accent="#ff4f9a",
    foreground="#e8e8f4",
    background="#090a13",
    surface="#10122a",
    panel="#171a38",
    success="#4cff8a",
    warning="#ffd166",
    error="#ff4b4b",
    dark=True,
)

CELL_STYLES = {
    "wall": "#3d4fb8",
    "floor": "#23274a",
    "door": "#8a8fb8",
    "locked": "bold #ffb000",
    "water": "#3fa7ff",
    "pillar": "#9aa0c8",
    "bones": "#c8c8d8",
    "rubble": "#7d7d99",
    "furniture": "#b0844f",
    "cage": "#a6aaba",
    "junk": "#a8946a",
    "plant": "#4cbf6a",
    "fire": "#ff7b2e",
    "feature": "bold #ffb000",
    "feature_used": "#6b5a2a",
    "item": "bold #4cff8a",
    "monster": "bold #ff4b4b",
    "boss": "bold reverse #ff4b4b",
    "calm": "bold #ffd166",
    "player": "bold #ffffff",
    "fixture": "bold #ff4f9a",
    "fixture_used": "#5a3a4a",
}

PERK_COLORS = {"red": "#ff4b4b", "green": "#4cff8a", "cyan": "#5fe3ff", "magenta": "#ff4f9a",
               "yellow": "#ffd166", "blue": "#6c8cff", "white": "#e8e8f4"}

MAP_STYLES = {"@": "bold #ffffff", "!": "bold #ff4b4b", "?": "#6c6f99", "#": "#6c8cff", "B": "bold reverse #ff4b4b",
              ">": "bold #ff4f9a", "†": "bold #ff4f9a", "■": "bold #ff4f9a", "◊": "bold #ff4f9a", "=": "bold #ffb000",
              "{": "bold #ffd166", "}": "bold #ffd166", "✧": "bold #ffd166", "$": "bold #ffd166",  # secrets: gold
              "¤": "bold #4cff8a"}  # a shop
