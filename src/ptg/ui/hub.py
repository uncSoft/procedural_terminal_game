"""Between runs: the campfire hub (souls, blessings, gifts, Hall of Legends) and the end-of-run screen."""

from __future__ import annotations

import asyncio
from datetime import datetime

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Static, TabbedContent, TabPane

from ..content import Content, Unlock, load_content
from ..meta import daily_seed, share_card, souls_earned
from ..models import GameState
from ..profile import Profile
from ..sprites import sprite_text
from ..story import load_library

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


class UnlockCard(Button):
    def __init__(self, unlock: Unlock, state: str) -> None:
        label = {"locked": f"{unlock.icon} {unlock.name}\n☽ {unlock.cost}",
                 "chosen": f"► {unlock.icon} {unlock.name}"}.get(state, f"{unlock.icon} {unlock.name}")
        super().__init__(label, classes=f"unlock-card {state}")
        self.unlock = unlock


class HubScreen(Screen):
    """The campfire. Spend souls, pick a gift, read the Hall of Legends, and go back down."""

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
                        yield Grid(id="grid-blessing", classes="unlock-grid")
                    with TabPane("Gifts", id="tab-gifts"):
                        yield Grid(id="grid-gift", classes="unlock-grid")
                    with TabPane("Secrets", id="tab-secrets"):
                        yield VerticalScroll(Static("", id="secrets-list"))
                yield Static("", id="unlock-detail")
                yield Button("", id="unlock-action", variant="primary")
            with Vertical(id="hub-right"):
                yield Static(Text(CAMPFIRE, style="bold #ff7b2e"), id="campfire")
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
        self.fire_frame = 0
        self._flicker()
        self.set_interval(0.2, self._flicker)

    def _flicker(self) -> None:
        self.fire_frame += 1
        art = sprite_text("campfire", self.fire_frame) if self.app.config.art == "sprites" else None
        self.query_one("#campfire", Static).update(art or Text(CAMPFIRE, style="bold #ff7b2e"))

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
        detail = self.query_one("#unlock-detail", Static)
        action = self.query_one("#unlock-action", Button)
        if unlock is None:
            detail.update(Text("Pick a blessing or a gift to see what it does.", style="#6c6f99"))
            action.display = False
            return
        unlocked = unlock.key in self.profile.unlocked()
        text = Text(f"{unlock.icon} {unlock.name.upper()}\n", style="bold #ffb000")
        text.append(unlock.desc, style="#c8c8e0")
        detail.update(text)
        action.display = True
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
    """Death or glory: the tombstone (or crown), the epitaph, and the souls you bank."""

    BINDINGS = [Binding("enter,space", "campfire", "To the campfire"), Binding("c", "copy", "Copy result")]

    def __init__(self, state: GameState) -> None:
        super().__init__()
        self.state = state

    def compose(self) -> ComposeResult:
        state = self.state
        player = state.player
        with Vertical(id="end-box"):
            if state.status == "won":
                yield Static(Text(CROWN, style="bold #ffd166"), classes="end-art")
                yield Static(Text("V I C T O R Y", style="bold reverse #ffd166"), classes="end-title")
            else:
                stone = TOMBSTONE.format(name=player.name[:14], line=f"floor {state.floor}")
                yield Static(Text(stone, style="#9aa0c8"), classes="end-art")
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
            yield Static(Text("[enter] to the campfire     [c] copy result", style="#ffb000"), classes="end-hint")
        yield Footer()

    def on_mount(self) -> None:
        self.tally()

    @work(exclusive=True)
    async def tally(self) -> None:
        widget = self.query_one("#end-souls", Static)
        total = souls_earned(self.state)
        steps = min(total, 30) or 1
        for i in range(steps + 1):
            value = round(total * i / steps)
            widget.update(Text(f"☽ +{value} souls banked", style="bold #5fe3ff"))
            await asyncio.sleep(0.03)

    def action_copy(self) -> None:
        self.app.copy_to_clipboard(share_card(self.state))
        self.notify("Result copied (if your terminal allows it).", timeout=3)

    def action_campfire(self) -> None:
        self.app.show_campfire()
