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

Each turn sends the model a small snapshot, not an ever-growing chat log, so local models stay fast: about 1-2 seconds a turn with Qwen3.6-35B-A3B in LM Studio. The snapshot reads oldest first: the floor, a few one-line notes on what happened before this turn, where the player was and is now (and whether they've been here before), the room as it stands with what lies beyond each exit, and what happened there before (rooms remember the
monster you killed, the chest you opened, the statue you toppled), and the facts of this turn.

Smaller local models slip, so the narration is checked against the facts a sentence at a time as it streams
(`src/ptg/llm/guard.py`). A sentence is left out if it echoes the prompt, talks about "the player" or being an AI,
puts choices to the player, calls a room it has never seen familiar, invents an exit, item or monster, or runs past
the length asked for; if nothing survives, the facts are narrated instead. To see how a model copes:

```bash
uv run python -m ptg.llm.check                                          # the model in your Settings
uv run python -m ptg.llm.check --url http://localhost:11434/v1 --model llama3.2:3b
```

It scores ten typed commands and five narrated moments, shows what the guard would cut and why, and times it all. The same check runs inside the game on the debug screen (F12, the Models tab), where you can pick any model the server offers and compare it with earlier checks. Without a model the game still runs: commands go through a keyword matcher and narration is stitched together from the facts.

## The loop

**Every turn**
- **Dice you roll yourself.** Skill checks open a big pixel-art d20: press Space (or click), it tumbles and bounces, bonuses add up one by one, and the result is stamped. Natural 20s glow gold, natural 1s glow red and shake the screen; with advantage you roll two and the one you don't keep greys out. Attacks get small inline dice.
- **You can see how it went.** Every roll ends in a coloured verdict (✔ HIT, ✘ HIT YOU, • NOTHING, ★ CRITICAL!) and flashes its colour. The story's border lights up green when the turn goes your way, red when it doesn't and silver when it's mixed (or blinks gold or crimson for a 20 or a 1). Damage numbers rise off the monster, your HP changes show by your hearts, and a new floor gets a title card and a banner in the story.
- **Props and flair.** Using a real thing in the room or your pack ("topple the statue onto it") adds a ✦ flair bonus to the roll and earns a **Fate** token on success.
- **Fate rerolls.** Spend Fate to rewind a failed check and roll again. Earn it with flair, perfect dodges, natural 20s and shrines.
- **Telegraphs.** Monsters wind up heavy blows a turn early (`⚠ HEAVY ATTACK NEXT`). Dodge or improvise an evasion to make them whiff, and get advantage and a Fate token.
- **Weaknesses.** Everything is weak to something: fire, holy, shiny, food, heavy, slippery... Turn the right prop on a monster to roll with advantage and hit harder. Once you discover a weakness, the bestiary remembers it forever.
- **A suggested trick.** The last choice (✦, in pink) is a creative idea built from what's actually in the room, so new players learn they can improvise.
- **Loot you can see.** What you find, pick up or see a monster drop appears in the story with its art, and the inventory (F2) shows everything you carry as tiles: arrows pick one, Enter uses it.
- **Rooms you can see.** The first time you walk into a room, the story shows it as you see it from the doorway, a pixel-art picture drawn from the room itself: its exits, decor, features, any monster and whatever's lying on the floor. Look (F4) shows it bigger.

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

While you write, the debug screen's Story tab (F12) reloads the files without restarting the game, shows any
problems, and can fire any event at the start of your next descent.

## Data files

All game content (themes, rooms, items, monsters, perks, unlocks, tags, art, story events) is plain data in
`src/ptg/data/`, checked on startup: a mistake is explained by file, entry and field ("monsters.toml
[monster.goblin]: unknown field 'hpp' (did you mean 'hp'?)") instead of crashing. The shipped files are
also fingerprinted, so the game notices when they've been edited. Editing is allowed. It's just noticed.
After real changes:

```bash
uv run python -m ptg.integrity          # what changed since the last signing
uv run python -m ptg.integrity --sign   # accept it (a test fails until you do)
```

## Pixel art

Monsters, the bestiary, the campfire, the dungeon's fixtures and the dice are drawn as pixel art using
half-block characters: each terminal cell shows two pixels (`▀` in the top pixel's colour on a background of
the bottom pixel's colour). That works inside the UI in any terminal with 24-bit colour, with no image
protocol. Switch to the original ASCII art in Settings (Art), or it falls back automatically for anything
without a sprite.

Everything moves. Monsters bob while idle, glow when winding up a heavy blow, see stars when stunned, lunge
when they attack, flash white when hit and dissolve when they die. Shrines, chests, fountains and stairs come
alive when you first walk in and play out when you use them (the chest rattles open, the stairs fade into
the dark). Story events can put a sprite on their card (`sprite:` in the header, see
[docs/writing-events.md](docs/writing-events.md)). The poses are made from each sprite's own frames, so new
art gets them for free.

Sprites live in `src/ptg/data/sprites/` as PNG strips: frames side by side, transparent background, any size
(they're scaled to fit). Frames are square unless the PNG stores a `frames` count. The shipped ones are drawn
as colour maps in `tools/build_sprites.py`, which adds outlines, shading and animation frames; the d20 is drawn
in code (`dice_art.py`) so it can show any number:

```bash
uv run python tools/build_sprites.py --sheet sheet.png   # rebuild, plus an 8x preview sheet
uv run python -m ptg.sprites goblin troll                # preview sprites in your terminal
```

To use your own art (Aseprite, Piskel, an image model), drop a PNG named after the monster's key
(`goblin.png`, `drowned_abbot.png`...) into that folder.

**Small versions.** Items are also drawn small, 12 pixels wide, in the inventory and in loot cards, and pixel art
doesn't shrink well. So each item can have a hand-made small version: a 12×12 PNG strip with the same frames, in
`src/ptg/data/sprites/small/` under the same name (`item_healing_potion.png`), best drawn in the big sprite's own
colours with the bottom row left empty for the bob. The Monster & Item Maker draws them too (below), and its import
puts them there. Without one, the big sprite is halved block by block, which keeps its lines whole but looks rough.
The debug screen (F12) shows every small version beside the big one, and lists the items still being halved.
An item with no art at all shows a plain grey stand-in for its kind (a blade, a jerkin, a loaf, a key...), and its
inventory card says it has no picture yet.

**Room pictures.** The picture of a room (in the story when you first walk in, and in Look) is drawn in code
(`room_picture.py`), not from art files, so every room the game makes has one. It's the view from the door you came
in by, in one-point perspective and in the dungeon's own look: the Crypt's bricks and candles, the Warren's earth,
timber and torches, the Ruins' marble. Exits are doorways in their walls (dark if unexplored, planked if locked); the
room map's decor stands where the map has it (water, pillars, tables, cages, plants, fungus...); each feature is a
small prop of its kind, from its name ("a half-sunken pew", "the throne of chairs"); the fixture, monster and items
are their own sprites; and candles, torches and glowing things light what's near them. Add `sky` to a room's `decor`
in `rooms.toml` and its walls stand broken under the stars. Every colour is one the sprites already use, so the
pictures don't strain a GPU terminal's glyph cache. A new dungeon borrows the Crypt's look until it's given one
(`LOOKS` in `room_picture.py`).

```bash
uv run python -m ptg.room_picture 7     # every room on the first floor of seed 7, in your terminal
```

## The Monster & Item Maker

`docs/maker` is a one-page web app for drawing monsters and items and setting their stats, hosted free on GitHub
Pages so friends can contribute. It works on a laptop, a tablet or a phone, with nothing to install:

- **Draw** on a 24x24 grid in the game's own 32 colours plus any colour you pick (kept as "your colours"), with
  pencil, eraser, fill, colour picker, mirror mode, undo and redo (B, E, G, I, M and Ctrl/Cmd+Z), and a second frame
  for the idle animation. The preview shows it moving, the way it'll look in the dungeon.
- **A small version** (items): a 12x12 board under the drawing for how the inventory and loot cards show the item.
  It starts as the drawing halved exactly the way the game would; draw on it to fix it up by hand, with the same
  tools, frames and undo. Once it's hand-made it stops following the drawing, says so if the drawing changes after,
  and "Start again from the drawing" goes back. Only a hand-made one is sent, and imported.
- **Set everything**: tier (with typical values for it, one click to apply), HP, defense, attack, damage dice and XP;
  creature type, which decides which dungeons it appears in; weaknesses; any extra tags; whether it can be reasoned
  with; its heavy-attack tell; and a description, which the in-game narrator reads so it describes the thing the way
  its creator imagined. Items get their kind, tier, damage, defense, healing or escape, tags and description.
- **Save**: put your name in "Created by" and press Save. The creation goes into the library straight away, whether
  or not it ever goes into the game (for everyone once the shared library below is set up; until then, just in that
  browser). Saving again updates it, a reminder shows when it's changed since, and deleting it from "My work" takes it
  out of the library too.
- **The library** shows what's been saved but isn't in the game yet, newest first, then every monster and item in
  the game, each with its art, stats and who created it, searchable. Your own saved things can be edited, anyone
  else's remixed into a new one of yours, and the game's own edited and saved as a suggested change. Once the owner
  brings a saved one into the game, it moves to the game's shelf.
- **Other ways to share** (tucked under Save): "Copy link" and "Download .json" give you something to send the
  game's owner yourself. Work is also kept in the browser. (The maker no longer files GitHub issues.)

**The shared library**: GitHub Pages can only serve files, so the saves everyone sees live in a Google Sheet, behind
a small Apps Script web app (free, about five minutes to set up, nothing to run yourself):

1. Make a Google Sheet (sheets.new), then Extensions → Apps Script, and paste in
   [`tools/maker_saves.gs`](tools/maker_saves.gs) in place of what's there.
2. Deploy → New deployment → Web app, executing as you, with access for "Anyone". Allow what it asks for (Google
   warns that the app isn't verified: it's yours, so Advanced → Go to …).
3. Put the web app URL (it ends in `/exec`) in `docs/maker/config.json` as `"saves": {"url": "…"}`, commit and push.

When `tools/maker_saves.gs` changes (it learned to keep an item's small version, for one), paste it in again and
publish it: Deploy → Manage deployments → Edit → Version: New version → Deploy. The URL stays the same. Until then
the old script quietly leaves out what it doesn't know, and links and downloads still carry everything.

Each saved creation is a row in the sheet: its number, name, type, who created it and when. The number (#1, #2, …)
never changes and is never reused; it shows on the creation's card in the library and when it's saved. Type anything
in a row's `hide` cell to take it out of the library (saving it again won't bring it back), or delete the row. Only
the browser that saved something can change or remove it. The URL is in the page source, so anyone could post to it;
the script only keeps things shaped like creations, and at most 1,000 of them.

To bring things into the game (in a checkout of this repo):

```bash
uv run ptg import --saves               # what's been saved in the maker but isn't in the game yet, by number
uv run ptg import --saves 3 7           # bring #3 and #7 into the game (--dry-run to only look)
uv run ptg import "<link>"              # a link someone sent (or a saved one's Link button), a .json file,
                                        # or a URL serving creations
uv run ptg export                       # refresh the page's library by hand
```

`--saves` reads the shared library from `docs/maker/config.json` (or `--url`). A save counts as in the game once the
game has something by its name from the same creator, the same rule the page uses to move it to the game's shelf, so
picking one twice doesn't add it twice. Submissions from before Save, made as GitHub issues with "[maker]" in the
title, can still be brought in with `uv run ptg import --github` (`--dry-run` to look first; it needs the GitHub CLI
logged in, and comments on and closes each issue it imports).

Each import writes the sprite (`src/ptg/data/sprites`), the entry in `monsters.toml` or `items.toml` with a
`# drawn by` credit (the GitHub username if the maker left their name blank), ASCII art for a new monster's ASCII
mode, checks the whole game still loads before writing anything, re-signs the data, and refreshes
`docs/maker/library.json`. A submission that doesn't load is reported and skipped; the rest still go in. Commit and
push, and the page's library shows them too.

**Where new things turn up**: no code changes needed. Monsters appear in every dungeon that calls for their tags,
at their tier. Items drop by kind and tier (`src/ptg/loot.py`): each place that hands one out asks for something
like "a tier-1 weapon" or "a potion of tier 2 or more" and picks among every item in the game that fits, a tier
first, then an item of it (so adding five tier-3 potions doesn't make tier 3 five times as likely). Tier 1 turns
up from floor 1, tier 2 deeper, and the best of each kind in hidden stashes and floor-3 chests; the debug screen's
Items tab (F12) says where each item can turn up.

**An inbox instead of (or as well as) GitHub**: set `inbox.url` in `docs/maker/config.json` and the page gets a
"Send to inbox" button that posts each creation there: a Discord webhook gets a message with the link, anything
else gets the creation as JSON (`{"kind": "ptg-creation", "text", "link", "code", "creation"}`). Use it for a
channel or a storage endpoint you own; anything that can later serve those JSON creations back (or the links) can
be imported with `uv run ptg import`. The URL is visible in the page source, so treat it as semi-public.

To publish the page: on GitHub, Settings → Pages → "Deploy from a branch", pick the branch and the `/docs` folder.
It appears at `https://uncsoft.github.io/procedural_terminal_game/` (which forwards to `/maker/`). To try it
locally: `python3 -m http.server --directory docs`, then open http://localhost:8000/maker/.

## Sound

Short 8-bit effects for the moments that matter: the d20 clattering and landing, hits and misses, coins, secrets,
the stairs, level-ups, a natural 20. A terminal can only beep, so the game plays its own sound: a small mixer on a
thread of its own streams to your speakers through [sounddevice](https://python-sounddevice.readthedocs.io)
(PortAudio, bundled on macOS and Windows; on Linux install `libportaudio2`), with the system's player (`afplay`,
`pw-play`, `paplay`, `aplay`) as a fallback. Sound never blocks or crashes the game. F8 turns it on and off,
Settings has the volume, and `PTG_SOUND=0` keeps it quiet (the tests do).

The built-in sounds are synthesized, like the sprites: `tools/build_sounds.py` describes each one as a few
chip-style tones (square, triangle and noise waves, pitch slides, arpeggios) and writes 8-bit, 22 kHz WAVs to
`src/ptg/data/sounds`. Tweak one and rebuild.

To use your own, put WAV files (8- or 16-bit PCM, any rate) in `~/.ptg/sounds`:

- `great.wav` replaces the natural-20 sound; `great_2.wav`, `great_3.wav`... add variations played at random.
- `sounds.toml` maps any file names to moments, sets volumes, and records where each sound came from:

```toml
[great]
files = ["fanfare.wav"]
volume = 0.8
credit = "Jane Doe, opengameart.org"
license = "CC0"

[hit]
volume = 0.5   # no files: just turn a built-in sound down
```

```bash
uv run python -m ptg.sound              # every moment, where its sound comes from, and any problems
uv run python -m ptg.sound great coin   # play some
```

Making and finding sounds: sfxr-style tools (jsfxr, Bfxr, ChipTone) export 8-bit WAVs that are yours outright. For
downloads, CC0 packs are the easiest (Kenney, OpenGameArt's CC0 section, freesound with the CC0 filter); CC-BY is
fine with a credit line in `sounds.toml`. Many store-bought packs allow use in a game but not sharing the files
themselves, so keep those in `~/.ptg/sounds` rather than committing them to a public repo.

## Running it

Needs Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
uv run ptg
```

The first launch opens Settings: pick LM Studio, Ollama, another OpenAI-compatible server, Claude, or Offline, pixel sprites or ASCII art, and whether dice roll on Space or automatically. Settings, saves and the profile database live in `~/.ptg` (set `PTG_HOME` to move them). The game autosaves every turn; **Continue** on the title screen picks up where you left off.

| Key | Typed | Opens |
| --- | --- | --- |
| F1 | `help` | how to play |
| F2 | `i` | inventory: what you carry, with its art (arrows pick, Enter uses) |
| F3 | `c` | character: perks, traits and progress toward the next one |
| F4 | `l` | the room: its picture, description, exits and floor plan |
| F5 | `m` | the floor map and the whole descent |
| F6 | `b` | bestiary: art, kills, discovered weaknesses, lore |
| F7 | `j` | journal |
| F8 | | sound on or off |
| F12 | | the debug screen |
| Ctrl+L | | redraw the screen |

Everything works with a mouse too: click a choice, a highlighted word or the dice (once to roll, again to carry on), and close a panel with its ✕ or a click outside it.

Useful flags:

```bash
uv run ptg --daily                       # today's daily descent
uv run ptg --seed 42                     # a specific run
uv run ptg --continue                    # straight into your autosave
uv run ptg --plain                       # line-by-line mode, no full-screen UI
uv run ptg --offline                     # no language model
uv run ptg --url http://localhost:11434  # one-off server override (Ollama here)
uv run ptg --debug                       # open the debug screen (F12)
```

For Claude, install the extra and sign in with `ANTHROPIC_API_KEY` (or `ant auth login`):

```bash
uv sync --extra claude
uv run ptg --backend anthropic
```

Model requests and responses are logged to `~/.ptg/llm.log`.

**Garbled letters or tiny art?** Terminals that draw with the GPU (xterm.js in an editor or an app's terminal panel,
for one) keep every character they've drawn, in each pair of colours, in a cache; the pixel art fills it fast, and
when it overflows, letters turn into the wrong glyphs and pictures shrink. The game keeps its colours few (effects
use fixed shades), redraws the whole screen every few turns, and Ctrl+L redraws it now. If it still happens, play in
a terminal app (Terminal, iTerm2, Ghostty, WezTerm, kitty).

## The debug screen

F12 anywhere in the game (or `uv run ptg --debug`) opens a page of everything at a glance. The number keys pick
a tab:

| Tab | Shows |
| --- | --- |
| Overview | anything that looks wrong, the narrator and settings, what's loaded, your files, the data's signatures |
| Monsters | every monster's numbers, art and every pose a fight puts it in, who drew it, where it lives, your bestiary |
| Items | every item, its numbers and art, and who drew it |
| Art | every sprite, frame by frame, animated in any pose |
| Sounds | every moment's sound: click one (or Enter) to play it, reload after adding yours, open your sounds folder |
| Story | every story event and its parts, choices and effects; reload the files, or fire one on the next descent |
| State | this run's story flags, the player, and the whole save as a tree; your profile's marks, secrets and souls |
| Models | the model check against any model on the server, with earlier results kept to compare |
| Log | the latest exchanges with the model, what the guard cut, newest first |

The Models tab lists the server's models with the loaded ones first. Picking one that isn't loaded warns you first:
LM Studio would load it to answer, which can unload the one you have loaded. **Use for the narrator** saves the
choice for your next descent.

## Project layout

```
src/ptg/
  data/            themes, rooms, items, monsters, perks, unlocks, prop tags (TOML), art and story/ events
  content.py       loads and validates the data (broken data fails loudly)
  world.py         seeded floors: layout, stairs, fixtures, elites, loot, ghosts, the map
  loot.py          what turns up where: loot by kind and tier, read from the items
  layout.py        room floor plans and where things stand
  models.py        game state (pydantic; a save file is just this as JSON)
  dice.py          d20 checks with advantage, as data the UI can animate
  rules.py         available actions, movement, items, fixtures, perks, traits
  combat.py        attacks, telegraphed intents, dodging, fleeing, defeat
  creative.py      free-text attempts: props, flair, weaknesses, clamped effects
  game.py          one turn: interpret -> resolve -> (reroll) -> narrate -> save -> profile
  profile.py       SQLite: souls, unlocks, Hall of Legends, bestiary, ghosts, turn log
  meta.py          building the adventurer from unlocks, starting runs, scoring the end
  sprites.py       PNG sprites rendered as half-block pixel art, and their poses
  room_picture.py  pictures of rooms, seen from the doorway, drawn in code from the room itself
  dice_art.py      the pixel-art d20
  sound.py         8-bit sound effects: the sound bank, your own sounds, and playing them
  library.py       the Monster & Item Maker's library: export it, and import what's made there
  glossary.py      the terms highlighted in the story
  integrity.py     fingerprints of the shipped data, and noticing edits
  story/           story events: file format, checker, and the engine that plays them
  llm/             backends (OpenAI-compatible, Claude), prompts, interpreter, narrator, guard, check, extras
  ui/              Textual app: title, settings, campfire, game screen, dice, panels, endings, debug screen
  cli.py           `ptg` entry point and plain-text mode
tests/             world, rules, profile, interpreter and UI tests, plus a bot that plays whole runs
docs/maker/        the Monster & Item Maker page and its library.json (GitHub Pages serves docs/)
tools/             build_sprites.py: the hand-drawn sprite maps; build_sounds.py: the synthesized sounds;
                   maker_saves.gs: the maker's shared library (a Google Apps Script)
legacy/            the v1 curses prototype, kept for reference
```

Add a theme with a `[[theme]]` block in `themes.toml`, its room archetypes in `rooms.toml`, and tagged monsters in `monsters.toml`. Give a room feature new powers by adding its keyword to `tags.toml`. No code changes needed.

## Tests

```bash
uv run pytest
```

The suite includes a bot that plays 100 seeded runs using only the listed actions. It never improvises or buys blessings, and wins a little under half its runs; that win rate is a guard against balance regressions.
