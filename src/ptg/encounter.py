"""A fight as an event on the stage (docs/plans/combat-and-balance.md §3.1, §3.6). While a monster's after you, the
stage stops being the room with a monster in it and becomes the fight: the room dimmed behind, the foe as big as the
stage lets it be (twice its size, where there's room) in a pool of light, what it'll do next over its head
(combat.foresee) and its banner under its feet: its traits and name, how dangerous it looks (combat.danger), its
health and what you know of it.

    Fight         one fight's pictures, the room behind it drawn once: as it stands (`still`, in a pose, flashing),
                  its coming in (`entrance`: from the side, or its own clip; a boss's name called out as it lands),
                  its own swing if it has one (`swing`), and its end (`shatter`)
    spoils_text   what it left: the XP bar, the gold, the souls, the style it was won in, and each thing it dropped in
                  its rarity's colour (`step`s of it, to show them coming one by one)
    wipe          one picture sweeping across another, from a side: the stage going back to the room after

Each is plain half-block Text (Rich): the screen shows them in turn. Nothing here changes the game."""

from __future__ import annotations

from dataclasses import InitVar, dataclass, field

from rich.style import Style
from rich.text import Text

from . import combat, loot, room_picture, sprites
from .content import Content
from .models import LEVEL_XP, GameState, MonsterState
from .sprites import Image

DIM = (0.34, 0.34, 0.44)  # how much of the room's light is left behind a fight (red, green, blue: a cold night)
INK = "#181425"
BAND = "#1b1830"  # the banner's ground
RED, ORANGE, GOLD, BLUE, GREEN, PURPLE = "#e43b44", "#feae34", "#fee761", "#6c8cff", "#63c74d", "#b55088"
WHITE, GREY, FAINT = "#ffffff", "#8b9bb4", "#3a4466"
POOL = (88, 74, 120)  # the light the foe stands in
FOE_SHARE = 0.55  # the most of the stage's width the foe may take
SHATTER_FRAMES = 7
CARD = "#3b1424"  # a boss's name card: crimson, gilt rules
GILT = "#be4a2f"
SPELL = 4  # the letters (and spaces) of a boss's name the card spells out each frame
STINGS = ("encounter", "boss_encounter")  # an entrance's cue as it lands (sound.MOMENTS); "dice_tick" spells
# What a monster's next move looks like over its head (combat.Foresight.kind): its ground, then its words' colour.
INTENT_LOOK = {"heavy": (RED, WHITE), "strike": ("#5a1f2e", WHITE), "guard": (BLUE, INK), "reeling": (GOLD, INK),
               "running": (ORANGE, INK)}
RARITY = {0: GREY, 1: "#c0cbdc", 2: GREEN, 3: "#0099db", 4: PURPLE}  # a thing's colour by its tier; rare: GOLD


def rarity(content: Content, key: str) -> str:
    """The colour a thing shines in when it drops: gold if it's rare, else its tier's."""
    item = content.item(key)
    return GOLD if loot.rare(item) else RARITY.get(min(4, item.tier), WHITE)


def danger_marks(level: int) -> Text:
    """☠☠○: how dangerous a fight looks (combat.danger), out of three."""
    return Text.assemble(("☠" * level, f"bold {RED}"), ("○" * (3 - level), FAINT))


def hp_bar(hp: int, most: int, cells: int, colour: str = RED) -> Text:
    """A health bar `cells` wide, and the numbers after it."""
    filled = round(cells * max(0, hp) / max(1, most))
    return Text.assemble(("█" * filled, colour), ("█" * (cells - filled), "#3e2731"),
                         (f" {max(0, hp)}/{most}", "bold"))


def traits(monster: MonsterState, content: Content) -> list[str]:
    """What sets this one apart, for its banner: a boss, the warden, its elite trait, a venom it was given."""
    known = content.monster(monster.key)
    tags = ["BOSS"] if known.boss else ["WARDEN"] if monster.warden else []
    if monster.elite:
        tags.append(monster.elite.upper())
    if "venom" in monster.tricks and monster.name.startswith(("Venomous ", f"{monster.elite} Venomous ")):
        tags.append("VENOMOUS")
    return tags


def plain_name(monster: MonsterState) -> str:
    """Its name without the traits the banner shows apart ("Troll", not "Hulking Venomous Troll")."""
    name = monster.name.removeprefix(f"{monster.elite} ") if monster.elite else monster.name
    return name.removeprefix("Venomous ") if "venom" in monster.tricks else name


def _write(lines: list[Text], row: int, words: Text, centre: int | None = None) -> None:
    """`words` over row `row` of a picture, centred on column `centre` (its middle by default), cut to fit."""
    if not 0 <= row < len(lines):
        return
    line = lines[row]
    width = len(line.plain)
    words = words[:width]
    size = len(words.plain)
    middle = width // 2 if centre is None else centre
    start = max(0, min(width - size, middle - size // 2))
    lines[row] = Text.assemble(line[:start], words, line[start + size:])


def _band(width: int) -> Text:
    return Text(" " * width, style=Style(bgcolor=BAND))


def _on_band(words: Text, ground: str = BAND) -> Text:
    """Words on the banner's ground: in their own colours, on `ground` wherever they've no ground of their own."""
    out = words.copy()
    base = out.style if isinstance(out.style, Style) else Style.parse(out.style or "")
    out.style = Style(bgcolor=ground) + base
    return out


@dataclass
class Fight:
    """One fight's pictures on a stage `width` cells across and `rows` tall: the room behind drawn once, dimmed, and
    the foe drawn into it as it is now, in whatever pose, or coming in, or breaking apart. What it shows of the fight
    is a copy taken when it's made and at each `update` (the foe, its next move, how dangerous it looks), so it can
    be drawn off the screen's thread, and its end after the game has let the foe go."""

    state: InitVar[GameState]
    content: Content
    monster: MonsterState
    width: int
    rows: int
    known: list[str] = field(default_factory=list)  # the weaknesses you know it has
    back: object = None  # the dimmed room (an RGB image)
    scale: float = 1.0
    seen: combat.Foresight | None = None  # its next move
    danger: int = 1
    clips: dict = field(default_factory=dict)  # its own clips at the size the stage takes (sprites.clips), if any
    boss: bool = False
    guardian: bool = False  # one that guards the way on (King Mouse, at the stairs): called out by name as a boss is
    realm: str = ""  # where it's boss of, for its name card

    def __post_init__(self, state: GameState) -> None:
        self.banner_rows = 2 if self.rows >= 10 else 1
        self.top_rows = 1 if self.rows >= 7 else 0
        known = self.content.monster(self.monster.key)
        self.boss, self.guardian = known.boss, "guardian" in known.tags and not known.boss
        self.realm = self.content.themes[state.theme].name if state.theme in self.content.themes else ""
        self.back = self._backdrop(state)
        room = 2 * (self.rows - self.banner_rows) - 1  # (as tall as it is, its next move over its head)
        self.clips = self._clips(room)
        if self.clips:  # (drawn as made: placed by where its standing art is in their frames)
            self.box = sprites.art_box(self.clips["idle"].frames)
        else:
            self.box = self._box()
            height = self.box[3] - self.box[1] if self.box else 24
            width = self.box[2] - self.box[0] if self.box else 24
            big = room - 2  # (bigger: with a row clear for that)
            fits = [s for s in (2.0, 1.5) if height * s <= big and width * s <= self.width * FOE_SHARE]
            self.scale = fits[0] if fits else 1.0 if height <= room + 3 else 0.5  # (pixel art shrinks by halves)
        self.update(state, self.monster, self.known)

    def update(self, state: GameState, monster: MonsterState, known: list[str]) -> None:
        """The fight as it is now: the foe (a copy), what it'll do next, how dangerous it looks, what you know."""
        self.monster = monster.model_copy(deep=True)
        self.seen = combat.foresee(state, self.content, monster)
        self.danger = combat.danger(state, self.content, monster)
        self.known = list(known)

    # --- what's drawn ---

    def _backdrop(self, state: GameState):
        """The room as it is, with nobody in it, in the dark: what the fight happens in front of."""
        if Image is None:
            return None
        room = state.room.model_copy(update={"monster": None})
        img = room_picture.Picture(state, self.content, self.width, 2 * self.rows, room).draw()
        r, g, b = DIM
        return img.point([int(v * r) for v in range(256)] + [int(v * g) for v in range(256)]
                         + [int(v * b) for v in range(256)])

    def _clips(self, room: int) -> dict:
        """The foe's own clips (sprites.clips), at the biggest size whose standing art (its idle) fits the `room` the
        stage has for it, or a pixel or two over (it may stand over its next move's row): none if it has no idle to
        fight in, or the stage is too small even for its smallest."""
        found = sprites.clips(self.monster.key)
        fits = [clip.size for clip in found.get("idle", ())
                if (box := sprites.art_box(clip.frames)) and box[3] - box[1] <= room + 2]
        if not fits:
            return {}
        return {name: clip for name, sizes in found.items() for clip in sizes if clip.size == fits[-1]}

    def _box(self) -> tuple | None:
        """The box round the foe's art in every frame, so trimming to it doesn't make it jump between frames."""
        found = sprites._strip(self.monster.key)
        boxes = [box for frame in found or () if (box := frame.getbbox())]
        if not boxes:
            return None
        pad = 2  # (room for a lunge, a glow, the stars round a dazed head)
        width, height = found[0].size
        return (max(0, min(b[0] for b in boxes) - pad), max(0, min(b[1] for b in boxes) - pad),
                min(width, max(b[2] for b in boxes) + pad), min(height, max(b[3] for b in boxes) + pad))

    def foe(self, frame: int = 0, pose: str = "idle", flash: bool = False, clip: str = "idle"):
        """The foe at the fight's size, in a pose (sprites.posed), white all over if `flash`; None without a sprite.
        With clips of its own, the frame is its `clip`'s, whole (see anchor): an idle's frames 0 and 1 are its loop's
        first and middle, the two the stage takes turns with while it stands; winding up a heavy blow, it stands in
        its `windup` clip if it has one (the Goblin King, his pan held high), glowing as any monster does."""
        if self.clips:
            name = "windup" if pose == "windup" and "windup" in self.clips else clip
            frames = self.clips.get(name, self.clips["idle"]).frames
            index = frame * max(1, len(frames) // 2) if name in ("idle", "windup") else frame
            img = sprites.posed(frames[index % len(frames)], pose, frame)
            return sprites._recolour(img, lambda r, g, b: (255, 255, 255)) if flash else img
        found = sprites._strip(self.monster.key)
        if not found or self.box is None:
            return None
        base = found[0] if pose == "death" else found[frame % len(found)]
        img = sprites.posed(base, pose, frame).crop(self.box)
        if flash:
            img = sprites._recolour(img, lambda r, g, b: (255, 255, 255))
        if self.scale == 0.5:
            img = sprites.halve(img)
        elif self.scale != 1.0:
            img = img.resize((round(img.width * self.scale), round(img.height * self.scale)), Image.NEAREST)
        return img

    def feet(self) -> int:
        """The pixel row the foe stands on: just over its banner."""
        return 2 * (self.rows - self.banner_rows) - 1

    def anchor(self, foe) -> tuple[int, int]:
        """Where its feet are in a picture of the foe, (the middle, the bottom row): its standing art's in a clip's
        frames (which are as their maker drew them, the space it drops in from and swings through and all), else the
        picture's own."""
        if self.clips and self.box:
            return (self.box[0] + self.box[2]) // 2, self.box[3] - 1
        return foe.width // 2, foe.height - 1

    def stature(self, foe) -> tuple[int, int]:
        """How wide and tall the foe stands, in pixels: for its pool of light, and its next move over its head."""
        if self.clips and self.box:
            return self.box[2] - self.box[0], self.box[3] - self.box[1]
        return foe.size

    def canvas(self, foe, offset: int = 0, pool: bool = True):
        """The dimmed room with the foe in it, `offset` pixels off the middle (coming in), on its pool of light."""
        canvas = self.back.convert("RGBA")
        if foe is None:
            return canvas
        ax, ay = self.anchor(foe)
        x, y = self.width // 2 - ax + offset, self.feet() - ay
        if pool:
            self._pool(canvas, self.width // 2 + offset, self.stature(foe)[0])
        canvas.paste(foe, (x, y), foe)
        return canvas

    def _pool(self, canvas, centre: int, wide: int) -> None:
        """Light pooled on the floor under the foe, brightest in the middle (an ellipse, dithered at its edge)."""
        px = canvas.load()
        rx, ry, feet = max(4, int(wide * 0.7)), 3, self.feet()
        for y in range(max(0, feet - ry), min(canvas.height, feet + 2)):
            for x in range(max(0, centre - rx), min(canvas.width, centre + rx + 1)):
                d = ((x - centre) / rx) ** 2 + ((y - feet) / ry) ** 2
                if d > 1 or (d > 0.6 and sprites.BAYER[y % 4][x % 4] < 8):
                    continue
                k = 0.7 * (1 - d)
                r, g, b, a = px[x, y]
                px[x, y] = (int(r + (POOL[0] - r) * k), int(g + (POOL[1] - g) * k), int(b + (POOL[2] - b) * k), a)

    def _text(self, canvas) -> list[Text]:
        return sprites.image_text(canvas, snap=True).split("\n")

    def still(self, frame: int = 0, pose: str = "idle", flash: bool = False, offset: int = 0,
              banner: bool = True, clip: str = "idle", card: int | None = None, glint: int | None = None) -> Text:
        """The fight as it stands: the foe in a pose, its next move over its head, its banner under it. Or, as a boss
        arrives, its name card (`card` letters of it spelled out so far, a `glint` along them: see _card)."""
        if self.back is None:
            return Text()
        foe = self.foe(frame, pose, flash, clip)
        lines = self._text(self.canvas(foe, offset))
        if card is not None:
            self._card(lines, card, glint)
        elif banner:
            self._intent(lines, foe, offset)
            self._banner(lines)
        return Text("\n", no_wrap=True, overflow="crop").join(lines)

    @property
    def called(self) -> bool:
        """Whether it's called out by name as it arrives, to the boss sting: a boss, or a guardian."""
        return self.boss or self.guardian

    def subtitle(self) -> str:
        """What its name card says it is, under its name: boss of the floor, or guardian of the way on."""
        if self.guardian:
            return "GUARDIAN OF THE STAIRS" if self.monster.warden else f"GUARDIAN OF {self.realm.upper()}"
        return f"BOSS OF {self.realm.upper()}" if self.realm else ""

    def title(self) -> str:
        """A boss's name as its card spells it: in capitals, spaced out if there's room."""
        name = plain_name(self.monster).upper()
        return " ".join(name) if 2 * len(name) + 10 <= self.width else name

    def _card(self, lines: list[Text], shown: int, glint: int | None = None) -> None:
        """A boss's (or a guardian's) name called out under it as it arrives, on a crimson band where its banner will
        be: spelled out letter by letter between two ✦, gilt rules running out to the stage's edges, and what it is
        under it once it's all there (subtitle); then a glint runs along the letters, as off gold."""
        first = len(lines) - self.banner_rows
        for row in range(first, len(lines)):
            lines[row] = Text(" " * self.width, style=Style(bgcolor=CARD))
        letters = self.title()
        name = Text()
        for i, ch in enumerate(letters):
            near = glint is not None and abs(i - glint) <= 1
            name.append(ch if i < shown else " ", style=Style(color=WHITE if near else GOLD, bold=True))
        rule = "━" * max(0, (self.width - len(letters) - 8) // 2)
        _write(lines, first, _on_band(Text.assemble((rule + " ", GILT), ("✦  ", RED), name, ("  ✦", RED),
                                                    (" " + rule, GILT)), CARD))
        if self.banner_rows == 2 and shown >= len(letters) and self.subtitle():
            _write(lines, first + 1, _on_band(Text(self.subtitle(), style=f"bold {GREY}"), CARD))

    def _called(self, beats: int) -> tuple[int, int | None, str]:
        """The name card `beats` frames after the boss lands: how many of its letters show (SPELL more a frame), where
        the glint is once they're all there, and the sound that frame cues (the sting as it lands, a tick for each
        frame of spelling)."""
        letters = len(self.title())
        spelled = -(-letters // SPELL)
        glint = SPELL * (beats - spelled) if beats >= spelled else None
        cue = STINGS[self.called] if beats == 0 else "dice_tick" if beats < spelled else ""
        return min(letters, SPELL * (beats + 1)), glint, cue

    def _intent(self, lines: list[Text], foe, offset: int) -> None:
        """Its next move (combat.foresee) over its head, in the colour of what it means."""
        seen = self.seen
        if seen is None or not self.top_rows:
            return
        ground, ink = INTENT_LOOK.get(seen.kind, (INK, WHITE))
        words = Text(f" {seen.said()} ", style=Style(color=ink, bgcolor=ground, bold=True))
        top = (self.feet() - (self.stature(foe)[1] if foe is not None else 0)) // 2
        _write(lines, max(0, top - 1), words, self.width // 2 + offset)

    def _banner(self, lines: list[Text]) -> None:
        """Under its feet: its traits, its name and how dangerous it looks; its health, how it is and what you know."""
        monster, width = self.monster, self.width
        first = len(lines) - self.banner_rows
        for row in range(first, len(lines)):
            lines[row] = _band(width)
        tags = traits(monster, self.content)
        name = Text()
        if tags:
            name.append(" · ".join(tags) + "  ", style=f"bold {ORANGE}")
        name.append(plain_name(monster), style=f"bold {WHITE}")
        name.append("  ")
        name.append_text(danger_marks(self.danger))
        health = hp_bar(monster.hp, monster.max_hp, max(8, min(24, width // 5)))
        how = "  ⛨ guarding" if monster.guarding else ""
        health.append(how, style=f"bold {BLUE}")
        if self.known:
            health.append(f"  weak to {', '.join(self.known)}", style="#5fe3ff")
        if self.banner_rows == 2:
            _write(lines, first, _on_band(name))
            _write(lines, first + 1, _on_band(health))
        else:
            _write(lines, first, _on_band(Text.assemble(name, "   ", health)))

    # --- moments ---

    def entrance(self, side: int = 1, steps: int = 7):
        """It comes in, frame by frame, each (the picture, seconds to show it, the sound it cues: "" for none), drawn
        as it's asked for so the first shows at once. With an entrance clip of its own (sprites.clips: the Goblin King
        drops in from above), that, at no more than sprites.CLIP_FPS frames a second; else from off the stage (`side`
        1 from the right, -1 the left) to the middle, fast then slowing. The fight's sting as it lands (a boss's, and
        its name called out after: the card spelled out to ticks, a glint along it); then its banner."""
        if self.back is None:
            return
        sting = STINGS[self.called]
        clip = self.clips.get("entrance")
        if clip is not None:
            every = max(1, round(clip.fps / sprites.CLIP_FPS))
            landed = None  # (the frames since it landed)
            for i in range(0, len(clip.frames), every):
                lands = bool(clip.land) and i <= clip.land < i + every
                landed = 0 if lands else landed + 1 if landed is not None else None
                if self.called and landed is not None:
                    shown, glint, cue = self._called(landed)
                    yield self.still(i, clip="entrance", card=shown, glint=glint), every / clip.fps, cue
                else:
                    yield self.still(i, clip="entrance", banner=False), every / clip.fps, sting if lands else ""
            yield self.still(), 0.0, "" if clip.land else sting
            return
        foe = self.foe()
        start = (self.width + (foe.width if foe is not None else 24)) // 2 + 2
        for i in range(steps):
            eased = 1 - (1 - (i + 1) / steps) ** 3
            yield self.still(offset=round(side * start * (1 - eased)), banner=False), 0.035, ""
        if self.called:  # (its name called out once it's there)
            for beat in range(-(-len(self.title()) // SPELL) + 10):
                shown, glint, cue = self._called(beat)
                yield self.still(beat // 4 % 2, card=shown, glint=glint), 0.07, cue
            yield self.still(), 0.0, ""
            return
        yield self.still(), 0.0, sting

    def swing(self):
        """Its own attack, if it has an attack clip (the Goblin King's swing of his pan, from his fall), frame by frame
        with its banner, each (picture, seconds), at no more than sprites.CLIP_FPS frames a second; none without."""
        clip = self.clips.get("attack")
        if clip is None or self.back is None:
            return
        every = max(1, round(clip.fps / sprites.CLIP_FPS))
        for i in range(0, len(clip.frames), every):
            yield self.still(i, clip="attack"), every / clip.fps

    def shatter(self, side: int = -1) -> list[Text]:
        """Its end: the sprite breaks into its pixels, flung away from the blow (`side` -1 to the left, 1 the right)
        and falling, fading as they go; the room behind it all along, and its banner gone dark."""
        foe = self.foe()
        if self.back is None or foe is None:
            return []
        ax, ay = self.anchor(foe)
        x0, y0 = self.width // 2 - ax, self.feet() - ay
        src = foe.load()
        bits = [(x, y, src[x, y]) for y in range(foe.height) for x in range(foe.width) if src[x, y][3] >= 128]
        frames = []
        for step in range(1, SHATTER_FRAMES + 1):
            canvas = self.back.convert("RGBA")
            px = canvas.load()
            fade = 1 - step / (SHATTER_FRAMES + 1)
            for x, y, (r, g, b, _) in bits:
                seed = (x * 73 + y * 151) % 97 / 97  # (each bit its own way, the same each time)
                if seed > fade + 0.15:
                    continue  # (gone)
                dx = round(-side * step * (0.6 + 1.6 * seed) * self.scale) if step > 1 else 0
                dy = round(step * step * (0.15 + 0.35 * seed) - step * (1.4 - seed))
                tx, ty = x0 + x + dx, y0 + y + dy
                if 0 <= tx < canvas.width and 0 <= ty < canvas.height:
                    k = 0.35 + 0.65 * fade
                    px[tx, ty] = (int(r * k + 255 * (1 - k) * (step < 3)), int(g * k + 255 * (1 - k) * (step < 3)),
                                  int(b * k + 255 * (1 - k) * (step < 3)), 255)
            lines = self._text(canvas)
            for row in range(len(lines) - self.banner_rows, len(lines)):
                lines[row] = _band(self.width)
            frames.append(Text("\n", no_wrap=True, overflow="crop").join(lines))
        return frames

    def empty(self) -> Text:
        """The dimmed room, nobody in it: under the spoils."""
        if self.back is None:
            return Text()
        lines = self._text(self.canvas(None))
        return Text("\n", no_wrap=True, overflow="crop").join(lines)


@dataclass
class Spoils:
    """What a fight paid, from its events (combat.defeat's): XP and how it was earned, the gold, the souls, the styles
    it was won in, what it dropped, and whether you went up a level."""

    name: str
    xp: int = 0
    souls: int = 0
    gold: int = 0
    styles: list[tuple[str, int, int]] = field(default_factory=list)  # (name, its XP, its gold)
    drops: list[str] = field(default_factory=list)
    levels: list[int] = field(default_factory=list)

    @classmethod
    def of(cls, events, name: str) -> Spoils | None:
        """The spoils in a turn's events, or None if nothing was beaten in it."""
        beaten = next((e for e in events if e.kind == "defeat" and "xp" in e.data), None)
        if beaten is None:
            return None
        spoils = cls(name, xp=beaten.data["xp"], souls=beaten.data.get("souls", 0))
        for event in events:
            if event.kind == "style":
                spoils.styles.append((event.data["name"], event.data["xp"], event.data["gold"]))
            elif event.kind == "loot" and "gold" in event.data:
                spoils.gold += event.data["gold"]
            elif event.kind == "drop" and event.data.get("item"):
                spoils.drops.append(event.data["item"])
            elif event.kind == "level":
                spoils.levels.append(event.data["level"])
        return spoils

    @property
    def all_xp(self) -> int:
        return self.xp + sum(xp for _, xp, _ in self.styles)

    @property
    def all_gold(self) -> int:
        return self.gold + sum(gold for _, _, gold in self.styles)


def xp_line(level: int, xp: int, cells: int) -> Text:
    """Your XP bar: how far into this level you are."""
    low = LEVEL_XP[level - 1] if level - 1 < len(LEVEL_XP) else LEVEL_XP[-1]
    high = LEVEL_XP[level] if level < len(LEVEL_XP) else None
    if high is None:
        return Text.assemble(("█" * cells, GOLD), (f" level {level}, the most there is", "bold"))
    filled = round(cells * (xp - low) / max(1, high - low))
    return Text.assemble(("█" * min(cells, filled), GOLD), ("█" * max(0, cells - filled), FAINT),
                         (f" {xp}/{high} XP", "bold"))


def spoils_text(back: Text, spoils: Spoils, content: Content, player_level: int, player_xp: int, step: int = 99,
                fill: float = 1.0) -> Text:
    """The spoils over the stage (`back`: the dimmed room): a heading, the XP bar filling (`fill` of the way from
    where it was to where it is) with the level-up when there was one, the gold and souls, each style, and the drops,
    one more for each `step` (the bar first, then the purse, then each thing: the caller sounds each as it comes)."""
    lines = back.split("\n")
    width, rows = len(lines[0].plain) if lines else 0, len(lines)
    body: list[Text] = [Text("✦ SPOILS ✦", style=f"bold {GOLD}"),
                        Text(f"{spoils.name} is beaten", style=f"bold {WHITE}")]
    before = player_xp - spoils.all_xp
    shown_xp = round(before + (player_xp - before) * fill)
    level = player_level
    while level > 1 and shown_xp < (LEVEL_XP[level - 1] if level - 1 < len(LEVEL_XP) else 0):
        level -= 1  # (the bar fills through the old level first)
    bar = xp_line(level, shown_xp, max(10, min(24, width // 4)))
    gain = Text(f"  +{spoils.xp} XP", style=f"bold {GOLD}")
    body.append(Text.assemble(bar, gain))
    if spoils.levels and fill >= 1.0:
        body.append(Text(f"▲ LEVEL {spoils.levels[-1]}! ▲", style=f"bold {INK} on {GOLD}"))
    if step >= 1:
        purse = Text()
        if spoils.all_gold:
            purse.append(f"¤ +{spoils.all_gold} gold", style=f"bold {ORANGE}")
        if spoils.souls:
            purse.append(("   " if purse.plain else "") + f"☽ +{spoils.souls} souls", style=f"bold {PURPLE}")
        if purse.plain:
            body.append(purse)
        for name, xp, gold in spoils.styles:
            body.append(Text(f"★ {name.upper()}! +{xp} XP, +{gold} gold", style=f"bold {GREEN}"))
    things = spoils.drops[:max(0, step - 1)]
    if things:
        row = Text()
        for key in things:
            row.append(("   " if row.plain else "") + f"◆ {content.item(key).name}",
                       style=f"bold {rarity(content, key)}")
        body.append(row)
    top = max(0, (rows - len(body)) // 2)
    for i, words in enumerate(body):
        if top + i < rows:
            lines[top + i] = _band(width)
            _write(lines, top + i, _on_band(Text.assemble(" ", words, " ")))
    return Text("\n", no_wrap=True, overflow="crop").join(lines)


def wipe(old: Text, new: Text, steps: int = 6, side: int = 1) -> list[Text]:
    """`new` sweeping across `old`, from the right (`side` 1) or the left (-1), a few columns more each step, with a
    bright seam where they meet: the stage going back to the room (and, later, one room to the next)."""
    olds, news = old.split("\n"), new.split("\n")
    width = max((len(line.plain) for line in [*olds, *news]), default=0)
    frames = []
    for step in range(1, steps + 1):
        cut = round(width * step / steps)
        rows = []
        for o, n in zip(olds, news):
            if side > 0:  # (the new from the right)
                edge = width - cut
                row = Text.assemble(o[:edge], n[edge:])
                seam = edge
            else:
                row = Text.assemble(n[:cut], o[cut:])
                seam = cut - 1
            if 0 <= seam < width and step < steps:
                row.stylize(Style(bgcolor=FAINT), seam, seam + 1)
            rows.append(row)
        frames.append(Text("\n", no_wrap=True, overflow="crop").join(rows))
    return frames
