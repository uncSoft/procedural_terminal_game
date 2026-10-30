"""Game feel: what you see when a roll lands, coloured by how it went for you (see ptg.outcome).

    badge     the roll's line ends in a coloured pill: ✔ HIT, ✘ MISS, • NOTHING, ★ CRITICAL!, ✖ FUMBLE
    flash     the line lights up in that colour and fades
    pulse     a panel's border lights up for a moment (and blinks for a natural 20 or 1)
    popup     a number or word drifts away from where it happened: damage off the monster, HP by your hearts
    sounds    which of ptg.sound's moments a roll or an event plays
"""

from __future__ import annotations

import asyncio

from rich.cells import cell_len
from rich.text import Text
from textual.color import Color
from textual.css.scalar import ScalarOffset
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Static

from ..events import Event
from ..outcome import AWFUL, BAD, GOOD, GREAT, NEUTRAL, tone

COLORS = {GREAT: "#ffd166", GOOD: "#4cff8a", NEUTRAL: "#c8c8e0", BAD: "#ff4b4b", AWFUL: "#ff2a6d"}
ICONS = {GREAT: "★", GOOD: "✔", NEUTRAL: "•", BAD: "✘", AWFUL: "✖"}
INK = "#10122a"

# What happens (that isn't a roll) and the sound it makes. Rolls go by roll_sound().
EVENT_SOUNDS = {
    "enter": "step", "flee": "step", "travel": "step", "ambush": "windup", "locked": "locked", "unlock": "unlock", "telegraph": "windup", "stun": "stun",
    "find": "item", "take": "item", "loot": "item", "equip": "item", "key": "item", "fate": "fate", "trait": "fate",
    "pacify": "good", "exploit": "good", "bomb": "bomb", "secret_room": "bomb", "tip": "secret", "buy": "coin",
}


async def paced(frames):
    """Frames (each a tuple whose second part is the seconds it shows: a clip's), handed on at their own speed: the
    time one takes to draw comes off the wait after it, so a clip plays as fast as it was made, whatever the size."""
    loop = asyncio.get_running_loop()
    due = loop.time()
    for frame in frames:
        yield frame
        due += frame[1]
        await asyncio.sleep(max(0.0, due - loop.time()))


def frame_size(frame) -> tuple[int, int]:
    """A frame's rows and its widest row's cells: what a picture-sized Static is laid out to."""
    lines = (frame.plain if isinstance(frame, Text) else str(frame)).split("\n")
    return len(lines), max(map(cell_len, lines), default=0)


def show_frame(art: Static, frame, shown: tuple | None) -> tuple[int, int]:
    """A frame of an animation drawn into its Static (`shown`: the size of the one there now): the same size, it's
    drawn without laying the whole screen out again. That took 8-12 ms a frame at 24 a second, more as a floor's story
    grew, and stuttered run 66's floor 5. Returns its size, to pass back next time."""
    size = frame_size(frame)
    art.update(frame, layout=size != shown)
    return size


def event_sound(event: Event) -> str | None:
    """The sound of something that happened (not a roll): its own if it has one (a monster's cry as it rears up), a
    bomb's boom whatever it was thrown at, or its kind's."""
    return event.data.get("sound") or ("bomb" if event.data.get("bomb") else EVENT_SOUNDS.get(event.kind))


def roll_sound(event: Event) -> str:
    """The sound a roll makes when its result shows: what happened if it's a blow, otherwise how it went."""
    how = tone(event)
    if event.kind == "hit":
        return "crit_hit" if how == GREAT else "hit"
    if event.kind == "monster_hit":
        return "hurt"
    if event.dice.actor == "player" and how in (GREAT, AWFUL):
        return how
    return {"miss": "miss", "monster_miss": "dodge", "evade": "dodge", "secret": "secret"}.get(event.kind, how)


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


PULSED = ("border_top", "border_right", "border_bottom", "border_left", "border_title_color")


def lit(widget: Widget) -> str:
    """The tone a pulse has the widget's border lit in now, or "" (for the tests)."""
    if getattr(widget, "_ptg_pulse_was", None) is None or not widget.styles.inline.has_rule("border_top"):
        return ""
    colour = widget.styles.border_top[1].hex.lower()
    return next((tone for tone, hex_ in COLORS.items() if hex_ == colour), "")


def pulse(widget: Widget, tone: str, blinks: int = 1, on: float = 0.5, off: float = 0.12) -> None:
    """Light the widget's border in the tone's colour for a moment, blinking `blinks` times. A newer pulse on
    the same widget takes over from an older one. Its own style, set and put back as it was: a class on the story's
    frame had every line of the story's style worked out again, every blink (run 66's floor 5, its story long)."""
    token = object()
    inline = widget.styles.inline
    was = getattr(widget, "_ptg_pulse_was", None) or {rule: inline.get_rule(rule) for rule in PULSED}
    widget._ptg_pulse, widget._ptg_pulse_was = token, was  # type: ignore[attr-defined]
    colour = Color.parse(COLORS[tone])

    def step(i: int) -> None:
        if getattr(widget, "_ptg_pulse", None) is not token:
            return
        lit = i % 2 == 0 and i < blinks * 2
        if lit:
            widget.styles.border = ("double", colour)
            widget.styles.border_title_color = colour
        else:
            gutter = widget.styles.gutter
            for rule, value in was.items():
                inline.clear_rule(rule) if value is None else inline.set_rule(rule, value)
            widget.refresh(layout=widget.styles.gutter != gutter)
        if i < blinks * 2:
            widget.set_timer(on if lit else off, lambda: step(i + 1))
        else:
            widget._ptg_pulse_was = None  # type: ignore[attr-defined]

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
