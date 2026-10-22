"""Game feel: what you see when a roll lands, coloured by how it went for you (see ptg.outcome).

    badge     the roll's line ends in a coloured pill: ✔ HIT, ✘ MISS, • NOTHING, ★ CRITICAL!, ✖ FUMBLE
    flash     the line lights up in that colour and fades
    pulse     a panel's border lights up for a moment (and blinks for a natural 20 or 1)
    popup     a number or word drifts away from where it happened: damage off the monster, HP by your hearts
"""

from __future__ import annotations

from rich.text import Text
from textual.color import Color
from textual.css.scalar import ScalarOffset
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Static

from ..outcome import AWFUL, BAD, GOOD, GREAT, NEUTRAL, TONES

COLORS = {GREAT: "#ffd166", GOOD: "#4cff8a", NEUTRAL: "#c8c8e0", BAD: "#ff4b4b", AWFUL: "#ff2a6d"}
ICONS = {GREAT: "★", GOOD: "✔", NEUTRAL: "•", BAD: "✘", AWFUL: "✖"}
INK = "#10122a"


def rgb(tone: str) -> tuple[int, int, int]:
    """A tone's colour as an RGB tuple (for pixel art)."""
    color = Color.parse(COLORS[tone])
    return color.r, color.g, color.b


def badge(tone: str, word: str) -> Text:
    return Text(f" {ICONS[tone]} {word} ", style=f"bold {INK} on {COLORS[tone]}")


def flash(widget: Widget, tone: str, strength: float = 0.3, duration: float = 0.9) -> None:
    """Light the widget's background in the tone's colour, fading back to nothing."""
    start = Color.parse(COLORS[tone]).with_alpha(strength)
    widget.styles.background = start
    widget.styles.animate("background", start.with_alpha(0), duration=duration, easing="out_cubic")


def pulse(widget: Widget, tone: str, blinks: int = 1, on: float = 0.5, off: float = 0.12) -> None:
    """Light the widget's border in the tone's colour for a moment, blinking `blinks` times. A newer pulse on
    the same widget takes over from an older one."""
    token = object()
    widget._ptg_pulse = token  # type: ignore[attr-defined]
    widget.remove_class(*(f"tone-{t}" for t in TONES))

    def step(i: int) -> None:
        if getattr(widget, "_ptg_pulse", None) is not token:
            return
        lit = i % 2 == 0 and i < blinks * 2
        widget.set_class(lit, f"tone-{tone}")
        if i < blinks * 2:
            widget.set_timer(on if lit else off, lambda: step(i + 1))

    step(0)


class Popup(Static):
    """A number or word that drifts away from where something happened, and fades."""

    DEFAULT_CSS = """
    Popup {
        position: absolute;
        overlay: screen;
        width: auto;
        height: 1;
    }
    """


async def popup(screen: Screen, text: str, style: str, x: int, y: int, dx: int = 0, dy: int = -3,
                duration: float = 1.0) -> Popup:
    """Float `text` from (x, y) on the screen by (dx, dy), dimming near the end, then gone. (No opacity fade:
    in a terminal a fading widget turns into a blank patch over whatever is under it.)"""
    widget = Popup(Text(text, style=style))
    widget.styles.offset = (x, y)
    await screen.mount(widget)
    widget.styles.animate("offset", ScalarOffset.from_offset((x + dx, y + dy)), duration=duration,
                          easing="out_cubic", on_complete=widget.remove)
    widget.set_timer(duration * 0.65, lambda: widget.update(Text(text, style=f"{style} dim")))
    return widget
