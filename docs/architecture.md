# Architecture

How the software is built: its layers, how a turn flows through them, where state lives, and where to extend it.
For the game's design see `docs/plans/game-design.md`; for writing story events, `docs/writing-events.md`.

Keep this current: when a module's job changes, or a new one arrives, update its row here in the same commit.

## The one rule

**The engine owns the facts; the language model owns the words.** (`ptg/__init__.py`)

Everything that can be true or false (positions, HP, dice, what's in a room, what you carry) is decided by plain
Python from seeded randomness. A language model is used only to *read* what the player typed (into a structured
intent the engine checks) and to *write* prose about events the engine already resolved. Every model call has a
deterministic fallback, so the whole game runs offline.

## Layers

```
 ┌──────────────────────────────────────────────────────────────────────────────┐
 │ Front ends   ui/ (Textual: terminal app)   serve.py (browser, textual-serve)  │
 │              cli.py --plain (text mode)    ui/debug.py (F12 debug app)        │
 ├──────────────────────────────────────────────────────────────────────────────┤
 │ Session      game.py  Game: begin() → reroll() → finish()                     │
 │              story/  authored events (Markdown) watched each turn             │
 ├───────────────────────────┬──────────────────────────────────────────────────┤
 │ Language (llm/)           │ Rules engine                                      │
 │  interpreter.py  text→Intent  rules.py      actions, perform(), facts        │
 │  narrator.py     events→prose combat.py     fights, intents, death           │
 │  guard.py        prose vs facts interactions.py  the (verb, item, target) grid│
 │  prompts.py      snapshots    creative.py   free-text stunts, clamped        │
 │  extras.py       lore, recaps inventory.py  every change of hands            │
 │  backends: openai_compat,     npcs.py · powers.py · loot.py · dice.py ·       │
 │            anthropic, offline outcome.py · sheet.py · scene.py · glossary.py │
 │                               statuses.py (poison...) · hazards.py (Norfel)  │
 ├───────────────────────────┴──────────────────────────────────────────────────┤
 │ World        world.py (seeded floors) · layout.py (floor plans)              │
 │              room_picture.py (rooms drawn in code) · sprites.py (pixel art)  │
 ├──────────────────────────────────────────────────────────────────────────────┤
 │ Data         models.py (GameState, pydantic) · content.py (loads data/)      │
 │              data/*.toml, art.txt, story/*.md, sprites/*.png, sounds/*.wav   │
 │              integrity.py (signed data) · library.py (the Maker's in/out)    │
 ├──────────────────────────────────────────────────────────────────────────────┤
 │ Persistence  config.py (~/.ptg: config.json, saves/*.json, llm.log)          │
 │              profile.py (~/.ptg/profile.db, SQLite: everything across runs)  │
 └──────────────────────────────────────────────────────────────────────────────┘
```

Dependencies point downward only: the rules never import the UI or the language layer; the UI never changes state
except through `Game`.

## A turn

```
player types or clicks
   │
   ▼
Game.begin(raw, action?)                                   game.py
   ├─ a scene running?  story engine reads the input       story/engine.py
   ├─ a numbered choice or a button?  → that Action        (no model call)
   └─ free text  → interpreter: local matcher first,       llm/interpreter.py
                   then the model (JSON), else keywords     → Intent (intent.py)
   │
   ▼
resolve the Intent                                         rules.py
   ├─ action      → rules.perform(state, content, id)      → Events (events.py)
   ├─ creative    → creative.perform_creative: props checked, effects clamped, rolled
   └─ flavor      → told, changes nothing
   + story.after_turn: authored moments that fire on these events
   │
   ▼  Pending: the events, the primary roll
UI shows the dice; Fate may reroll (state is rewound)     ui/dice.py, Game.reroll()
   │
   ▼
Game.finish(on_text)
   ├─ narrator: a fresh snapshot of facts + events → streamed prose   llm/narrator.py, prompts.py
   │     guard drops any sentence that contradicts the facts          llm/guard.py
   │     offline: prose stitched from the events themselves
   ├─ log (state.log, state.journal), profile (bestiary, turn log)    profile.py
   └─ autosave (config.save_game)
```

Each turn sends the model a **small fresh snapshot** (prompts.py), never a growing chat history, so long runs cost
the same per turn and a weak local model stays on track.

## State

| What | Where | Lifetime |
|---|---|---|
| The run: rooms, player, monsters, log, journal, quests, flags | `models.GameState` (pydantic) → `~/.ptg/saves/autosave.json` | one run; saved every turn |
| Settings | `config.Config` → `~/.ptg/config.json` | until changed |
| Across runs: souls, unlocks, Hall of Legends, bestiary, ghosts, secrets, story marks, **every turn's log** (`turns` table) | `profile.Profile` → `~/.ptg/profile.db` (SQLite) | forever |
| Model traffic | `~/.ptg/llm.log` | appended |
| The game's content | `src/ptg/data/` (TOML, Markdown, PNG, WAV), loaded once by `content.load_content()` | shipped, signed |

`PTG_HOME` moves `~/.ptg`; `ptg serve` gives each player their own `PTG_HOME` under its data folder (`PTG_DATA`).

**Determinism.** `world.generate(seed)` builds the same dungeon for the same seed. Dice come from `dice.py`'s
per-turn streams, seeded from the run's seed and labels, so a save replays identically and a Fate reroll is a real
rewind. Tests rely on this (`tests/bot.py` games are compared run to run).

## Content and the Maker

- **Game data** lives in `src/ptg/data/`: `items.toml`, `monsters.toml`, `themes.toml`, `rooms.toml`, `perks.toml`,
  `unlocks.toml`, `tags.toml`, `dialogue.toml`, `art.txt` (ASCII art), `story/*.md`, sprites and sounds.
  `content.py` loads and validates it into frozen dataclasses (`ItemDef`, `MonsterDef`…).
- **Integrity**: `data/manifest.json` fingerprints the data files (`integrity.py`). After editing data, run
  `uv run python -m ptg.integrity --sign` and `uv run ptg export`, or the game marks runs as modded (the "Hackerman"
  secret).
- **The Monster & Item Maker** (`docs/maker/index.html`, a static page) is where the kids draw and describe things.
  `ptg export` writes `docs/maker/library.json` for it; `ptg import` brings creations back (from a link, a file, the
  Maker's saves or GitHub issues), writing sprites and TOML entries, checking the game still loads, and re-signing.
  `ptg maker` (`maker.py`) serves the page on this computer with a Claude panel: the page runs Claude's tools on its
  own boards, and the server holds the key, makes each call, renders the fight poses and runs the game's art tests
  and importer as a dry run.
- **Loot, NPCs and powers are data-driven**: a new item drops by its role and tier (`loot.py`); what an item does is
  a list of named powers (`powers.py`); characters are tagged `npc` and given behaviour in `npcs.py`.
- **Statuses are data too** (`statuses.toml`, `statuses.py`): a status says when it ticks (a step, a fight's turn),
  what a tick costs, whether it can kill, what it takes off your rolls, and whether a shrine cures it. Items say what
  they do about one: `cures` it (used up), `guards` against the next few, `wards` it off while they work for you.
  `statuses.inflict` is the one way any status takes hold, so a new one is a row and its sources; the turn puts its
  penalty on every roll of yours (`dice.HINDERED`, set by `rules.perform`).
- **Floors**: a theme's `floor` pins it to one (Norfel to 4) and its `status` makes it that status's floor (shops,
  a shrine, Granny's offer a floor above). Norfel's river and vent are placed by `hazards.py`, as choices, never as
  rolls on the way in.
- **Story events** are Markdown with a small header (`story/parser.py` checks them against the content, failing
  loudly with a file and line).

## Language models

- `llm/base.py` is the interface: **structured JSON** (for the interpreter and extras) and **streamed prose** (for
  the narrator). Backends: any OpenAI-compatible server (`openai_compat.py`: LM Studio, Ollama, Apple Intelligence
  through apfel, llama.cpp, vLLM, OpenRouter), Claude (`anthropic_backend.py`, the `claude` extra), or none (offline).
- **Interpreter** (`interpreter.py`): matches obvious commands locally; otherwise asks the model for an `Intent`
  naming only things in the room's `RoomView` (`scene.py`), so "the rat" is never a guess. Falls back to keywords.
- **Narrator** (`narrator.py`) with **guard** (`guard.py`): prose is checked against the facts a sentence at a time
  as it streams. A sentence that breaks a rule (invented exits, items or monsters, talking about "the player",
  asking what you'll do) is left out; if nothing survives, the facts themselves are told. Dropped sentences and why
  go to `llm.log`.
- **Extras** (`extras.py`): the suggested trick, bestiary lore, epitaphs, recaps; each has a plain fallback and runs
  in the background.
- `llm/check.py` scores a model on fixed situations (the debug app runs it).

## Front ends

- **Textual app** (`ui/app.py`, `PTGApp`): title, settings, campfire hub, the game screen, panels and the debug app.
  Styles in `ui/app.tcss`, palette in `ui/theme.py`.
- **Three game screens**, chosen by `Config.layout` and the terminal's size (`ui/tabs.game_screen`):
  - `ui/game_screen.py` **GameScreen**, the classic layout, laid out by `ui/plan.py` for any size (one column on a
    phone);
  - `ui/tabs.py` **TabsScreen**, the desktop layout (story and decision on the left; the room, Here and tabbed panes
    on the right). It subclasses GameScreen: turns, dice, animations and the story are shared; only layout and
    panes differ.
  - `ui/grid.py` **GridScreen**, a fixed grid (every box sized from the screen alone, `grid.share`, and lined up with
    the one beside it): the picture and the map across the top; under them the story, the decision beside it (six
    big buttons, a fight's or the room's, the compass, and your things as cards) and Here in sections with Lately
    under them; under the story instead on a narrower screen. Its Map panel, **ChartScreen**, draws the floor on
    parchment (`ui/parchment.py`, pixels in half blocks with names in ink over them), or as a chart (`grid.chart`).
    Each part is drawn again only when what it shows changes, the buttons, the compass's cells and Lately in place,
    and a part rebuilt is swapped in one batch (`GridScreen.swap`): a box emptied and filled again showed as text
    flashing off and on. Also a GameScreen underneath.
- **Widgets** (`ui/widgets.py`): the HUD, `Picture` (the one way anything with a sprite is drawn), choices, the dice
  line. `ui/here.py` builds the Here tiles; `ui/panels.py` the pop-up panels (inventory, sheet, map, bestiary,
  journal, shop, cards).
- **Pictures**: sprites are PNG strips drawn as half-block characters (`sprites.py`); rooms are drawn in code from
  the room itself (`room_picture.py`); the d20 is drawn in code (`dice_art.py`), and so are the dice screen's big
  pixel letters (its target and verdict: `lettering`) and a critical's burst of light; so is the title's castle in the
  storm (`title_scene.py`: materials and shades, coloured by the light, so one drawing gives the dark and the
  flash). Its frames are all made before it plays, as ready-made Strips (`ui/storm.py`): a Static handed a frame as
  text measures and lays it out again every time, and the rain hiccupped. `tools/build_sprites.py` and
  `tools/build_sounds.py` generate the built-in art and 8-bit sounds (`sound.py` plays them without blocking, and loops a moment's sound as music, crossfading from one to the next: the title's, a floor's, a fight's).
- **Browser**: `ptg serve` (`serve.py`, on textual-serve) runs one game per tab behind a page that asks who's
  playing; `web/app_index.html` fits phones. Deployed with the `Dockerfile` (Render). Sound plays in the page, not
  on the server. Each game runs with `PTG_SOUND=web`, so its sound engine sends each sound as a message through
  Textual's web driver (`sound.Browser`). `serve.py` passes those messages on to the page (textual-serve would drop
  them) and serves the WAVs at `/sounds/<stamp>/`, whose address changes when any sound does, so browsers keep
  them. The page plays them with Web Audio, decoded as the mixer decodes them.
- **Plain text mode**: `ptg --plain` drives the same `Game` from a prompt loop in `cli.py`.

## Drawing: text and pixel art in a terminal

**The terminal is a grid of character cells**, not pixels. Each cell holds one character, a foreground colour, a
background colour and a style. Everything on screen, words and art alike, is characters in cells, in 24-bit colour.

**The stack**, top to bottom:

1. Our code builds **Rich `Text`**: runs of characters with styles (a story line, the HUD, a sprite).
2. **Textual widgets** hold it, laid out by CSS (`ui/app.tcss`) into boxes.
3. Textual's **compositor** merges the widgets into lines of styled segments, one per row.
4. The **driver** writes ANSI escape sequences, **only for the lines that changed** since the last frame (which is
   why changing a tab doesn't repaint the room's picture).
5. The **terminal emulator** draws the cells as glyphs, usually on the GPU. In a browser (`ptg serve`), the same
   output goes over a websocket to **xterm.js**.

**Pixel art: half blocks** (`sprites.py`). A cell shows `▀` with its foreground set to the top pixel's colour and
its background to the bottom pixel's: one cell, two pixels, and since a cell is about twice as tall as it's wide,
the pixels come out square. A 24×24 sprite is 24 columns × 12 rows; a small 12px one is 12 × 6. A transparent pixel
has no colour (`▀` with no background, `▄` alone, or a space). Sprites are PNG strips in `data/sprites/` (48×24 is two
frames), with hand-made small versions in `data/sprites/small/`. Effects (a hit's flash, a lunge's red, the death
dissolve's ordered dither) recolour pixels in a few fixed shades. A floor's **splash art** (its card's picture,
`ui/panels.py` FloorScreen) is in `data/splash/<theme>/` in several widths up to 160, each made from the original
picture by `tools/make_splash.py`; the card draws the widest that fits the screen round its words.

**Room pictures are drawn in code** (`room_picture.py`), fresh for each room at whatever size the stage has: one-point
perspective from the doorway you came in by; the dungeon's own look (`Look`: bricks and candles, timber and torches,
marble and sky); textures from noise and Bayer dithering; light falling off from candles, torches and glowing things;
props from small hand-made grids; fixtures, monsters and items placed from the floor plan (`layout.py`), scaled by
halves and nudged aside so nothing you can act on is hidden or cut off. The result becomes half-block `Text` like any
sprite. The d20 is drawn the same way (`dice_art.py`).

**Animation** (`ui/widgets.py`). `Picture` is the one widget anything with a sprite is drawn in. One `PictureClock`
per app beats every 0.15 s (flames, glints) or 0.6 s (idle breathing and bobbing), and a picture takes a frame only
while it's in sight, so the screen changes once a beat, not once per picture. Fight moments (flash, lunge, death)
play as frame sequences on the monster's picture.

**Words that do things.** Story lines are `Text` whose highlighted terms carry metadata in their style: a tooltip
for hover, and a term that a click turns into its card (`StoryLine`, `glossary.py`). The map's rooms carry their names
the same way, and a room you can get back to the room's id ("travel"), which a click turns into the trip; as the
mouse comes to one, the map draws it in gold (its screen's `hover_room`). Neither is a Textual `@click` link: those are
underlined and repainted in the theme's link colour, a room's whole frame with them.
A `StoryLine` measures itself after each update and resize, and asks to be laid out again if it's shorter than its
words: now and then one kept a height from before all its words came, and lost its end under the next line.

**Two constraints the code works around:**

- **The GPU glyph cache.** GPU terminals (xterm.js above all) cache each character in each pair of colours they meet;
  pixel art makes thousands, and when the cache overflows, letters and art come out garbled or tiny. So every colour
  the game makes up (room lighting, effects) is **snapped to the sprites' palette** (`sprites.palette()`), and the
  app **wipes and redraws the whole screen** every few turns (`PTGApp.REDRAW_EVERY`, `action_redraw`; Ctrl+L by hand).
- **Two colours a cell.** Half blocks are the densest lossless way to draw pixels. Denser characters exist (quadrants
  2×2, sextants 2×3) but still allow only two colours a cell; and xterm.js draws half blocks and quadrants itself,
  seamlessly, while leaving sextants to the font (seams, or missing glyphs on phones). See
  `docs/plans/desktop-layouts/spike.py`'s "dense" thumbnails.

**Not used:** true image protocols (Kitty graphics, Sixel, iTerm's): real pixels, but not supported everywhere, and
not by xterm.js as textual-serve ships it.

**Fallback.** With sprites off (Settings → Art, or no Pillow), everything is drawn from the ASCII art in
`data/art.txt`: rooms, monsters, items and the die each have a text form.

## Commands

| | |
|---|---|
| `uv run ptg` | play (`--seed`, `--daily`, `--continue`, `--offline`, `--backend`, `--url`, `--model`, `--plain`) |
| `uv run ptg --test-room WHO --loadout KIT --floor N` | straight to a character, shop, boss or monster; counts for nothing (`testrooms.py`) |
| `uv run ptg --debug` (or F12) | the debug app: content, art, sounds, model check, test rooms |
| `uv run ptg serve` | the browser version |
| `uv run ptg export` / `ptg import …` | the Maker's library out and creations in |
| `uv run python -m ptg.integrity [--sign]` | check or accept the data files |
| `uv run python -m ptg.story` | check the story files |
| `uv run pytest -q` | the tests (about 1,300; under a minute, in parallel: `-n0` for one at a time) |

## Tests

- **Rules and content** are tested directly on `GameState` (fast).
- **UI** tests drive the real app headless with Textual's `run_test` (`tests/test_ui.py`, `test_screen.py`,
  `test_tabs.py`, `test_grid.py`); classic-screen tests pin `layout="classic"`.
- **In parallel** (pytest-xdist, `-n auto --dist worksteal` in `pyproject.toml`): the UI tests are nine tenths of
  the time and mostly wait on the app (animations, dice, narration), so they overlap well; each test has its
  own `PTG_HOME` (`conftest.py`). Run one with `-n0` to use a debugger or see print().
- **Balance**: `tests/bot.py` is an action-only player; `test_rules.py` plays 100 seeds and keeps its win rate
  between 20% and 75%, and checks bot games are deterministic.
- **Narration** is tested offline (no model), with a fake model where the shape of a model call matters.

## Where to extend

| To add | Touch |
|---|---|
| An item, monster, theme, perk, unlock | `data/*.toml` (or the Maker and `ptg import`), then sign and export |
| A floor's card: its picture and story | `uv run python tools/make_splash.py picture.png --floor <theme>`; its `lore` in `themes.toml` |
| What an item does | a power in `powers.py`, named in the item's `powers` |
| A way to use one thing on another | a row in `interactions.py`'s grid |
| A free-text effect the model may ask for | the effect sets in `creative.py`, and its line in the interpreter's prompt (`llm/prompts.py`) |
| An action in the choices | `rules.available_actions` and `rules.perform` |
| A character with behaviour | tag it `npc`; its verbs, stages and lines in `npcs.py` and `dialogue.toml` |
| A scripted moment or scene | a Markdown file in `data/story/` (`docs/writing-events.md`) |
| A language model backend | a class on `llm/base.py`'s interface |
| A pane or panel | a `pane_*` method in `ui/tabs.py`; a `Panel` in `ui/panels.py` |

## Conventions

- **Facts in, words out**: nothing a model says changes state; only engine events do.
- **Everything seeded** that affects play; no `random` without a seeded `Random`.
- **Data is signed**: re-sign and re-export after editing `src/ptg/data`.
- **Settings and saves never live in the repo** (`config.py`).
- **Docstrings explain why**, in plain words; module docstrings say what a module owns. This file says how they fit.
