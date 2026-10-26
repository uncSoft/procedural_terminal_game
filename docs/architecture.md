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
- **Loot, NPCs and powers are data-driven**: a new item drops by its role and tier (`loot.py`); what an item does is
  a list of named powers (`powers.py`); characters are tagged `npc` and given behaviour in `npcs.py`.
- **Story events** are Markdown with a small header (`story/parser.py` checks them against the content, failing
  loudly with a file and line).

## Language models

- `llm/base.py` is the interface: **structured JSON** (for the interpreter and extras) and **streamed prose** (for
  the narrator). Backends: any OpenAI-compatible server (`openai_compat.py`: LM Studio, Ollama, llama.cpp, vLLM,
  OpenRouter), Claude (`anthropic_backend.py`, the `claude` extra), or none (offline).
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
- **Two game screens**, chosen by `Config.layout` and the terminal's size (`ui/tabs.game_screen`):
  - `ui/game_screen.py` **GameScreen**, the classic layout, laid out by `ui/plan.py` for any size (one column on a
    phone);
  - `ui/tabs.py` **TabsScreen**, the desktop layout (story and decision on the left; the room, Here and tabbed panes
    on the right). It subclasses GameScreen: turns, dice, animations and the story are shared; only layout and
    panes differ.
- **Widgets** (`ui/widgets.py`): the HUD, `Picture` (the one way anything with a sprite is drawn), choices, the dice
  line. `ui/here.py` builds the Here tiles; `ui/panels.py` the pop-up panels (inventory, sheet, map, bestiary,
  journal, shop, cards).
- **Pictures**: sprites are PNG strips drawn as half-block characters (`sprites.py`); rooms are drawn in code from
  the room itself (`room_picture.py`); the d20 is drawn in code (`dice_art.py`). `tools/build_sprites.py` and
  `tools/build_sounds.py` generate the built-in art and 8-bit sounds (`sound.py` plays them without blocking).
- **Browser**: `ptg serve` (`serve.py`, on textual-serve) runs one game per tab behind a page that asks who's
  playing; `web/app_index.html` fits phones. Deployed with the `Dockerfile` (Render).
- **Plain text mode**: `ptg --plain` drives the same `Game` from a prompt loop in `cli.py`.

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
| `uv run pytest -q` | the tests (about 1,150; ten minutes) |

## Tests

- **Rules and content** are tested directly on `GameState` (fast).
- **UI** tests drive the real app headless with Textual's `run_test` (`tests/test_ui.py`, `test_screen.py`,
  `test_tabs.py`); classic-screen tests pin `layout="classic"`.
- **Balance**: `tests/bot.py` is an action-only player; `test_rules.py` plays 100 seeds and keeps its win rate
  between 20% and 75%, and checks bot games are deterministic.
- **Narration** is tested offline (no model), with a fake model where the shape of a model call matters.

## Where to extend

| To add | Touch |
|---|---|
| An item, monster, theme, perk, unlock | `data/*.toml` (or the Maker and `ptg import`), then sign and export |
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
