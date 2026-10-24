"""Between runs: the campfire hub (souls, blessings, gifts, Hall of Legends) and the end-of-run screen."""

from __future__ import annotations

import asyncio
from datetime import datetime

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Horizontal, Vertical, VerticalScroll
from textual.geometry import Size
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Button, Footer, Static, TabbedContent, TabPane

from .. import sound
from ..content import Content, Unlock, load_content
from ..meta import SUNGLASSES, daily_seed, share_card, souls_earned
from ..models import GameState
from ..profile import Profile
from ..sprites import DEFAULT_WIDTH, SMALL, engrave, frames, sprite_text
from ..story import load_library
from .widgets import TALL, Clickable, Picture

CAMPFIRE = r"""
       )   (
      (  )  )
     ) (  (  (
    (  ) )  ) )
     \(_(_)_)/
   ~~~~\\||//~~~~
""".strip("\n")

TOMBSTONE = r"""
      __________
     /          \
    /   R.I.P.   \
   |              |
   |{name:^14}|
   |{line:^14}|
   |              |
 __|______________|__
""".strip("\n")

CROWN = r"""
    _/\_/\_/\_
    \  *  *  /
     \______/
""".strip("\n")
CROWN_GLINT = [0, 1, 2, 3] + [4] * 8  # the pixel crown's frames: a glint sweeps across it, then it rests a while
END_WIDTH = 76  # the end screen's box (#end-box in app.tcss), border and padding included


def tombstone(name: str, floor: int, width: int = DEFAULT_WIDTH) -> Text | None:
    """The pixel tombstone with the name and floor carved into it (a half-size one has room for just R.I.P.), or None
    without sprites (then it's TOMBSTONE)."""
    found = frames("tombstone", width)
    if not found:
        return None
    return engrave(found[0], {2: "R.I.P.", 4: name[:14], 5: f"floor {floor}"} if width == DEFAULT_WIDTH else
                   {2: "R.I.P."})


def rows(widget: Widget, width: int) -> int:
    """How many rows a widget takes `width` columns wide, its own border and padding included."""
    gutter = widget.styles.gutter
    size = Size(width, 0)
    return widget.get_content_height(size, size, width - gutter.width) + gutter.height


class UnlockCard(Button):
    def __init__(self, unlock: Unlock, state: str) -> None:
        label = {"locked": f"{unlock.icon} {unlock.name}\n☽ {unlock.cost}",
                 "chosen": f"► {unlock.icon} {unlock.name}"}.get(state, f"{unlock.icon} {unlock.name}")
        super().__init__(label, classes=f"unlock-card {state}")
        self.unlock = unlock


class HubScreen(Screen):
    """The campfire. Spend souls, pick a gift, read the Hall of Legends, and go back down.

    Everything keeps its place: the cards scroll in their tabs, what the one you pick does shows in a pane of its own
    height under them, and the buttons to go back down stay at the bottom. On a short screen the fire burns smaller,
    so the Hall of Legends keeps a few lines."""

    BINDINGS = [Binding("d", "descend", "Descend"), Binding("y", "daily", "Daily"), Binding("escape", "back", "Title")]

    def __init__(self, profile: Profile) -> None:
        super().__init__()
        self.profile = profile
        self.content: Content = load_content()
        self.selected: Unlock | None = None

    def compose(self) -> ComposeResult:
        with Horizontal(id="hub"):
            with Vertical(id="hub-left"):
                with TabbedContent(id="hub-tabs"):
                    with TabPane("Blessings", id="tab-blessings"):
                        yield VerticalScroll(Grid(id="grid-blessing", classes="unlock-grid"))
                    with TabPane("Gifts", id="tab-gifts"):
                        yield VerticalScroll(Grid(id="grid-gift", classes="unlock-grid"))
                    with TabPane("Secrets", id="tab-secrets"):
                        yield VerticalScroll(Static("", id="secrets-list"))
                with Vertical(id="unlock-pane"):
                    yield Static("", id="unlock-detail")
                    yield Button("", id="unlock-action", variant="primary")
            with Vertical(id="hub-right"):
                yield Picture("campfire", flicker=True, ascii=Text(CAMPFIRE, style="bold #ff7b2e"), id="campfire")
                yield Static(Text("The Void stirs...", style="italic #9a9cc0"), id="void-line")
                yield Static("", id="hub-souls")
                yield VerticalScroll(Static("", id="legends"), id="legends-box")
                with Horizontal(id="hub-buttons"):
                    yield Button("Descend", id="descend", variant="primary")
                    yield Button("Daily descent", id="daily")
                    yield Button("Title", id="back")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#legends-box").border_title = "Hall of Legends"
        self.refresh_all()
        self.speak()

    def on_resize(self) -> None:
        """The fire at full size on a tall screen, half size on a short one."""
        self.query_one("#campfire", Picture).fit(DEFAULT_WIDTH, None if self.size.height >= TALL else SMALL // 2)

    def on_screen_resume(self) -> None:
        self.refresh_all()
        self.speak()

    def refresh_all(self) -> None:
        unlocked = self.profile.unlocked()
        gift = self.profile.gift
        for kind in ("blessing", "gift"):
            grid = self.query_one(f"#grid-{kind}", Grid)
            grid.remove_children()
            cards = []
            for unlock in self.content.unlocks.values():
                if unlock.kind != kind:
                    continue
                if unlock.requires and unlock.requires not in unlocked:
                    continue
                state = "owned" if unlock.key in unlocked else "locked"
                if kind == "gift" and unlock.key == gift:
                    state = "chosen"
                cards.append(UnlockCard(unlock, state))
            grid.mount(*cards)
        souls = Text("☽ ", style="bold #5fe3ff")
        souls.append(f"{self.profile.souls} souls", style="bold")
        chosen = self.content.unlocks.get(gift)
        if chosen:
            souls.append(f"     gift: {chosen.icon} {chosen.name}", style="#ffb000")
        self.query_one("#hub-souls", Static).update(souls)
        self.query_one("#legends", Static).update(self.legends())
        self.query_one("#secrets-list", Static).update(self.book_of_secrets())
        _, today = daily_seed()
        done = self.profile.daily_run(today)
        daily = self.query_one("#daily", Button)
        daily.disabled = done is not None
        daily.label = "Daily: done" if done else "Daily descent"
        self.show_detail(self.selected)

    def book_of_secrets(self) -> Text:
        """Every hand-written secret: the ones you've found by name, the rest as a hint."""
        secrets = load_library(self.content).secrets
        found = self.profile.secrets()
        text = Text(f"BOOK OF SECRETS · {len(found)}/{len(secrets)} found\n\n", style="bold #ffd166")
        for event in secrets:
            if event.id in found:
                when = datetime.fromtimestamp(found[event.id]).strftime("%b %d")
                text.append(f"✧ {event.title}", style="bold #ffd166")
                text.append(f"   found {when}\n", style="#6c6f99")
            else:
                text.append("? ???", style="#6c6f99")
                text.append(f"   {event.hint}\n" if event.hint else "\n", style="italic #9a9cc0")
        if not secrets:
            text.append("No secrets have been written yet.", style="#6c6f99")
        return text

    def legends(self) -> Text:
        runs = self.profile.runs(limit=12)
        totals = self.profile.totals()
        secrets = f" · secrets {len(self.profile.secrets())}/{len(load_library(self.content).secrets)}"
        text = Text(f"{totals['runs']} descents · {totals['wins']} victories · deepest floor {totals['deepest']}"
                    f"{secrets}\n\n", style="#9a9cc0")
        if not runs:
            text.append("No legends yet. Be the first.", style="#6c6f99")
        for run in runs:
            mark = "★" if run["status"] == "won" else "☠"
            text.append(f"{mark} ", style="bold #ffd166" if run["status"] == "won" else "#ff4b4b")
            text.append(f"{run['name']} {run['epithet']}", style="bold")
            if run.get("modded"):
                text.append(f" {SUNGLASSES}", style="bold #5fe3ff")
            text.append(f"  lv{run['level']} · floor {run['floor']} · ☽{run['souls']}"
                        f"{' · daily' if run['daily'] else ''}\n", style="#9a9cc0")
            if run["epitaph"]:
                text.append(f"   “{run['epitaph']}”\n", style="italic #c8c8e0")
        return text

    @work(exclusive=True, group="void")
    async def speak(self) -> None:
        from ..llm.extras import void_line

        runs = self.profile.runs(limit=1)
        llm = await self.app.connect(quiet=True)
        line = await void_line(llm, runs[0] if runs else None, self.app.config.player_name)
        if llm is not None:
            await llm.aclose()
        self.query_one("#void-line", Static).update(Text(f"The Void: “{line}”", style="italic #ff4f9a"))

    @on(Button.Pressed, ".unlock-card")
    def card_pressed(self, event: Button.Pressed) -> None:
        self.selected = event.button.unlock
        self.show_detail(self.selected)

    def show_detail(self, unlock: Unlock | None) -> None:
        """What the card you've picked does (it's marked as picked), and what you can do about it, in the pane under
        the tabs."""
        for card in self.query(UnlockCard):
            card.set_class(unlock is not None and card.unlock.key == unlock.key, "-picked")
        detail = self.query_one("#unlock-detail", Static)
        action = self.query_one("#unlock-action", Button)
        if unlock is None:
            detail.update(Text("Pick a blessing or a gift to see what it does.", style="#6c6f99"))
            action.visible, action.disabled = False, True  # (its place is kept for it)
            return
        unlocked = unlock.key in self.profile.unlocked()
        text = Text(f"{unlock.icon} {unlock.name.upper()}\n", style="bold #ffb000")
        text.append(unlock.desc, style="#c8c8e0")
        detail.update(text)
        action.visible = True
        if not unlocked:
            action.label = f"Unlock for ☽ {unlock.cost}"
            action.disabled = self.profile.souls < unlock.cost
        elif unlock.kind == "gift":
            chosen = self.profile.gift == unlock.key
            action.label = "Your gift for the next descent" if chosen else "Take this gift"
            action.disabled = chosen
        else:
            action.label = "Blessing owned"
            action.disabled = True

    @on(Button.Pressed, "#unlock-action")
    def unlock_action(self) -> None:
        unlock = self.selected
        if unlock is None:
            return
        if unlock.key not in self.profile.unlocked():
            if self.profile.buy(unlock.key, unlock.cost):
                self.notify(f"{unlock.icon} {unlock.name} unlocked.", title="The Void accepts your souls")
                if unlock.kind == "gift":
                    self.profile.set("gift", unlock.key)
        elif unlock.kind == "gift":
            self.profile.set("gift", unlock.key)
        self.refresh_all()

    @on(Button.Pressed, "#descend")
    def action_descend(self) -> None:
        self.app.start_descent(daily=False)

    @on(Button.Pressed, "#daily")
    def action_daily(self) -> None:
        if not self.query_one("#daily", Button).disabled:
            self.app.start_descent(daily=True)

    @on(Button.Pressed, "#back")
    def action_back(self) -> None:
        self.app.pop_screen()


class EndScreen(Screen):
    """Death or glory: the tombstone (or crown), the epitaph, and the souls you bank. It all fits on the screen: on a
    short one the blank lines between the parts go, then the pixel picture shrinks to half size (see fit)."""

    BINDINGS = [Binding("enter,space", "campfire", "To the campfire"), Binding("c", "copy", "Copy result")]

    def __init__(self, state: GameState) -> None:
        super().__init__()
        self.state = state
        self.picture = ""  # the pixel picture's sprite ("crown" or "tombstone"); "" for the ASCII art
        self.picture_width = DEFAULT_WIDTH

    def compose(self) -> ComposeResult:
        state = self.state
        player = state.player
        key = "crown" if state.status == "won" else "tombstone"
        self.picture = key if self.app.config.art == "sprites" and frames(key) else ""
        with Vertical(id="end-box"):
            if state.status == "won":
                yield Picture("crown", flicker=True, loop=CROWN_GLINT, ascii=Text(CROWN, style="bold #ffd166"),
                              classes="end-art")
                yield Static(Text("V I C T O R Y", style="bold reverse #ffd166"), classes="end-title")
            else:
                stone = tombstone(player.name, state.floor) if self.picture else None
                ascii_stone = TOMBSTONE.format(name=player.name[:14], line=f"floor {state.floor}")
                yield Static(stone or Text(ascii_stone, style="#9aa0c8"), classes="end-art")
                yield Static(Text("Y O U   D I E D", style="bold reverse #ff4b4b"), classes="end-title")
            yield Static(Text(f"“{state.epitaph}”", style="italic #e8e8f4"), classes="end-epitaph")
            stats = Text(f"Level {player.level} · {player.kills} slain · {player.style.get('pacify', 0)} talked down · "
                         f"{player.style.get('flair', 0)} stunts · {player.gold} gold · {state.turn} turns",
                         style="#9a9cc0")
            if player.traits:
                stats.append("\nTraits: " + ", ".join(t.replace("_", " ").title() for t in player.traits),
                             style="#4cff8a")
            yield Static(stats, classes="end-stats")
            yield Static("", id="end-souls")
            yield Static(Text(share_card(state), style="#6c8cff"), id="end-card")
            with Horizontal(classes="end-hint"):
                yield Clickable(Text(" [enter] to the campfire ", style="#ffb000"), action="screen.campfire")
                yield Clickable(Text(" [c] copy result ", style="#ffb000"), action="screen.copy")
        yield Footer()

    def on_mount(self) -> None:
        sound.play("victory" if self.state.status == "won" else "death")
        self.tally()

    def on_resize(self) -> None:
        self.fit()

    def fit(self) -> None:
        """Fit the whole box on the screen, down to the hint at the bottom: with a blank line between the parts if
        there's room, else without; with the pixel picture full size if it fits, else half size; and on a tiny
        screen with no picture at all (past that, the screen scrolls)."""
        box = self.query_one("#end-box")
        art = box.query_one(".end-art", Static)
        # The width inside the box's border and its padding at the sides, as if the screen had a scrollbar (it has
        # one while the box is too tall, and that narrows the box, which wraps more lines, which keeps it too tall).
        width = min(END_WIDTH, self.size.width - self.styles.scrollbar_size_vertical) - 6
        rest = sum(rows(part, width) for part in box.children if part is not art)
        room = self.size.height - 3  # less the footer and the box's border
        gaps = sum(isinstance(part, Static) for part in box.children) + 2  # a line under each, and the box's padding
        if self.picture:
            tall = {size: sprite_text(self.picture, 0, size).plain.count("\n") + 1 for size in (DEFAULT_WIDTH, SMALL)}
        else:
            tall = {0: art.content.plain.count("\n") + 1}  # the ASCII art
        size = next((size for size, height in tall.items() if rest + height <= room), None)
        art.display = size is not None
        box.set_class(rest + tall.get(size, 0) + gaps > room, "-tight")
        if size and size != self.picture_width:
            self.picture_width = size
            if isinstance(art, Picture):  # the crown, glinting
                art.fit(size)
            else:
                art.update(tombstone(self.state.player.name, self.state.floor, size))

    @work(exclusive=True)
    async def tally(self) -> None:
        widget = self.query_one("#end-souls", Static)
        if self.state.test_room:
            widget.update(Text("A test room: nothing banked, nothing remembered.", style="bold #5fe3ff"))
            return
        total = souls_earned(self.state)
        steps = min(total, 30) or 1
        for i in range(steps + 1):
            value = round(total * i / steps)
            widget.update(Text(f"☽ +{value} souls banked", style="bold #5fe3ff"))
            await asyncio.sleep(0.03)

    def action_copy(self) -> None:
        self.app.copy_to_clipboard(share_card(self.state, emoji=True))
        self.notify("Result copied (if your terminal allows it).", timeout=3)

    def action_campfire(self) -> None:
        self.app.show_campfire()
