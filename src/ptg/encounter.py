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

Each is plain half-block Text (Rich): the screen shows them in turn. Nothing here changes the game.

A fight against several foes (combat.foes) shows them all, each in its own place along the stage (its `place`: the
same place whoever you face), smaller the more there are: the one you face in the light, the others a little dimmer,
each with its next move over its head and its health on the banner's first row; the one you face's banner under
that. Any of them with clips of its own plays them at the size its slice of the stage takes: they come in together,
each stands in its own idle (its windup while a heavy blow's coming), and a turn's blows play each striker's attack
at once (`swing`: those without one lunge)."""

from __future__ import annotations

from dataclasses import InitVar, dataclass, field

from rich.style import Style
from rich.text import Text

from . import combat, loot, room_picture, sprites, statuses
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


def status_marks(monster: MonsterState) -> Text:
    """What's on a foe, after its health: each status's mark in its colour and its turns left ("♨2 ✚3"), dazed too."""
    marks = Text()
    for key, left in monster.statuses.items():
        status = statuses.DEFS.get(key)
        if status is not None:
            marks.append(f" {status.icon}{left}", style=f"bold {status.colour}")
    if monster.stunned:
        marks.append(f" {statuses.DEFS['stun'].icon}", style=f"bold {statuses.DEFS['stun'].colour}")
    return marks


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


@dataclass(frozen=True)
class Look:
    """A kind of foe's art among the others on the stage (Fight.look): its sprite's frames, the box round its art in
    all of them (in its idle's, if it has clips), the size the sprite's drawn at, and its own clips at the size it
    takes there."""

    frames: tuple
    box: tuple | None
    size: float
    clips: dict = field(default_factory=dict)


def _frame_of(clip, name: str, frame: int, tick: int | None = None):
    """A clip's frame for the stage: standing (an idle, a windup), its loop played through a frame a `tick` while the
    stage plays it at its own speed, or else frame 0 or 1 is its loop's first or middle (the two a still picture takes
    turns with); a moment (an entrance, an attack), its own frame, held on its last once it's over."""
    frames = clip.frames
    if name in ("idle", "windup"):
        return frames[(tick if tick is not None else frame * max(1, len(frames) // 2)) % len(frames)]
    return frames[min(frame, len(frames) - 1)]


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
    cry: str = ""  # its own sound as it lands, instead of the fight's sting (MonsterDef.cry: the Matriarch's screech)
    others: list = field(default_factory=list)  # the rest of the fight (copies), beside the one you face
    others_seen: list = field(default_factory=list)  # their next moves

    def __post_init__(self, state: GameState) -> None:
        self.banner_rows = 2 if self.rows >= 10 else 1
        self.top_rows = 1 if self.rows >= 7 else 0
        known = self.content.monster(self.monster.key)
        self.boss, self.guardian = known.boss, "guardian" in known.tags and not known.boss
        self.cry = known.cry
        self.realm = self.content.themes[state.theme].name if state.theme in self.content.themes else ""
        self.back = self._backdrop(state)
        room = 2 * (self.rows - self.banner_rows) - 1  # (as tall as it is, its next move over its head)
        crowd = len([m for m in state.room.others if m.hostile and m.hp > 0])
        self.looks: dict[str, Look] = {}  # each kind of foe's art among the others (look), worked out once
        self.share = FOE_SHARE if not crowd else 0.95 / (crowd + 1)  # (each foe's slice of the stage)
        self.wide = self.width * self.share * 1.3 if crowd else None  # (in a crowd, as wide as its slice, or a bit)
        # (in a crowd, every foe's clips at one size, the biggest they all fit, so they keep their sizes side by side)
        self.most = min((size for m in [self.monster, *state.room.others] if m.hostile and m.hp > 0
                         if (size := self._fits(m.key, room, self.wide))), default=0) if crowd else 0
        self.clips = self._clips_for(self.monster.key, room, self.wide)
        if self.clips:  # (drawn as made: placed by where its standing body is in their frames)
            self.box = sprites.stance(self.monster.key, self.clips["idle"].size)
        else:
            self.box = self._box()
            height = self.box[3] - self.box[1] if self.box else 24
            width = self.box[2] - self.box[0] if self.box else 24
            self.scale = self._fit(width, height, room)
        self.update(state, self.monster, self.known)

    def _fit(self, width: int, height: int, room: int) -> float:
        """How big a foe of this size is drawn: twice, or half again, where there's room (with a row clear for that),
        as it is if it fits the stage's height (or a pixel or two over), else halved (pixel art shrinks by halves);
        in a crowd, no wider than its slice of the stage."""
        fits = [s for s in (2.0, 1.5) if height * s <= room - 2 and width * s <= self.width * self.share]
        if fits:
            return fits[0]
        return 1.0 if height <= room + 3 and width <= self.width * self.share * 1.3 else 0.5

    def update(self, state: GameState, monster: MonsterState, known: list[str]) -> None:
        """The fight as it is now: the foe (a copy), what it'll do next, how dangerous it looks, what you know; and the
        rest of the fight beside it, with their next moves."""
        self.monster = monster.model_copy(deep=True)
        self.seen = combat.foresee(state, self.content, monster)
        self.danger = combat.danger(state, self.content, monster)
        self.known = list(known)
        self.others = [m.model_copy(deep=True) for m in state.room.others if m.hostile and m.hp > 0]
        self.others_seen = [combat.foresee(state, self.content, m) for m in state.room.others
                            if m.hostile and m.hp > 0]

    # --- a crowd: its places along the stage ---

    def lineup(self) -> list[MonsterState]:
        """Everyone in the fight in their places, left to right: the one you face among them."""
        return sorted([self.monster, *self.others], key=lambda m: m.place)

    def centre(self, monster: MonsterState | None = None) -> int:
        """The middle of a foe's place on the stage, in pixels (the one you face, unless it says): the stage's middle,
        alone; in a crowd, its slice's, moved in from the stage's edge if it's too wide to stand there whole."""
        monster = monster or self.monster
        line = self.lineup()
        index = next((i for i, m in enumerate(line) if m.place == monster.place and m.name == monster.name), 0)
        middle = round((index + 0.5) * self.width / len(line))
        if len(line) == 1:
            return middle
        half = (self._wide_as(monster) + 1) // 2
        return max(half, min(self.width - half, middle))

    def _wide_as(self, monster: MonsterState) -> int:
        """How wide a foe in a crowd stands, in pixels: the one you face's art, or one of the others' (look)."""
        if monster.place == self.monster.place and monster.name == self.monster.name:
            if self.clips and self.box:
                return self.box[2] - self.box[0]
            return round((self.box[2] - self.box[0]) * self.scale) if self.box else 0
        look = self.look(monster.key)
        if look.box is None:
            return 0
        wide = look.box[2] - look.box[0]
        return wide if look.clips else round(wide * look.size)

    def look(self, key: str) -> Look:
        """A kind of foe's art among the others, worked out once: its own clips at the size its slice of the stage
        takes (as the one you face's are), or else its sprite at the size it's drawn there."""
        if key not in self.looks:
            room = 2 * (self.rows - self.banner_rows) - 1
            clips = self._clips_for(key, room, self.wide)
            if clips:
                self.looks[key] = Look((), sprites.stance(key, clips["idle"].size), 1.0, clips)
            else:
                found = sprites._strip(key) or ()
                box = sprites.art_box(found)
                size = self._fit(box[2] - box[0], box[3] - box[1], room) if box else 1.0
                self.looks[key] = Look(found, box, size)
        return self.looks[key]

    def other(self, monster: MonsterState, frame: int = 0, pose: str = "idle", clip: str = "idle",
              tick: int | None = None):
        """One of the others as it is now, a little dimmer than the one you face, and where its feet are in the picture
        (x, y): in its own clip if it has them (`clip`'s frame `frame`; while a heavy blow's coming, its windup's),
        drawn as made, or else its sprite in a pose (sprites.posed), at its size among them. None, with neither."""
        look = self.look(monster.key)
        if look.box is None:
            return None
        if look.clips:
            name = "windup" if pose == "windup" and "windup" in look.clips else clip
            img = sprites.posed(_frame_of(look.clips.get(name, look.clips["idle"]), name, frame, tick),
                                "idle" if pose == "lunge" else pose, frame)
            feet = ((look.box[0] + look.box[2]) // 2, look.box[3] - 1)
        else:
            if not look.frames:
                return None
            img = sprites.posed(look.frames[frame % len(look.frames)], pose, frame).crop(look.box)
            if look.size == 0.5:
                img = sprites.halve(img)
            elif look.size != 1.0:
                img = img.resize((round(img.width * look.size), round(img.height * look.size)), Image.NEAREST)
            feet = (img.width // 2, img.height - 1)
        return sprites._recolour(img, lambda r, g, b: (int(r * 0.72), int(g * 0.72), int(b * 0.8))), feet

    def stands(self, monster: MonsterState) -> int:
        """How tall one of the others stands, in pixels: for its next move over its head."""
        look = self.look(monster.key)
        if look.box is None:
            return 0
        tall = look.box[3] - look.box[1]
        return tall if look.clips else round(tall * look.size)

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

    def _clips_for(self, key: str, room: int, wide: float | None = None) -> dict:
        """A foe's own clips (sprites.clips), at the biggest size it fits (_fits), and in a crowd no bigger than the
        crowd's (`most`): none if it has no idle to fight in, or the stage is too small even for its smallest."""
        size = min(self._fits(key, room, wide), self.most or 10 ** 6)
        return {name: clip for name, sizes in sprites.clips(key).items() for clip in sizes if clip.size == size}

    @staticmethod
    def _fits(key: str, room: int, wide: float | None = None) -> int:
        """The biggest of a foe's clips' sizes whose standing body (sprites.stance, in its idle) fits the `room` the
        stage has for it, or a pixel or two over (it may stand over its next move's row), and in a crowd its slice of
        the stage (`wide` pixels); 0 if none does, or it has none."""
        fits = [clip.size for clip in sprites.clips(key).get("idle", ())
                if (box := sprites.stance(key, clip.size)) and box[3] - box[1] <= room + 2
                and (wide is None or box[2] - box[0] <= wide)]
        return fits[-1] if fits else 0

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

    def foe(self, frame: int = 0, pose: str = "idle", flash: bool = False, clip: str = "idle",
            tick: int | None = None):
        """The foe at the fight's size, in a pose (sprites.posed), white all over if `flash`; None without a sprite.
        With clips of its own, the frame is its `clip`'s, whole (see anchor): an idle's frames 0 and 1 are its loop's
        first and middle, the two the stage takes turns with while it stands; winding up a heavy blow, it stands in
        its `windup` clip if it has one (the Goblin King, his pan held high), glowing as any monster does."""
        if self.clips:
            name = "windup" if pose == "windup" and "windup" in self.clips else clip
            img = sprites.posed(_frame_of(self.clips.get(name, self.clips["idle"]), name, frame, tick), pose, frame)
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

    def canvas(self, foe, offset: int = 0, pool: bool = True, frame: int = 0, clip: str = "idle",
               striking: frozenset = frozenset(), tick: int | None = None):
        """The dimmed room with the foe in it at its place (the middle, alone), `offset` pixels off it (coming in), on
        its pool of light; the others in theirs (see _crowd)."""
        canvas = self.back.convert("RGBA")
        self._crowd(canvas, frame, clip, striking, tick)
        if foe is None:
            return canvas
        ax, ay = self.anchor(foe)
        x, y = self.centre() - ax + offset, self.feet() - ay
        if pool:
            self._pool(canvas, self.centre() + offset, self.stature(foe)[0])
        canvas.paste(foe, (x, y), foe)
        return canvas

    def _crowd(self, canvas, frame: int = 0, clip: str = "idle", striking: frozenset = frozenset(),
               tick: int | None = None) -> None:
        """The others, each standing in its place: winding up while a heavy blow's coming, stars round its head while
        it's reeling; coming in as the one you face does (`clip` "entrance": its own entrance, if it has one), and
        going for you in its own attack (or a lunge) if its place is one of those `striking`."""
        for monster, seen in zip(self.others, self.others_seen):
            pose = {"heavy": "windup", "reeling": "dizzy"}.get(seen.kind if seen else "", "idle")
            own = "entrance" if clip == "entrance" else "attack" if monster.place in striking else "idle"
            if own == "entrance":
                pose = "idle"  # (coming in, whatever it'll do next)
            elif own == "attack":
                pose = "lunge" if frame < 4 else "idle"  # (without an attack of its own: a lunge, then back)
            drawn = self.other(monster, frame, pose, own, tick)
            if drawn is not None:
                img, (x, y) = drawn
                canvas.paste(img, (self.centre(monster) - x, self.feet() - y), img)

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
              banner: bool = True, clip: str = "idle", card: int | None = None, glint: int | None = None,
              striking: frozenset = frozenset(), tick: int | None = None) -> Text:
        """The fight as it stands: the foe in a pose, its next move over its head, its banner under it; the others in
        theirs (those `striking` going for you). Or, as a boss arrives, its name card (`card` letters of it spelled
        out so far, a `glint` along them: see _card). With a `tick`, every foe's own idle (or windup) is that far
        through its loop: the stage playing them at their own speed (`loops`)."""
        if self.back is None:
            return Text()
        foe = self.foe(frame, pose, flash, clip, tick)
        lines = self._text(self.canvas(foe, offset, frame=frame, clip=clip, striking=striking, tick=tick))
        if card is not None:
            self._card(lines, card, glint)
        elif banner:
            self._intent(lines, foe, offset)
            self._banner(lines)
        return Text("\n", no_wrap=True, overflow="crop").join(lines)

    def loops(self) -> bool:
        """Whether any foe here has clips of its own to stand in: the stage plays their loops through, a frame a tick
        (still's `tick`), rather than taking turns with two pictures."""
        return bool(self.clips) or any(self.look(m.key).clips for m in self.others)

    @property
    def sting(self) -> str:
        """The sound as it lands: its own cry, or the fight's sting (a boss's, deeper)."""
        return self.cry or STINGS[self.called]

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
        cue = self.sting if beats == 0 else "dice_tick" if beats < spelled else ""
        return min(letters, SPELL * (beats + 1)), glint, cue

    def _intent(self, lines: list[Text], foe, offset: int) -> None:
        """Its next move (combat.foresee) over its head, in the colour of what it means."""
        seen = self.seen
        if seen is None or not self.top_rows:
            return
        ground, ink = INTENT_LOOK.get(seen.kind, (INK, WHITE))
        said = f"▼ {seen.said()}" if self.others else seen.said()  # (in a crowd, which is the one you face)
        words = Text(f" {said} ", style=Style(color=ink, bgcolor=ground, bold=True))
        top = (self.feet() - (self.stature(foe)[1] if foe is not None else 0)) // 2
        _write(lines, max(0, top - 1), words, self.centre() + offset)
        for monster, theirs in zip(self.others, self.others_seen):  # (the others': their mark, and its damage)
            if theirs is None:
                continue
            ground, ink = INTENT_LOOK.get(theirs.kind, (INK, WHITE))
            head = (self.feet() - self.stands(monster)) // 2
            short = theirs.mark + (f" {theirs.low}-{theirs.high}" if theirs.high else f" {theirs.words}".rstrip())
            _write(lines, max(0, head - 1), Text(f" {short} ", style=Style(color=ink, bgcolor=ground)),
                   self.centre(monster))

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
        health.append_text(status_marks(monster))
        if self.known:
            health.append(f"  weak to {', '.join(self.known)}", style="#5fe3ff")
        if self.others and self.banner_rows == 2:  # (each foe's health under it; then the one you face's banner)
            self._healths(lines, first)
            _write(lines, first + 1, _on_band(Text.assemble(name, "   ", health)))
            return
        if self.banner_rows == 2:
            _write(lines, first, _on_band(name))
            _write(lines, first + 1, _on_band(health))
        else:
            _write(lines, first, _on_band(Text.assemble(name, "   ", health)))

    def _healths(self, lines: list[Text], row: int) -> None:
        """Every foe's health on the banner's first row, each under its place: the one you face's bright, with ▶◀."""
        slot = max(8, self.width // len(self.lineup()) - 2)
        for monster in self.lineup():
            facing = monster.place == self.monster.place and monster.name == self.monster.name
            cells = max(4, min(10, slot - 8))
            bar = hp_bar(monster.hp, monster.max_hp, cells, RED if facing else "#a22633")
            bar.append_text(status_marks(monster))
            words = Text.assemble(("▶" if facing else " ", f"bold {GOLD}"), bar, ("◀" if facing else " ",
                                                                                   f"bold {GOLD}"))
            _write(lines, row, _on_band(words), self.centre(monster))

    # --- moments ---

    def entrance(self, side: int = 1, steps: int = 7, quiet: bool = False):
        """It comes in, frame by frame, each (the picture, seconds to show it, the sound it cues: "" for none), drawn
        as it's asked for so the first shows at once. With an entrance clip of its own (sprites.clips: the Goblin King
        drops in from above), that, at no more than sprites.CLIP_FPS frames a second; else from off the stage (`side`
        1 from the right, -1 the left) to the middle, fast then slowing. The fight's sting as it lands (a boss's, and
        its name called out after: the card spelled out to ticks, a glint along it); then its banner. `quiet`: no
        sting and no card (it's been called out already, big: ui/boss_intro.py)."""
        if self.back is None:
            return
        if quiet:
            yield from ((frame, seconds, "") for frame, seconds, cue in self._entrance(side, steps, called=False))
            return
        yield from self._entrance(side, steps, self.called)

    def _entrance(self, side: int, steps: int, called: bool):
        sting = self.sting
        clip = self.clips.get("entrance")
        if clip is not None:
            every = max(1, round(clip.fps / sprites.CLIP_FPS))
            landed = None  # (the frames since it landed)
            for i in range(0, len(clip.frames), every):
                lands = bool(clip.land) and i <= clip.land < i + every
                landed = 0 if lands else landed + 1 if landed is not None else None
                if called and landed is not None:
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
        if called:  # (its name called out once it's there)
            for beat in range(-(-len(self.title()) // SPELL) + 10):
                shown, glint, cue = self._called(beat)
                yield self.still(beat // 4 % 2, card=shown, glint=glint), 0.07, cue
            yield self.still(), 0.0, ""
            return
        yield self.still(), 0.0, sting

    def rise(self, side: int = 1, steps: int = 7):
        """Its entrance backwards (a spike: ui/boss_intro.py): from standing, up and away the way it came, frame by
        frame without its banner, each (the picture, seconds). With clips, every foe's entrance run back from the last
        of them to land (the others with it); without, a sweep back off the stage (`side`)."""
        if self.back is None:
            return
        clip = self.clips.get("entrance")
        if clip is None:
            foe = self.foe()
            start = (self.width + (foe.width if foe is not None else 24)) // 2 + 2
            for i in range(steps):
                eased = ((i + 1) / steps) ** 3
                yield self.still(offset=round(side * start * eased), banner=False), 0.035
            return
        lands = [clip.land] + [look.clips["entrance"].land for m in self.others
                               if "entrance" in (look := self.look(m.key)).clips]
        every = max(1, round(clip.fps / sprites.CLIP_FPS))
        for i in range(max(lands), -1, -every):
            yield self.still(i, clip="entrance", banner=False), every / clip.fps

    def swing(self, striking=None, pose: str = "idle"):
        """The turn's blows, frame by frame with the banner, each (picture, seconds): every foe that went for you
        (`striking`: their places; the one you face alone, if it isn't said) in its own attack clip (the Goblin King's
        swing of his pan, from his fall), all at once, those without one lunging, at no more than sprites.CLIP_FPS
        frames a second; the one you face in its `pose` if it isn't one of them. None if none has an attack of its
        own."""
        striking = frozenset({self.monster.place} if striking is None else striking)
        facing = self.monster.place in striking
        own = facing and "attack" in self.clips
        clips = [self.clips["attack"]] if own else []
        clips += [look.clips["attack"] for m in self.others if m.place in striking
                  and "attack" in (look := self.look(m.key)).clips]
        if not clips or self.back is None:
            return
        fps = max(clip.fps for clip in clips)
        every = max(1, round(fps / sprites.CLIP_FPS))
        for step, i in enumerate(range(0, max(len(clip.frames) for clip in clips), every)):
            if own:
                yield self.still(i, clip="attack", striking=striking), every / fps
            elif facing:  # (it has no attack of its own: it lunges, then stands)
                yield self.still(step % 2, "lunge" if step < 2 else "idle", striking=striking), every / fps
            else:
                yield self.still(0, pose, striking=striking), every / fps

    def shatter(self, side: int = -1):
        """Its end, frame by frame (each drawn as it's asked for): the sprite breaks into its pixels, flung away from
        the blow (`side` -1 to the left, 1 the right) and falling, fading as they go; the room behind it all along,
        and its banner gone dark."""
        foe = self.foe()
        if self.back is None or foe is None:
            return
        ax, ay = self.anchor(foe)
        x0, y0 = self.centre() - ax, self.feet() - ay
        src = foe.load()
        bits = [(x, y, src[x, y]) for y in range(foe.height) for x in range(foe.width) if src[x, y][3] >= 128]
        for step in range(1, SHATTER_FRAMES + 1):
            canvas = self.back.convert("RGBA")
            self._crowd(canvas)
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
            yield Text("\n", no_wrap=True, overflow="crop").join(lines)

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
