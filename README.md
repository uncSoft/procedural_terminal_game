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
- **Props and flair.** Using a real thing in the room or your pack ("topple the statue onto it") adds a ✦ flair bonus to the roll and earns a **Fate** token on success. What you throw, pour, feed or hand over is gone afterwards, whether or not the model lists it (bribe an orc with stale bread and the orc has the bread); your weapon, armor and keys only go if you say so.
- **Fate rerolls.** Spend Fate to rewind a failed check and roll again. Earn it with flair, perfect dodges, natural 20s and shrines.
- **Telegraphs.** Monsters wind up heavy blows a turn early (`⚠ HEAVY ATTACK NEXT`). Dodge or improvise an evasion to make them whiff, and get advantage and a Fate token.
- **Weaknesses.** Everything is weak to something: fire, holy, shiny, food, heavy, slippery... Turn the right prop on a monster to roll with advantage and hit harder. Once you discover a weakness, the bestiary remembers it forever.
- **A suggested trick.** The last choice (✦, in pink) is a creative idea built from what's actually in the room, so new players learn they can improvise.
- **Loot you can see.** What you find or see a monster drop appears in the story with its full art, and the inventory (F2) shows everything you carry as tiles: arrows pick one, Enter uses it. Carry more than one of a thing and its choices say how many (×2), and using one says how many are left.
- **Picking up is free.** Click a card in the story to take it (▶ click to take), or take everything here with one choice; either way it costs no turn, so leave what you don't want. Bombs and small keys you don't even pick up: they're yours as soon as a monster drops them or you walk in on them.
- **Rooms you can see.** The first time you walk into a room, the story shows it as you see it from the doorway, a pixel-art picture drawn from the room itself: its exits, decor, features, any monster and whatever's lying on the floor. Look (F4) shows it bigger.
- **Click a picture for its card.** A room's picture looks around it; a loot card, a chest or shrine in the story, or the monster in the sidebar opens its full card, with the matching action.
- **Easy to get around.** The ways out carry their arrows (▲ ▼ ◀ ▶) in the choices, and a pad of arrows beside them lights the doors there are: click one to go. Or type `n`, `s`, `e` or `w`. The choices box keeps its size, so nothing moves under your mouse while a suggestion arrives.

**Every run (about 25-40 minutes)**
- Three floors, three different dungeons, getting harder, with a boss at the bottom.
- **Pick one of three perks** at each level-up (Ruthless, Acrobatics, Vampiric, Glass Cannon...).
- **Traits earned by how you play**: talk monsters down and you become *Silver Tongue*; win with props and you become a *Showboat*; dodge enough and you become a *Duelist*.
- See what's through a door before you go: the map and choices show stairs `>`, shrines `†`, chests `■` and fountains `◊` ahead.
- **Things that do things.** Beyond their numbers, some items have powers, on their cards and tiles: Weighted Dice add 1 to every roll you make, a Torch 1 to searching, the Ten-Foot Pole 2 to picking locks and disarming traps; the Mysterious Floppy Disk maps the whole floor when you pick it up; flasks, holy water and the odd grenade can be thrown in a fight (and are gone); a Laser Pointer or a Rubber Duck costs a monster its next attack, once a fight; a Glow Stick lights up anything hidden in a room. Some are a mixed blessing. Some change your stats while you carry them (Lenny's Bad Tooth: +1 might, -1 wits; the Unusual Butter: +1 to everything and 5 more max HP), Swoogy's Diaper keeps monsters' hits 2 lighter but costs max HP every floor, and eating a Jar o' Light in a fight makes the monster flee.
- **Characters, not just monsters** (most made by the kids in the maker). **Lucky Lenny** turns up calm in some runs: a goblin knocked his bad tooth out with a pan, and it's hidden on his floor or the one before. Ask him and he points you to it; give it back and he yanks out his good one for you (+1 to every roll). **Swoogy the Gooey** waits in some secret rooms with a die: guess his number and his diaper is yours; guess wrong and he charges up his flaps, so calm him down with something you carry (gold, a potion, anything), fight him (he's strong), or get away and come back. **King Mouse** guards the stairs on floor 2 now and then, and leaves his vest. Some monsters have tricks: **Baby Joey** grabs your food (or gold) and runs off with it unless you stop him, and **Swamp Bottoms**' vines stop you running away.
- **Rare things.** Some items never lie about on a floor or drop from an everyday monster: they're kept in chests, hidden stashes, each floor's secret room, shops, and by the warden at the stairs (always) or an elite (sometimes), and each turns up at most once a run. The floor caps how good a warden's is, so the best come deeper, and from secret rooms. A warden with nothing rare left to give carries a small key.
- **Bombs and small keys** (● and ⚷ by your hearts). You start with a bomb; monsters drop bombs and keys now and then, elites more often. A chest opens three ways: a small key (safe), picking its lock (agility: fail and a needle gets you) or smashing it (might: fail and what's inside breaks). A bomb thrown in a fight always goes off.
- **A secret room on every floor**, sealed until you bomb a wall into it. It's only ever built in a gap in the map that touches two rooms or more, so you can work out where it might be, and only those walls offer a bomb. Search a room next to it and you may feel a draft. There's one a floor: once it's open, no wall is worth a bomb. Finding it is a moment: a bang, a fanfare, a banner across the story, and the room in gold on the map, `{✧}`, from then on.
- **Shops, now and then** (about one floor in four): a nook off the map, `[¤]`, behind a door a small key opens or two bombs break. Granny Gristle keeps most of them: a potion, gear for the floor, a bomb or a small key, and a trinket or, sometimes, something rare. Once in a while it's Granny Kamultruk's instead, the rare one, with the best and dearest stock. Shopping has a screen of its own: her wares as pictures with their prices; pick one for its card, Enter to buy, B to haggle (wits: a third off, or a quarter dearer if it goes wrong, once a ware). Mama's Shillelagh, sold nowhere else, helps you talk. Walking into one gets a jingle and a banner, gold and starrier for Granny Kamultruk.
- **Creatures that have stopped fighting know things.** Ask one what it knows (or, if it can't talk, watch where it goes): a wits roll, once each. It may put the floor's secret room or its hidden stash on your map (the stash as a gold `$`, and there when you search it), or, if it talks, tell you what one of the floor's monsters can't stand, the warden's or the boss's first.

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

**Small versions.** Items are also drawn small, 12 pixels wide, on the inventory's tiles, and pixel art
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

An item tagged `rare`, or given a `found` list in `items.toml` (`chest`, `stash`, `secret`, `warden`, `shop`, `quest`
for one a character gives you, or a monster's key for one that drops it), only turns up there, at most once a run.
Shops also sell what chests keep. An item's `powers` are what it does beyond its numbers (`powers = ["luck"]`), and
`stats` what carrying it does to yours (`stats = {might = 1, wits = -1}`, `max_hp` too); `src/ptg/powers.py` lists
the powers. A monster's `tricks` are what it does in a fight beyond hitting you (`tricks = ["steal"]`, or `tangle`).
The maker doesn't set these yet; importing a changed item or monster keeps what the game already gave it.

A monster tagged `npc` (the maker's NPC box) is a character, not one of the dungeon's monsters: it never attacks on
sight, and turns up calm on some floors to be talked to and asked (Lucky Lenny and Swoogy have their own places and
stories, in `src/ptg/npcs.py`, which also says how often everyone turns up). One tagged `guardian` only ever guards
the stairs (King Mouse).

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

The first launch opens Settings: pick LM Studio, Ollama, another OpenAI-compatible server, Claude, or Offline, pixel sprites or ASCII art, and whether dice roll on Space or automatically. Settings, saves and the profile database live in `~/.ptg` (set `PTG_HOME` to move them). The game autosaves every turn; **Continue** on the title screen picks up where you left off, with a line where the story so far stops, the room as you'd see it walking in (anything lying there ready to take) and where you are. While a run is unfinished, Continue comes first, with the run shown under it. Starting a new one instead asks first, and abandoning a run counts as a death: you keep its souls, it goes in the Hall of Legends, and your ghost stays on the floor where you left it.

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

Esc closes a panel; in the story, press it twice for the title screen (your game is saved).

Everything works with a mouse too: click a choice, an arrow on the pad, a highlighted word, a picture (for its card), loot in the story (to take it) or the dice (once to roll, again to carry on), and close a panel with its ✕ or a click outside it. Type `n`, `s`, `e` or `w` to go that way.

Useful flags:

```bash
uv run ptg --daily                       # today's daily descent
uv run ptg --seed 42                     # a specific run
uv run ptg --continue                    # straight into your autosave
uv run ptg --plain                       # line-by-line mode, no full-screen UI
uv run ptg --offline                     # no language model
uv run ptg --url http://localhost:11434  # one-off server override (Ollama here)
uv run ptg --debug                       # open the debug screen (F12)
uv run ptg --test-room swoogy            # a test room (below): next door to Swoogy
```

For Claude, install the extra and sign in with `ANTHROPIC_API_KEY` (or `ant auth login`):

```bash
uv sync --extra claude
uv run ptg --backend anthropic
```

Model requests and responses are logged to `~/.ptg/llm.log`. Each run's turns are kept in the profile (`~/.ptg/profile.db`, table `turns`): every turn's facts, and what the story showed, top to bottom (kind `shown`: the words, and which picture, sprite or cards appeared where).

**Garbled letters or tiny art?** Terminals that draw with the GPU (xterm.js in an editor or an app's terminal panel,
for one) keep every character they've drawn, in each pair of colours, in a cache; the pixel art fills it fast, and
when it overflows, letters turn into the wrong glyphs and pictures shrink. The game keeps its colours few (effects
use fixed shades), redraws the whole screen every few turns, and Ctrl+L redraws it now. If it still happens, play in
a terminal app (Terminal, iTerm2, Ghostty, WezTerm, kitty).

## Play it in a browser

`ptg serve` puts the game on a web page for a few people to share: one link, a page that asks who's playing, and
each name its own saves (profile, souls, settings and autosave). Typing the same name later picks up where that
player left off. A second tab with the same name ends the first, so a run is never played in two places. It's built
on Textual's `textual-serve`, which runs one game for each browser tab. Laptops and tablets play it fully; phones
need the narrow layout planned in `docs/plans/cross-platform-and-mobile.md`. Sound is off, since it would play on
the server.

Try it on your own machine (saves go in `./players`):

```bash
uv sync --extra web --extra claude
uv run ptg serve
```

Then open http://localhost:8000.

**Hosting it on Render** (a server that builds the game from GitHub, about $7 a month):
1. New → **Web Service**, and connect this repository, branch `v2`. Render finds the `Dockerfile`.
2. Instance type: **Starter** (the free one can't keep saves).
3. Under Advanced, add a **disk**: mount path `/data`, 1 GB.
4. Add environment variables (all optional):

   | Variable | What it does |
   | --- | --- |
   | `PTG_PASSWORD` | Asks for this on the name page, once a browser. Without it, anyone with the link can play. |
   | `ANTHROPIC_API_KEY` | Your key: every player's game is narrated by Claude on it, and players need no AI of their own (they never see it). Without it, the offline narrator. |
   | `PTG_MODEL` | The Claude model: `claude-haiku-5-5` (the default, a few cents a run) or `claude-sonnet-5-5`. |
   | `PTG_MAX_GAMES` | Games running at once (5). Each is about 80 MB, and the Starter plan has 512. |
   | `PTG_TEST_ROOMS` | `1` adds a **Test rooms** link to the name page (below). Leave it off for players. |

   Keep the key in Render's settings, never in the `Dockerfile` or the repository: the repository is public, and
   anything in an image can be read back out of it. Set a monthly spend limit in Anthropic's console, and a
   password, since everyone who plays spends from your key.
5. Create it. Every push to `v2` rebuilds and restarts it. Anyone mid-game is disconnected, but the game saved their
   last turn, and their name picks it up again.

Played this way, the game runs in hosted mode (`PTG_HOSTED=1`): Settings can't change the narrator, and the debug
screen (F12) is off, since it shows the model log and could point the server's narrator anywhere.

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

| Test rooms | straight to a character, a shop, a boss or any monster, with the kit you pick (below) |

The Models tab lists the server's models with the loaded ones first. Picking one that isn't loaded warns you first:
LM Studio would load it to answer, which can unload the one you have loaded. **Use for the narrator** saves the
choice for your next descent.

## Test rooms

To try someone out without playing down to them: a test room starts you next door to whoever you pick, so walking
in plays out as it would in a run. Lucky Lenny (his bad tooth is in your pack), Swoogy (behind a wall to bomb, with
a bomb), King Mouse (at the floor-2 stairs), either shop (at its door, with a small key, two bombs and 100 gold to
spend), each boss (at its locked door, with its key), or any monster.

Pick a kit: a new adventurer (`new`), what a run might have by that floor (`random`: gear, level and a perk for each
level), the best of everything (`strong`), or your own (`weapon=war_pick,armor=chain_shirt,items=holy_water+pickle,
level=3,gold=50,bombs=2,keys=1`, anything left out as a new adventurer has it). Most can be tried on any floor.

Nothing in a test room counts: it never saves over your run, banks no souls, and leaves your Hall of Legends,
ghosts and bestiary as they were. Esc twice leaves it.

```bash
uv run ptg --test-room list                                  # who, and the kits
uv run ptg --test-room king_mouse --loadout strong
uv run ptg --test-room shiny_shop --loadout new --floor 3
uv run ptg --test-room goblin --loadout "weapon=war_pick,items=pickle+pickle"
```

On the debug screen (F12, then 0) the same choices show the kit you'll get before you go (↻ for another draw). On
the browser version, `PTG_TEST_ROOMS=1` puts a test-rooms page at `/test`, under the tester's own name: when they
leave a test room they're back at their own title screen, their run where they left it.

## Project layout

```
src/ptg/
  data/            themes, rooms, items, monsters, perks, unlocks, prop tags (TOML), art and story/ events
  content.py       loads and validates the data (broken data fails loudly)
  world.py         seeded floors: layout, stairs, fixtures, elites, loot, ghosts, the secret room, the map
  loot.py          what turns up where: loot by kind and tier, read from the items, and where rare things are kept
  powers.py        what items do beyond their numbers: roll bonuses, maps, throwing, distracting, curses
  npcs.py          characters who aren't just monsters: Lucky Lenny, Swoogy, King Mouse, anyone tagged npc
  layout.py        room floor plans and where things stand
  models.py        game state (pydantic; a save file is just this as JSON)
  dice.py          d20 checks with advantage, as data the UI can animate
  rules.py         available actions, movement, items, fixtures, chests, bombs, perks, traits
  combat.py        attacks, telegraphed intents, dodging, fleeing, defeat
  creative.py      free-text attempts: props, flair, weaknesses, clamped effects
  game.py          one turn: interpret -> resolve -> (reroll) -> narrate -> save -> profile
  profile.py       SQLite: souls, unlocks, Hall of Legends, bestiary, ghosts, turn log
  meta.py          building the adventurer from unlocks, starting runs, scoring the end
  testrooms.py     test rooms: next door to anyone, with any kit, counting for nothing
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
  serve.py         `ptg serve`: the game in web browsers, a name and saves for each player
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
