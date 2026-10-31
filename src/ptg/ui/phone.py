"""The game screen made for a finger (docs/plans/mobile-view.md §4), what a touch screen plays on.

Every box is a fixed size, set by the screen's size alone, so nothing moves while you play: a room with more in it,
a fight starting, a longer choice, none of them push another box along. Upright (a phone held in the hand, under 60
columns) it's one column: the status bar; the room's picture (the fight, in one); the tabs, Story, Here, Pack, Map
and Sheet, and the one they show, the story while you play; the ways out, an arrow each; and the choices as big
buttons two across at your thumb, every one of them (Here's own first, so Attack is never a tab away), then the
command line. Wide (a folding phone opened out, a tablet, a phone on its side) it's two: the picture and the story on
the left, the tabs, the ways and the buttons on the right. Turned or folded across that line, it's laid out again the
other way, the run as it was.

The turns, the story and the pictures are GameScreen's, and the tabs' panes TabsScreen's: this lays them out. Picked
by ui/tabs.game_screen for a touch screen; the ☰ menu's Layout swaps it for the classic screen, for comparing."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Center, Horizontal, Vertical, VerticalScroll
from textual.events import Click
from textual.widgets import Input, Static

from ..events import Action
from .plan import Plan
from .tabs import TAB_PANEL, TabsScreen
from .widgets import ARROWS, PHONE, Clickable, ClickableBox, DPad, Hud, StoryLine

TABS_UPRIGHT = (("story", "Story"), ("here", "Here"), ("pack", "Pack"), ("map", "Map"), ("sheet", "Sheet"))
TABS_WIDE = (("here", "Here"), ("pack", "Pack"), ("map", "Map"), ("sheet", "Sheet"), ("journal", "Journal"))
STAGE_SHARE = 0.32  # upright: the room's picture's share of the rows (within STAGE_LEAST and STAGE_MOST)
STAGE_LEAST, STAGE_MOST = 8, 20
WIDE_STAGE_SHARE = 0.5  # wide: of the left column's rows
WIDE_SIDE = 0.46  # wide: the right column's share of the width
TAB_ROWS = 2  # a tab two rows tall, for a finger
WAYS_ROWS = 2
CHOICE_ROWS = 8  # three rows of buttons two rows tall (a row between), two across; more scroll
TOUCH_CLASSIC = {"on": False}  # the ☰ menu's Layout: the classic screen instead, for comparing (this run's session)


class PhoneButton(Static):
    """A choice as a big button: its number and its words, two rows of them; tapped, its action (a picker's opens
    its list first: GameScreen.press)."""

    def __init__(self, number: int, action: Action, words: Text) -> None:
        super().__init__(words, classes="phone-choice")
        self.number, self.action = number, action
        if action.id.startswith("perk:") or action.id == "attack":
            self.add_class("-first")

    def on_click(self, event: Click) -> None:
        event.stop()
        self.screen.pressed(self.number, self.action)


class PhoneScreen(TabsScreen):
    """The game screen for a finger (see the module's docstring)."""

    def __init__(self, game, fresh: bool, switched: bool = False) -> None:
        super().__init__(game, fresh, switched)
        self.tab = "story"
        self.upright = True
        self.tabs_shown: tuple | None = None

    def compose(self) -> ComposeResult:
        self.upright = self.app.size.width < PHONE
        if not self.upright:
            self.tab = "here"
        with Horizontal(id="hud-row"):
            yield Hud(id="hud")
            yield Static(id="hud-short")
            yield Clickable(Text(" ☰ "), "screen.menu()", id="hud-menu")
        with Horizontal(id="main"):
            with Vertical(id="left"):
                with Center(id="stage-box"):
                    with ClickableBox(action="screen.stage_card()", id="stage"):
                        yield Static(id="stage-art")
                if not self.upright:
                    yield VerticalScroll(id="story")
            with Vertical(id="side"):
                yield Horizontal(id="phone-tabs")
                with Vertical(id="pane-box"):
                    if self.upright:
                        yield VerticalScroll(id="story")
                    yield VerticalScroll(id="pane")
                yield Horizontal(id="ways")
                with Vertical(id="decide"):
                    yield VerticalScroll(id="choices")
                    yield Input(id="command", placeholder="Type, or tap a choice")
        with Vertical(id="shims"):  # (what GameScreen's and TabsScreen's turns look for, that this layout hasn't)
            yield Vertical(id="here")
            yield Vertical(id="here-strip")
            yield Static(id="map")
            yield DPad(id="dpad")
            yield Horizontal(id="pane-head")
            yield Static(id="ways-words")
            yield Horizontal(id="tab-row")
            yield Static(id="tab-bar")
            yield Clickable(Text(" "), "screen.expand()", id="tab-expand")
            yield StoryLine(id="lately")
            yield Static(id="footer-narrator")

    # --- the layout ---

    def relayout(self) -> None:
        """Every box its fixed size for this screen: upright, the picture a share of the rows and the pane what's
        left over the ways and the buttons; wide, the picture and the story on the left, the rest on the right."""
        if self._resize_timer is not None:
            self._resize_timer.stop()
            self._resize_timer = None
        width, height = self.size
        if not width:
            return
        if (width < PHONE) != self.upright:  # (turned, or folded: laid out the other way)
            self.call_later(self.rearrange)
            return
        rows = height - 1  # (less the status bar)
        decide = CHOICE_ROWS + 1  # (and the command line)
        if self.upright:
            side, stage_width = width, width
            stage_rows = max(STAGE_LEAST, min(STAGE_MOST, round(STAGE_SHARE * rows)))
            pane = rows - stage_rows - TAB_ROWS - WAYS_ROWS - decide
            story = pane
        else:
            side = max(40, round(width * WIDE_SIDE))
            stage_width = width - side
            stage_rows = max(STAGE_LEAST, min(30, round(WIDE_STAGE_SHARE * rows), round(stage_width / 3)))
            pane = rows - TAB_ROWS - WAYS_ROWS - decide
            story = rows - stage_rows
        # (the picture's own rows: its box has a rule on top with the room's name)
        self.plan = Plan(width, height, not self.upright, True, True, side, stage_rows - 1, stage_width,
                         CHOICE_ROWS, WAYS_ROWS, pane, story)
        self.lately_lines = 0  # (notifications are toasts: there's no docked journal)
        self.set_class(True, "touch")
        self.set_class(True, "compact")
        self.set_class(self.upright, "upright")
        self.query_one("#side").styles.width = side
        self.query_one("#stage-box").styles.height = stage_rows
        self.query_one("#pane-box").styles.height = pane
        self.query_one("#ways").styles.height = WAYS_ROWS
        self.query_one("#decide").styles.height = decide
        if not self.upright:
            self.query_one("#left").styles.width = stage_width
            self.query_one("#story").styles.height = story
        self.refresh_hud()
        self.refresh_stage()
        self.refresh_here()
        self.refresh_choices()
        self.refresh_ways()

    refresh_panels = relayout

    def rearrange(self) -> None:
        """The screen turned or folded across the upright line: the same run, laid out the other way."""
        if self.busy:
            self.later(self.rearrange)
            return
        self.switching = True  # (the music plays on)
        self.app.switch_screen(PhoneScreen(self.game, False, switched=True))

    def refresh_stage(self) -> None:
        """The picture as TabsScreen draws it, with a rule over it in place of a frame (a phone's every column
        counts), titled with the room's name."""
        super().refresh_stage()
        stage = self.query_one("#stage")
        colour = stage.styles.border_top[1] if stage.styles.border_top else None
        stage.styles.border = None
        if colour is not None:
            stage.styles.border_top = ("heavy", colour)

    # --- the tabs and the pane ---

    def phone_tabs(self) -> tuple:
        return TABS_UPRIGHT if self.upright else TABS_WIDE

    def refresh_tabs(self) -> None:
        """The tabs, a button each, the one showing lit in its own colour; Here, not showing, says when it has something
        for you. Rebuilt only when that changes."""
        shown = (self.tab, self.waiting_here(), self.game.state.in_combat)
        if shown == self.tabs_shown:
            return
        self.tabs_shown = shown
        bar = self.query_one("#phone-tabs", Horizontal)
        buttons = []
        for key, label in self.phone_tabs():
            on = key == self.tab
            colour = "#c8c8e0" if key == "story" else self.tab_colour(key)
            words = Text(f"{label}{' ●' if key == 'here' and self.waiting_here() else ''}",
                         style=f"bold #10122a on {colour}" if on else f"bold {colour}", justify="center")
            button = Clickable(words, f"screen.tab('{key}')", classes="phone-tab" + (" -on" if on else ""))
            if on:
                button.styles.background = colour
            buttons.append(button)
        with self.app.batch_update():
            bar.remove_children()
            bar.mount_all(buttons)

    def waiting_here(self) -> bool:
        return self.tab != "here" and any(t.character or t.verbs for t in self.things)

    def action_tab(self, name: str) -> None:
        """A tab tapped: its pane in the one place panes go (the story's too, upright); nothing else moves."""
        if name == self.tab or name not in (*TAB_PANEL, "story"):
            return
        if name == "story" and not self.upright:
            return
        self.tab = name
        self.show_tab()
        if name != "story":
            self.draw_pane(force=True)
            self.query_one("#pane").scroll_home(animate=False)

    def show_tab(self) -> None:
        story = self.tab == "story"
        if self.upright:
            self.query_one("#story").display = story
        self.query_one("#pane").display = not story
        self.refresh_tabs()
        if story:
            self._follow()

    def refresh_here(self) -> None:
        """Who and what is here, and the pane drawn; the tab you're on stays (a fight starting doesn't take you off the
        story: the picture and the buttons have the fight)."""
        tab = self.tab
        super().refresh_here()
        if tab == "story" and self.upright:
            self.tab = "story"
        self.show_tab()

    def draw_pane(self, force: bool = False) -> None:
        if self.tab == "story":
            return
        super().draw_pane(force)

    def action_panel(self, name: str) -> None:
        """A panel asked for (the ☰ menu, a typed "map"): its tab, if it has one here; else the panel in full."""
        tab = {"look": "here", "map": "map", "inventory": "pack", "character": "sheet",
               "journal": "journal"}.get(name)
        if tab and tab in dict(self.phone_tabs()) and tab != self.tab:
            self.action_tab(tab)
        else:
            super(TabsScreen, self).action_panel(name)

    # --- the choices, the ways ---

    def _strip(self) -> list[Action]:
        """Every choice but the ways out (the arrows have those): Here's own included, numbered first."""
        return [a for a in super()._strip() if not a.id.startswith("go:") or self.game.state.scene]

    def refresh_choices(self) -> None:
        """The choices as big buttons two across, Here's own first (Attack is never a tab away), each its number and
        its words; the box a fixed size, scrolling when there are more. Rebuilt only when they change."""
        game = self.game
        scene = game.story.scene_title(game.state)
        verbs = list(self.tile_verbs)
        actions = [*verbs, *self._strip()]
        self.numbered = actions
        self.query_one(DPad).show(self._choices(), game.locked_doors())
        shown = (scene, game.state.over, [(a.id, a.label, a.hint) for a in actions])
        if shown == self.choices_shown:
            return
        self.choices_shown = shown
        box = self.query_one("#choices", VerticalScroll)
        if game.state.over:
            with self.app.batch_update():
                box.remove_children()
                box.mount(Clickable(Text("Tap here to see your fate.", style="bold #ffb000"), "screen.fate()",
                                    classes="phone-note"))
            return
        buttons = []
        for number, action in enumerate(actions, 1):
            owner = self.verb_owner.get(action.id, "") if action in verbs else ""
            buttons.append(PhoneButton(number, action, self.button_words(number, action, owner)))
        if not buttons:
            buttons.append(Static(Text("Nothing to choose: the arrows, or type what you do.", style="#6c6f99"),
                                  classes="phone-note"))
        with self.app.batch_update():
            box.remove_children()
            box.mount_all(buttons)
            box.scroll_home(animate=False)

    @staticmethod
    def button_words(number: int, action: Action, owner: str = "") -> Text:
        """A button's words: its number, then what it does (to whom, for one of Here's: "Face it · the Rot Gill"), what
        it costs or risks under it."""
        creative = action.label.startswith("✦") or action.id == "suggest"
        text = Text(f"{number} ", style="bold #ffb000")
        label = f"{action.label} · {owner}" if owner and len(action.label) < 12 else action.label
        text.append(label, style="italic bold #ff4f9a" if creative else "bold #ffd166" if action.id.startswith(
            "perk:") else "bold #e8e8f4")
        if action.hint:
            text.append(f"\n{action.hint}", style="#9a9cc0")
        return text

    def pressed(self, number: int, action: Action) -> None:
        """A button tapped: a scene's, or the idea, go by their number (as typed); the rest as they are."""
        if self.busy:
            self.later(lambda: self.pressed(number, action))
            return
        if self.game.state.over:
            return
        if self.game.state.scene or action.id == "suggest":
            self.run_turn(str(next((i for i, a in enumerate(self._choices(), 1) if a.id == action.id), number)))
        else:
            self.press(action)

    def action_fate(self) -> None:
        """The run's over: on to how it ended (what Enter does)."""
        if self.game.state.over and not self.busy:
            self.app.end_run(self)

    def refresh_ways(self) -> None:
        """The ways out, an arrow each, always in the same place, lit where there's a way (a locked door says so)."""
        bar = self.query_one("#ways", Horizontal)
        choices, locked = self._choices(), self.game.locked_doors()
        ways = {a.id[3:]: a for a in [*locked, *choices] if a.id.startswith("go:")}
        shown = tuple((d, d in ways) for d in ("west", "north", "south", "east"))
        if getattr(self, "ways_shown", None) == shown and bar.children:
            return
        self.ways_shown = shown
        buttons = []
        for direction, lit in shown:
            label = Text(f"{ARROWS[direction]} {direction[0].upper()}", style="bold #5fe3ff" if lit else "#2e3149")
            buttons.append(Clickable(label, f"screen.go('{direction}')" if lit else "screen.nothing()", classes="way"))
        with self.app.batch_update():
            bar.remove_children()
            bar.mount_all(buttons)

    def action_switch_layout(self) -> None:
        """The ☰ menu's Layout: the classic screen, for comparing (back with the same)."""
        swap_touch_layout(self)


def swap_touch_layout(screen) -> None:
    """Between this screen and the classic one, played by touch: the run as it was."""
    from .game_screen import GameScreen

    if screen.busy or screen.game.state.over:
        return
    TOUCH_CLASSIC["on"] = not TOUCH_CLASSIC["on"]
    nxt = GameScreen(screen.game, False, switched=True) if TOUCH_CLASSIC["on"] else \
        PhoneScreen(screen.game, False, switched=True)
    screen.switching = True
    screen.app.switch_screen(nxt)
    nxt.notify("The classic screen. ☰ Layout for the phone's." if TOUCH_CLASSIC["on"] else
               "The phone's screen. ☰ Layout for the classic one.", title="Layout", timeout=3)
