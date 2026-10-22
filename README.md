# Procedural Terminal Game

A seeded dungeon crawl in your terminal, narrated by a language model running on your own machine (LM Studio, Ollama) or through an API (Claude, or any OpenAI-compatible server).

Every turn you can pick a numbered choice, or type whatever you want to try:

```
> I flip the stew cauldron onto the goblin
  ⚄ might: d20 14 + 2 = 16 vs 13 - success
The cauldron tips with a wet, glorious slop, and the goblin disappears under a tide of
mystery stew. It staggers back, blinded and dripping, flailing at the air where you used to be.
```

## The idea: the engine owns the facts, the model owns the words

| Who | Does what |
| --- | --- |
| **World generator** (code) | Builds the dungeon from a seed: rooms on a grid, a locked boss room, a key, monsters scaled by depth, loot, one secret. Same seed, same dungeon. |
| **Rules** (code) | Lists the legal actions each turn (the numbered choices) and resolves everything with d20 rolls: combat, fleeing, searching, potions, leveling. |
| **Interpreter** (model) | Reads free text and returns structured JSON: one of the listed actions, or a *creative* attempt with a stat, a difficulty and effects picked from a fixed menu (stun, small damage, pacify, reveal a secret...). The rules clamp those effects, roll the dice and apply them. "Summon a dragon" fails; "throw sand in its eyes" might stun it. |
| **Narrator** (model) | Gets the list of facts that actually happened and streams 2-4 sentences of prose. It can't change the game state, so it can't make up loot or kill monsters. |

Each turn sends the model a small snapshot (room, player, last few events), not an ever-growing chat log, so local models stay fast. With Qwen3.6-35B-A3B in LM Studio a turn takes 1-2 seconds.

Without a model the game still runs: plain commands go through a keyword matcher and narration is stitched together from the facts. That's also what the tests use.

## Running it

Needs Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
uv run ptg
```

The first launch opens Settings: pick LM Studio, Ollama, another OpenAI-compatible server, Claude, or Offline. Settings and saves live in `~/.ptg` (set `PTG_HOME` to move them). The game autosaves every turn; **Continue** on the title screen picks up where you left off.

Useful flags:

```bash
uv run ptg --seed 42                     # a specific dungeon
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
  data/            themes, room archetypes, items, monsters (TOML) and ASCII art
  content.py       loads and validates the data (broken data fails loudly)
  world.py         seeded dungeon generation and the ASCII map
  models.py        game state (pydantic; a save file is just this as JSON)
  rules.py         available actions, combat, creative-action resolution
  intent.py        what the player meant, and the JSON schema the interpreter fills
  game.py          one turn: interpret -> resolve -> narrate -> autosave
  llm/             backends (OpenAI-compatible, Claude), prompts, interpreter, narrator
  ui/              Textual app: title, settings, intro, game screen
  cli.py           `ptg` entry point and plain-text mode
tests/             rules, world, interpreter, save and UI tests, plus a bot that plays whole games
legacy/            the v1 curses prototype, kept for reference
```

Add a theme by writing a `[[theme]]` block in `themes.toml`, its room archetypes in `rooms.toml`, and tagging monsters in `monsters.toml`. No code changes needed.

## Tests

```bash
uv run pytest
```

The suite includes a bot that plays 120 seeded games using only the listed actions. Its win rate (around 50%) is a guard against balance regressions.

## Status

v2 is a first playable slice: one 10-room dungeon per seed across three themes, a boss, free-text actions and save/load. Ideas for what's next:

- Talkable NPCs and shops, beyond fighting or pacifying monsters
- Multi-floor runs, with the dungeon getting harder on each floor
- Let the model reword the numbered choices to match the scene
- More themes and monster art
