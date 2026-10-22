# Procedural Terminal Game

A roguelite dungeon crawl in your terminal, narrated by a language model running on your own machine (LM Studio, Ollama) or through an API (Claude, or any OpenAI-compatible server). It looks like a DOS game and listens like a game master.

Every turn you can pick a numbered choice, or type whatever you want to try:

```
> splash my holy water in its face
                ╔═════════ AGILITY CHECK ═════════╗
                ║      /\        /\               ║
                ║     /  \      /  \              ║
                ║    / 13 \    / 9  \   needs 13  ║
                ║   /______\  /______\            ║
                ║  d20 13 + 1 agility + 2 ✦ Vial  ║
                ║  of Holy Water = 16             ║
                ║           ✔ SUCCESS             ║
                ╚═════════════════════════════════╝
You hurl the vial with theatrical precision and it shatters against the ghoul's grey flesh...
```

## The idea: the engine owns the facts, the model owns the words

| Who | Does what |
| --- | --- |
| **World generator** (code) | Builds a three-floor descent from a seed. Each floor is a different dungeon: rooms on a grid with floor plans, stairs guarded by a warden, shrines, trapped chests, fountains, elites, one secret per floor, and the boss behind a locked door on the last floor. Same seed, same run. |
| **Rules** (code) | List the legal actions each turn (the numbered choices) and resolve everything with d20 rolls: combat, telegraphed heavy blows, dodging, fleeing, searching, fixtures, leveling. |
| **Interpreter** (model) | Turns free text into JSON: one of the listed actions, or a *creative* attempt with a stat, a difficulty, the props it uses, and effects from a fixed menu (stun, small damage, pacify, evade, reveal a secret...). The rules check the props exist, clamp the effects, roll the dice and apply them. "Summon a dragon" fails; "throw sand in its eyes" might stun it. |
| **Narrator** (model) | Gets the list of facts that actually happened and streams a few sentences of prose. It can't change the game state, so it can't make up loot or kill monsters. |

Each turn sends the model a small snapshot (room, positions, player, last few events), not an ever-growing chat log, so local models stay fast: about 1-2 seconds a turn with Qwen3.6-35B-A3B in LM Studio. Without a model the game still runs: commands go through a keyword matcher and narration is stitched together from the facts.

## The loop

**Every turn**
- **Dice you roll yourself.** Skill checks open a big d20 panel: press Space, it tumbles, bonuses add up one by one, and the result is stamped. Natural 20s flash gold, natural 1s shake the screen. Attacks get small inline dice.
- **Props and flair.** Using a real thing in the room or your pack ("topple the statue onto it") adds a ✦ flair bonus to the roll and earns a **Fate** token on success.
- **Fate rerolls.** Spend Fate to rewind a failed check and roll again. Earn it with flair, perfect dodges, natural 20s and shrines.
- **Telegraphs.** Monsters wind up heavy blows a turn early (`⚠ HEAVY ATTACK NEXT`). Dodge or improvise an evasion to make them whiff, and get advantage and a Fate token.
- **Weaknesses.** Everything is weak to something: fire, holy, shiny, food, heavy, slippery... Turn the right prop on a monster to roll with advantage and hit harder. Once you discover a weakness, the bestiary remembers it forever.
- **A suggested trick.** The last choice (✦, in pink) is a creative idea built from what's actually in the room, so new players learn they can improvise.

**Every run (about 25-40 minutes)**
- Three floors, three different dungeons, getting harder, with a boss at the bottom.
- **Pick one of three perks** at each level-up (Ruthless, Acrobatics, Vampiric, Glass Cannon...).
- **Traits earned by how you play**: talk monsters down and you become *Silver Tongue*; win with props and you become a *Showboat*; dodge enough and you become a *Duelist*.
- See what's through a door before you go: the map and choices show stairs `>`, shrines `†`, chests `■` and fountains `◊` ahead.

**Across runs**
- **Souls** carry over when you die. Spend them at **the campfire** on **blessings** (permanent upgrades) and **gifts** (a starting item for your next descent).
- **The Hall of Legends** lists every run with an epitaph the narrator writes for your tombstone.
- **Your ghost haunts later runs.** Die, and your adventurer may come back as a ghost on that floor, guarding what they carried. Lay them to rest to get it back.
- **The Void**, the voice by the campfire, remembers how your last run went.
- **Daily descent.** Everyone gets the same dungeon each day; you get a spoiler-free result card to share.

## Story events

Scripted moments live in `src/ptg/data/story/` as small Markdown files: a header saying when they fire
(entering a room, typing a magic word, a natural 20, defeating a monster...), then text written in your own
words, optional choices that also accept free text, and effects like `[hp -6]`, `[give oil_flask]`,
`[mark mirror_unbroken]` or `[secret]`. Marks and the **Book of Secrets** survive death. They work with no
AI at all. See [docs/writing-events.md](docs/writing-events.md).

```bash
uv run python -m ptg.story                    # check every story file
uv run ptg --event mirror_trial               # jump straight into one
```

## Pixel art

Monsters, the bestiary and the campfire are drawn as pixel-art sprites using half-block characters: each
terminal cell shows two pixels (`▀` in the top pixel's colour on a background of the bottom pixel's colour).
That works inside the UI in any terminal with 24-bit colour, with no image protocol. Monsters bob while idle
and flash white when hit. Switch to the original ASCII art in Settings (Art), or it falls back automatically
for anything without a sprite.

Sprites live in `src/ptg/data/sprites/` as PNG strips: square frames side by side, transparent background,
any size (they're scaled to fit). The shipped ones are drawn as colour maps in `tools/build_sprites.py`, which
adds outlines, shading and an idle frame:

```bash
uv run python tools/build_sprites.py --sheet sheet.png   # rebuild, plus an 8x preview sheet
uv run python -m ptg.sprites goblin troll                # preview sprites in your terminal
```

To use your own art (Aseprite, Piskel, an image model), drop a PNG named after the monster's key
(`goblin.png`, `drowned_abbot.png`...) into that folder.

## Running it

Needs Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
uv run ptg
```

The first launch opens Settings: pick LM Studio, Ollama, another OpenAI-compatible server, Claude, or Offline, pixel sprites or ASCII art, and whether dice roll on Space or automatically. Settings, saves and the profile database live in `~/.ptg` (set `PTG_HOME` to move them). The game autosaves every turn; **Continue** on the title screen picks up where you left off.

| Key | Typed | Opens |
| --- | --- | --- |
| F1 | `help` | how to play |
| F2 | `i` | inventory (Enter uses an item) |
| F3 | `c` | character: perks, traits and progress toward the next one |
| F4 | `l` | the room's floor plan |
| F5 | `m` | the floor map and the whole descent |
| F6 | `b` | bestiary: art, kills, discovered weaknesses, lore |
| F7 | `j` | journal |

Choices can be clicked as well as typed.

Useful flags:

```bash
uv run ptg --daily                       # today's daily descent
uv run ptg --seed 42                     # a specific run
uv run ptg --continue                    # straight into your autosave
uv run ptg --plain                       # line-by-line mode, no full-screen UI
uv run ptg --offline                     # no language model
uv run ptg --url http://localhost:11434  # one-off server override (Ollama here)
```

For Claude, install the extra and sign in with `ANTHROPIC_API_KEY` (or `ant auth login`):

```bash
uv sync --extra claude
uv run ptg --backend anthropic
```

Model requests and responses are logged to `~/.ptg/llm.log`.

## Project layout

```
src/ptg/
  data/            themes, rooms, items, monsters, perks, unlocks, prop tags (TOML), art and story/ events
  content.py       loads and validates the data (broken data fails loudly)
  world.py         seeded floors: layout, stairs, fixtures, elites, loot, ghosts, the map
  layout.py        room floor plans and where things stand
  models.py        game state (pydantic; a save file is just this as JSON)
  dice.py          d20 checks with advantage, as data the UI can animate
  rules.py         available actions, movement, items, fixtures, perks, traits
  combat.py        attacks, telegraphed intents, dodging, fleeing, defeat
  creative.py      free-text attempts: props, flair, weaknesses, clamped effects
  game.py          one turn: interpret -> resolve -> (reroll) -> narrate -> save -> profile
  profile.py       SQLite: souls, unlocks, Hall of Legends, bestiary, ghosts, turn log
  meta.py          building the adventurer from unlocks, starting runs, scoring the end
  sprites.py       PNG sprites rendered as half-block pixel art
  glossary.py      the terms highlighted in the story
  story/           story events: file format, checker, and the engine that plays them
  llm/             backends (OpenAI-compatible, Claude), prompts, interpreter, narrator, extras
  ui/              Textual app: title, settings, campfire, game screen, dice, panels, endings
  cli.py           `ptg` entry point and plain-text mode
tests/             world, rules, profile, interpreter and UI tests, plus a bot that plays whole runs
tools/             build_sprites.py: the hand-drawn sprite maps and their PNG build
legacy/            the v1 curses prototype, kept for reference
```

Add a theme with a `[[theme]]` block in `themes.toml`, its room archetypes in `rooms.toml`, and tagged monsters in `monsters.toml`. Give a room feature new powers by adding its keyword to `tags.toml`. No code changes needed.

## Tests

```bash
uv run pytest
```

The suite includes a bot that plays 100 seeded runs using only the listed actions. It never improvises or buys blessings, and wins a little under half its runs; that win rate is a guard against balance regressions.
