# Procedural Terminal Game

A roguelite dungeon crawl in your terminal, narrated by a language model running on your own machine (LM Studio, Ollama, Apple Intelligence) or through an API (Claude, or any OpenAI-compatible server). It looks like a DOS game and listens like a game master.

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
| **World generator** (code) | Builds a four-floor descent from a seed: three different dungeons, then Norfel. Rooms on a grid with floor plans, stairs guarded by a warden, shrines, trapped chests, fountains, elites, one secret per floor, a boss behind a locked door on floor 3 (beaten, it opens the stairs down) and Serpentis behind one at the bottom. Same seed, same run. |
| **Rules** (code) | List the legal actions each turn (the numbered choices) and resolve everything with d20 rolls: combat, telegraphed heavy blows, dodging, fleeing, searching, fixtures, leveling. |
| **Interpreter** (model) | Turns free text into JSON: one of the listed actions, a use of one thing on another (what's done, with what, to what: "throw the cheese at the ghoul", by the ids of what's in the room and what you carry), or a *creative* attempt with a stat, a difficulty, the props it uses, and effects from a fixed menu (stun, small damage, pacify, evade, reveal a secret...). The rules check the props exist, clamp the effects, roll the dice and apply them. "Summon a dragon" fails; "throw sand in its eyes" might stun it. Plain commands skip the model (a keyword matcher reads them the same way); handing something over, or anything said to a character, is the model's to read too. |
| **Narrator** (model) | Gets the list of facts that actually happened and streams a few sentences of prose. It tells what happened, not what the screen already shows: the room's things, who's here and the ways out are on the stage and in Here, so it names one only when something happens to it. It can't change the game state, so it can't make up loot or kill monsters. |

Each turn sends the model a small snapshot, not an ever-growing chat log, so local models stay fast: about 1-2 seconds a turn with Qwen3.6-35B-A3B in LM Studio. The snapshot reads oldest first: the floor, a few one-line notes on what happened before this turn, where the player was and is now (and whether they've been here before), the room's mood and what happened there before (rooms remember the
monster you killed, the chest you opened, the statue you toppled), and the facts of this turn, with the numbers the screen shows (damage, HP,
XP, counts, dice) left out.

Smaller local models slip, so the narration is checked against the facts a sentence at a time as it streams
(`src/ptg/llm/guard.py`). A sentence is left out if it echoes the prompt, talks about "the player" or being an AI,
puts choices to the player, calls a room it has never seen familiar, invents an exit, item or monster, lists the
ways out, says you took what still lies on the floor (or put on what's still in your pack), or runs past the length asked
for (the sentence that says how a fight ended is never cut for a name); if nothing survives, the facts are narrated
instead, with the numbers left off. To see how a model copes:

```bash
uv run python -m ptg.llm.check                                          # the model in your Settings
uv run python -m ptg.llm.check --url http://localhost:11434/v1 --model llama3.2:3b
```

It scores ten typed commands and five narrated moments, shows what the guard would cut and why, and times it all. The same check runs inside the game on the debug screen (F12, the Models tab), where you can pick any model the server offers and compare it with earlier checks. Without a model the game still runs: commands go through a keyword matcher and narration is stitched together from the facts.

## The loop

**Every turn**
- **Dice you roll yourself.** Skill checks open a big pixel-art d20, with what's at stake told before you roll: the number you need, your odds ("roll 8 or better · 65% chance"), your bonuses, what a hit would deal, and the die's twenty faces in a row, red for the ones that would fail and green for the ones that would succeed. Press Space (or click): it tumbles and bounces, the row flickers with it and marks the face it lands on, bonuses add up one by one, and the verdict is stamped in big pixel letters (on a smaller screen, the same in a column, the target in a line). Natural 20s glow gold and burst with light, natural 1s glow red and shake the screen; with advantage you roll two and the one you don't keep greys out. Attacks get small inline dice.
- **You can see how it went.** Every roll ends in a coloured verdict (✔ HIT, ✘ HIT YOU, • NOTHING, ★ CRITICAL!) and flashes its colour. The story's border lights up green when the turn goes your way, red when it doesn't and silver when it's mixed (or blinks gold or crimson for a 20 or a 1). Damage numbers rise off the monster, your HP changes show by your hearts, and a new floor gets a title card and a banner in the story.
- **Props and flair.** Using a real thing in the room or your pack ("topple the statue onto it") adds a ✦ flair bonus to the roll and earns a **Fate** token, if it changes something. A stunt wastes nothing: what it throws, pours, feeds or hands over is gone only if it worked (bribe an orc with stale bread and the orc has the bread; if it won't take it, you keep it), and a trick that can't change anything here (a lullaby for a rat) says why and costs nothing, not even a turn. Only what you do it with goes ("throw sand at the rat's eyes" spends no Pizza Rat), as much gold as you say ("offer 30 gold"), never your weapon or armor, and never a key (nor Lenny's bad tooth while he's waiting for it): a run could hang on it.
- **Things on things.** Say what you do with what, and it happens the one way: give Lenny his tooth or Swoogy a pickle (a character takes what it wants and hands back the rest), throw a pickle at the rat (anything throwable: a calm creature fights back), feed a beast what it's weak to or bribe a goblin with gold (a wits roll: it's handed over if it works), a small key or a bomb on a chest, the boss's key or a bomb on a door, a weapon to pry a chest open or a feature to search it, holy water or lamp oil on your blade (its next 3 hits count as holy, or fire). What can't work says why, and costs nothing.
- **Fate rerolls.** Spend Fate to rewind a failed check and roll again. Earn it with flair, perfect dodges, natural 20s and shrines.
- **Telegraphs.** Monsters wind up heavy blows a turn early (`⚠ HEAVY ATTACK NEXT`). Dodge or improvise an evasion to make them whiff, and get advantage and a Fate token.
- **Weaknesses.** Everything is weak to something: fire, holy, shiny, food, heavy, slippery... Turn the right prop on a monster to roll with advantage and hit harder. Once you discover a weakness, the bestiary remembers it forever.
- **A suggested trick.** The last choice (✦, in pink) is something you could really do here that the list doesn't spell out (a thing thrown that isn't made for throwing, a bribe, a feature worth a rummage), so new players learn they can improvise. Picking it does just that, and it never spends a potion or food you'll want for yourself; with nothing worth trying, there's none.
- **Here shows what's here.** Under the room's picture, a Here panel lists who and what is in the room (a character or a foe first, a shop's keeper and her wares, what lies on the floor, a chest or fountain, a spot worth searching), each as a tile with its picture, how it is (a foe's health and a big blow coming, "wants his bad tooth back", "▲ better than your Rusty Sword", "cursed! sticks to you") and a button for each thing you can do with it. The inventory (F2) shows everything you carry as tiles, with a button for each thing you can do with it: Equip, Drink, Throw, Drop, Sell, Give to…, Use on… (arrows pick one, Enter uses it). Carry more than one of a thing and its choices say how many (×2).
- **Picking up is free.** What you find searching, what's in a chest and what a monster drops lies where it turns up: press Take on its tile in Here, or take everything here with one choice; either way it costs no turn, so leave what you don't want. Bombs and small keys you don't even pick up: they're yours as soon as there's no fight. Put anything down again for free ("drop the bread", "leave the axe here"): it stays where you leave it, and no choice keeps offering it back.
- **Gear goes in your pack, never on the floor.** A weapon or armor you pick up, buy or are given goes on by itself only into an empty slot (armor, when you wear none). When something in your pack beats what you have on, a free choice says by how much and what it replaces: "Equip the War Pick (1d6 → 1d10) [replaces Rusty Sword · no turn]", and the old piece goes in your pack. Anything else goes on when you say so ("wield the hand axe", "take off the chain shirt"); say it of something you haven't got and you're told so. A weapon's or armor's powers count only while it's on; trinkets work from your pack.
- **Curses stick.** A cursed thing says so, and the first time you go to take it you're warned (so you can leave it); picking up everything here leaves it be. Once it's yours it won't leave you, can't be dropped, sold or given away, nor taken off once worn, until you pray at a shrine to lift the curse.
- **Rooms you can see.** The room you're in is the stage above the story: a pixel-art picture drawn from the room itself, as you see it from the doorway (its exits, decor, features, any monster and whatever's lying on the floor), shaped like a room and hidden when the screen is too short for it. The story under it is words only. Look (F4) shows it bigger.
- **Click a picture for its card.** The stage looks around the room; a character's, an item's or a fixture's picture in Here, or a coloured word in the story, opens its full card, with the matching action (for a friendly character, what they're there for: never a blow).
- **Easy to get around.** The ways out carry their arrows (▲ ▼ ◀ ▶) in the choices, and a pad of arrows in the side column (a bar of them above the choices, on a narrow screen) lights the doors there are: click one to go. Or type `n`, `s`, `e` or `w`. The buttons on Here's tiles are numbered first and the choices carry on from them, so typing a number does what clicking does. The screen fits itself to the window: two columns from 88 wide, one below that, a short status bar and a ☰ menu on a short one, and big buttons when played with a finger.

**Every run (about 25-40 minutes)**
- **Four floors.** Three different dungeons, getting harder; the third's boss guards the way down. Then **Norfel, Domain of Serpentis**, always the fourth: a purple poison cavern (after Metroid's Norfair), ten rooms, always a shrine, with Serpentis at the bottom.
- **Then deeper.** Beat Serpentis once, and every later run goes on down past her (her lair's floor cracks open as she falls): to **the Underbloom**, floor 5, a dark fungal deep where the only light is what grows and the torch you bring. Burn through the web door to the Sporefang Matriarch's lair (she'll trade the Philter of Light, a light that never burns down, for a certain cursed ring), and face the **Humongous Fungus** in the Spore Bed: the game's first fight against several foes at once, four parts each with its own health and its own job (one mends the others, one poisons you, one stuns you, one hits hard). Who to take down first is the fight. Daily runs stay four floors, the same for everyone.
- **Fights against several at once.** Each foe has its own health bar and its next move over its head; you face one at a time (turning to another costs nothing), and after your go every foe has its own. A bomb catches the others for half; fleeing gets you away from all of them. Sporerats never come alone.
- **Poison**, and **Burning** (2 a turn for three turns, and it can kill: water puts it out), **Stunned** (your next go lost, never two in a row) and **Mending** (`src/ptg/data/statuses.toml`; monsters can burn and mend too). Venomous bites, Serpentis's spit, Norfel's river and its gas vent poison you: -2 to your rolls and 2 HP a room walked and a fight's turn, shown by purple hearts and ☠ Poisoned. It never takes your last HP on its own, and it doesn't wear off: pray at a shrine (free, as often as you like) or drink **Pure** (it also stops the next poisoning). Norfel's monsters are deeper and half of them venomous.
- **Norfel's hazards are choices.** Nothing rolls as you walk in. One poison river on the way to the boss: leap it (agility), wade it (poisoned) or vault it with a ten-foot pole, and once you're over you know its stepping stones. One gas vent, over a cache: disarm it first, or grab the loot and take the gas.
- **Get ready a floor ahead.** Floor 3 always has Granny's shop, and asked what she knows she brings out an old smelly snakeskin for 80 gold: +2 armor that poison can't get past, against the +3 you likely wear. Items can cure, guard against and ward off statuses (`cures`, `guards`, `wards` in `items.toml`).
- **Pick one of three perks** at each level-up (Ruthless, Acrobatics, Vampiric, Glass Cannon...).
- **Traits earned by how you play**: talk monsters down and you become *Silver Tongue*; win with props and you become a *Showboat*; dodge enough and you become a *Duelist*.
- See what's through a door before you go: the map and choices show stairs `>`, shrines `†`, chests `■` and fountains `◊` ahead.
- **Things that do things.** Beyond their numbers, some items have powers, on their cards and tiles: Weighted Dice add 1 to every roll you make, a Torch 1 to searching, the Ten-Foot Pole 2 to picking locks and disarming traps; the Mysterious Floppy Disk maps the whole floor when you pick it up; flasks, holy water and the odd grenade can be thrown in a fight (and are gone); a Laser Pointer or a Rubber Duck costs a monster its next attack, once a fight; a Glow Stick lights up anything hidden in a room. Some are a mixed blessing. Some change your stats while you carry them (Lenny's Bad Tooth: +1 might, -1 wits; the Unusual Butter: +1 to everything and 5 more max HP), Swoogy's Diaper keeps monsters' hits 2 lighter but costs max HP every floor, and eating a Jar o' Light in a fight makes the monster flee.
- **Characters, not just monsters** (most made by the kids in the maker), who say what they say in their own words: a card with their picture, written in `src/ptg/data/dialogue.toml`, when you walk in on them, talk to them (free: no roll, no turn), hand them something, play their game or cross them. **Lucky Lenny** turns up calm in some runs: a goblin knocked his bad tooth out with a pan, and it's hidden somewhere on his floor. Talk to him and he points you to it, as often as you like; give it back and he yanks out his good one for you (+1 to every roll). Hit him and he fights back, but his tooth still calms him down. **Swoogy the Gooey** waits in some secret rooms with a die: guess his number and his diaper is yours (it lands at your feet: it's cursed, so you may rather leave it); guess wrong and he charges up his flaps, so calm him down with something you carry (gold, a potion, anything: he keeps it, and his diaper), fight him (he's strong), or get away and come back. **King Mouse** guards the stairs on floor 2 now and then (squeak), and leaves his vest. The shopkeepers greet you, thank you and chat, and anyone the maker tags NPC gets a few friendly lines until they have their own. Where each one's story has got to is kept for the run (the map marks Lenny with ☺ while he waits on his tooth), and story events can read and move it. Some monsters have tricks: **Baby Joey** grabs your food (or gold) and runs off with it unless you stop him, and **Swamp Bottoms**' vines stop you running away.
- **Rare things.** Some items never lie about on a floor or drop from an everyday monster: they're kept in chests, hidden stashes, each floor's secret room, shops, and by the warden at the stairs (always) or an elite (sometimes), and each turns up at most once a run. The floor caps how good a warden's is, so the best come deeper, and from secret rooms. A warden with nothing rare left to give carries a small key.
- **Bombs and small keys** (● and ⚷ by your hearts). You start with a bomb; monsters drop bombs and keys now and then, elites more often. A chest opens three ways: a small key (safe), picking its lock (agility: fail and a needle gets you) or smashing it (might: fail and what's inside breaks); or blow it open with a bomb (it always opens, and what's inside always breaks). A bomb thrown in a fight always goes off.
- **A secret room on every floor**, sealed until you bomb a wall into it. It's only ever built in a gap in the map that touches two rooms or more, so you can work out where it might be, and only those walls offer a bomb. Search a room next to it and you may feel a draft. There's one a floor: once it's open, no wall is worth a bomb. Finding it is a moment: a bang, a fanfare, a banner across the story, and the room in gold on the map, `{✧}`, from then on.
- **Shops, now and then** (about one floor in four; always on floor 3, and half the time on Norfel, where she always has two Pure): a nook off the map, `[¤]`, behind a door a small key opens or two bombs break. Granny Gristle keeps most of them: potions (two of them), gear for the floor, a bomb or a small key, and a trinket or, sometimes, something rare. Once in a while it's Granny Kamultruk's instead, the rare one, with the best and dearest stock. Shopping has a screen of its own: her wares as pictures with their prices; pick one for its card, Enter to buy, B to haggle (wits: a third off, or a quarter dearer if it goes wrong, once a ware). She buys too, at half her price ("sell the hand axe"): anything but a key, a quest's things, a curse or the weapon in your hand. Mama's Shillelagh, sold nowhere else, helps you talk. Walking into one gets a jingle and a banner, gold and starrier for Granny Kamultruk.
- **Creatures that have stopped fighting know things.** Ask one what it knows (or, if it can't talk, watch where it goes), or a shopkeeper: a wits roll, once each. It may put the floor's secret room or its hidden stash on your map (the stash as a gold `$`, and there when you search it), or, if it talks, tell you what one of the floor's monsters can't stand, the warden's or the boss's first.

**Across runs**
- **Souls** carry over when you die. Spend them at **the campfire** on **blessings** (permanent upgrades) and **gifts** (a starting item for your next descent).
- **The Hall of Legends** lists every run with an epitaph the narrator writes for your tombstone.
- **Your ghost haunts later runs.** Die, and your adventurer may come back as a ghost on that floor, guarding what they carried (but not their keys, the characters' own things like Lenny's teeth or Swoogy's diaper, or a rare thing this run has had already). Lay them to rest to get it back.
- **The Void**, the voice by the campfire, remembers how your last run went.
- **Daily descent.** Everyone gets the same dungeon each day; you get a spoiler-free result card to share.

## Story events

Scripted moments live in `src/ptg/data/story/` as small Markdown files: a header saying when they fire
(entering a room, meeting a character, finding a thing, typing a magic word, a natural 20, defeating a monster...),
then text written in your own words, optional choices that also accept free text, and effects like `[hp -6]`,
`[give oil_flask]`, `[mark mirror_unbroken]`, `[secret]` or `[npc lucky_lenny done]` (a character's story moved on).
Marks and the **Book of Secrets** survive death. They work with no AI at all. See [docs/writing-events.md](docs/writing-events.md).

```bash
uv run python -m ptg.story                    # check every story file
uv run ptg --event mirror_trial               # jump straight into one
```

While you write, the debug screen's Story tab (F12) reloads the files without restarting the game, shows any
problems, and can fire any event at the start of your next descent.

## Data files

All game content (themes, rooms, items, monsters, statuses, perks, unlocks, tags, art, story events, what the
characters say) is plain data in `src/ptg/data/`, checked on startup: a mistake is explained by file, entry and field
("monsters.toml [monster.goblin]: unknown field 'hpp' (did you mean 'hp'?)") instead of crashing. The shipped files are
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
the dark), and a used one looks it from then on (an emptied chest, a shrine with its candles out, a dry fountain).
A run ends on a pixel tombstone with your name carved in it, or a glinting crown. Story events can put a sprite
on their card (`sprite:` in the header, see [docs/writing-events.md](docs/writing-events.md)). The poses are made
from each sprite's own frames, so new art gets them for free. Characters are always in their own colours: a calm
one (Lucky Lenny, or something you've talked down) says so in words, never by greying out.

An item, a character or a fixture is drawn the same way wherever it is, in the story, on a card, in the inventory, the
shop, the bestiary or the sidebar (`Picture` in `ui/widgets.py`): full size and moving, all in step on one clock
(only what's on the screen moves), and small only where there isn't room for full size, picked by the space it's
given, across and down.

Sprites live in `src/ptg/data/sprites/` as PNG strips: frames side by side, each 24 pixels wide (12 for a small
version) and any height, on a transparent background (they're scaled to fit). The PNG also stores its `frames`
count; an editor that drops it is fine as long as the frames are 24 pixels wide. The shipped ones are drawn
as colour maps in `tools/build_sprites.py`, which adds outlines, shading and animation frames; the d20 is drawn
in code (`dice_art.py`) so it can show any number:

```bash
uv run python tools/build_sprites.py --sheet sheet.png   # rebuild, plus an 8x preview sheet
uv run python -m ptg.sprites goblin troll                # preview sprites in your terminal
```

To use your own art (Aseprite, Piskel, an image model), drop a PNG named after the monster's key
(`goblin.png`, `drowned_abbot.png`...) into that folder.

**Clips.** A monster can also have animations made for it elsewhere, frame by frame: a boss's entrance, say. The
Blender pipeline in `spikes/goblin3d` turns a sprite into a model, animates it and renders it back into pixels in the
sprite's own colours (the Goblin King's entrance was made that way). Its frames become clips with
`tools/make_clip.py`, one folder of numbered PNGs (one direction's) at a time, in a few sizes:

```bash
uv run python tools/make_clip.py spikes/goblin3d/king/frames_48/Entrance/0 goblin_king entrance --fps 24
uv run python tools/make_clip.py spikes/goblin3d/king/frames_48/Idle/0 goblin_king idle --fps 24
```

That writes `src/ptg/data/clips/goblin_king/entrance.48.png` (the frames side by side, their count, speed and the
frame the feet land on kept in the PNG). When a fight with the monster starts, the stage plays its `entrance` (at
most 12 frames a second, with the fight's sting as it lands) and keeps it in its `idle` for the rest of the fight, at
the biggest size whose standing art fits the stage; a monster without clips sweeps in from the side instead. So a
clip-made monster needs both, and 40, 48 and 64 pixels cover a laptop's screen to a big one. Two more are optional:
an `attack`, played each time it goes for you, and a `windup`, how it stands while a heavy blow is coming. `--frames`
cuts one from part of a folder: the King's are the swing at the end of his fall, and the pan held high before it.

```bash
uv run python tools/make_clip.py spikes/goblin3d/king/frames_48/Entrance/0 goblin_king attack --fps 24 --frames 53:73 --land 6
uv run python tools/make_clip.py spikes/goblin3d/king/frames_48/Entrance/0 goblin_king windup --fps 24 --frames 46:57
```

Every boss (and guardian: King Mouse) is called out by name as it lands, clip or not: spelled out on a crimson card
where its banner will be, with what it's boss of (or guarding) under it. King Mouse has clips too, from the same
pipeline: he drops in, flexes and roars, swipes with his claw and raises it for a heavy blow. Make a clip's sizes so
the standing figure is about 21, 25, 32 and (for big screens) 42 pixels tall: that's what the stage picks from.
The Underbloom's have them too: the Sporefang Matriarch drops in on a silk line and screeches as she lands, and in
the Spore Bed the Humongous Fungus and its three helpers come in together and swing at once, side by side at one size
(a crowd's clips: `encounter.Fight`).

**Small versions.** Where there isn't room for full size (the inventory's and the shop's tiles on a smaller screen,
a short sidebar, the things lying in a room's picture) a sprite is drawn small, 12 pixels wide, and pixel art
doesn't shrink well. So each item can have a hand-made small version: a 12×12 PNG strip with the same frames, in
`src/ptg/data/sprites/small/` under the same name (`item_healing_potion.png`), best drawn in the big sprite's own
colours with the bottom row left empty for the bob. The Monster & Item Maker draws them too (below), and its import
puts them there. Without one, the big sprite is halved block by block, which keeps its lines whole but looks rough.
The debug screen (F12) shows every small version beside the big one, and lists the items still being halved; its
Art tab also flags art that takes up less than half its frame (it looks tiny on cards and in rooms) and colours from
outside the maker's palette.
An item with no art at all shows a plain grey stand-in for its kind (a blade, a jerkin, a loaf, a key...), at either
size, and its inventory card says it has no picture yet.

**Room pictures.** The picture of a room (in the story when you first walk in, and in Look) is drawn in code
(`room_picture.py`), not from art files, so every room the game makes has one. It's the view from the door you came
in by, in one-point perspective and in the dungeon's own look: the Crypt's bricks and candles, the Warren's earth,
timber and torches, the Ruins' marble. Exits are doorways in their walls (dark if unexplored, planked and barred in
brass if locked); the room map's decor stands where the map has it (water, pillars, tables, cages, plants,
fungus...); each feature is a small prop of its kind, from its name ("a half-sunken pew", "the throne of chairs");
the fixture and items are their own sprites (items at their 12-pixel small size, never smaller in a picture as tall
as the story card's; halved in a shorter one wherever the monster would be, so a potion is never as big as it); and
candles, torches and glowing things light what's near them. Whoever is in the room stands where the room map has
them, steps aside rather than stand in front of the fixture or hide most of a feature or an item, and is drawn last,
so nothing hides them; items step aside from them and from the fixture (and a feature from them, rather than be half
hidden), and nothing you can do something with is cut off at the picture's edges. Add `sky` to a room's `decor` in
`rooms.toml` and its walls stand broken under the stars. Every colour is one the sprites already use, so the
pictures don't strain a GPU terminal's glyph cache. A new dungeon borrows the Crypt's look until it's given one
(`LOOKS` in `room_picture.py`).

```bash
uv run python -m ptg.room_picture 7     # every room on the first floor of seed 7, in your terminal
```

## The Monster & Item Maker

`docs/maker` is a one-page web app for drawing monsters and items and setting their stats, hosted free on GitHub
Pages so friends can contribute. It works on a laptop, a tablet or a phone, with nothing to install:

- **Draw** on a 24x24 grid in the game's own 32 colours plus any colour you pick (kept as "your colours"), with
  pencil, eraser, fill, colour picker, mirror mode, undo and redo (B, E, G, I, M and Ctrl/Cmd+Z), and up to four
  frames for the idle animation: two is the usual (an empty second one bobs), and frames 3 and 4 make a longer loop,
  each drawn over a faint copy of the one before. The preview shows it moving, the way it'll look in the dungeon.
- **A small version** (items): a 12x12 board under the drawing for how the game shows the item where it's short of
  room (the inventory's tiles on a smaller screen, the room's picture).
  It starts as the drawing halved exactly the way the game would; draw on it to fix it up by hand, with the same
  tools, frames and undo. Once it's hand-made it stops following the drawing, says so if the drawing changes after,
  and "Start again from the drawing" goes back. Only a hand-made one is sent, and imported.
- **Set everything**: tier (with typical values for it, one click to apply), HP, defense, attack, damage dice and XP;
  creature type; the floors it shows up on (pick none and it's every floor its creature type fits, which for a beast
  is most of them; Norfel, the fourth, only has tier 3 and up); weaknesses; any extra tags; whether it can be
  reasoned with; its heavy-attack tell; and a description, which the in-game narrator reads so it describes the thing
  the way its creator imagined. Items get their kind, tier, damage, defense, healing or escape, tags and description.
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

When `tools/maker_saves.gs` changes (it learned to keep an item's small version, and a monster's floors), paste it in
again and publish it: Deploy → Manage deployments → Edit → Version: New version → Deploy. The URL stays the same.
Until then the old script quietly leaves out what it doesn't know, and links and downloads still carry everything.

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
uv run ptg export                       # refresh the page's library by hand (after changing a sprite or
                                        # an entry yourself, so the page doesn't send the old one back)
```

`--saves` reads the shared library from `docs/maker/config.json` (or `--url`). A save counts as in the game once the
game has something by its name from the same creator, the same rule the page uses to move it to the game's shelf, so
picking one twice doesn't add it twice. Submissions from before Save, made as GitHub issues with "[maker]" in the
title, can still be brought in with `uv run ptg import --github` (`--dry-run` to look first; it needs the GitHub CLI
logged in, and comments on and closes each issue it imports).

Each import writes the sprite (`src/ptg/data/sprites`), the entry in `monsters.toml` or `items.toml` with a
`# drawn by` credit (the GitHub username if the maker left their name blank), ASCII art for a new monster's ASCII
mode, checks the whole game still loads before writing anything, re-signs the data, and refreshes
`docs/maker/library.json`. A submission that doesn't load is reported and skipped; the rest still go in. It also
says when a drawing uses colours from outside the maker's 32: they show, but each is one more colour for the game
(and a GPU terminal) to keep, so swapping them for the nearest palette colour keeps the art in step. Commit and push,
and the page's library shows them too. A re-import of an older save puts back that save's picture: to change art
that's been touched up in the game since (an outline, tidied colours, a new small version), start from it in the
maker's library, which `uv run ptg export` keeps up to date, not from the old save. The change keeps what only the
game gives it (powers, stats, tricks, where it's found), and is credited to the name in its "Created by": put the
artist's there to keep their credit.

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

**Claude at the drawing board**: `uv run ptg maker` serves the maker on this computer with a Claude panel beside the
boards. Ask for a monster or an item and Claude draws it on the maker's own boards, frame by frame (you watch each
stroke land, and can undo it or draw over it), gives it fair numbers for its tier and the floors that suit it, looks
at it the way a fight shows it (the game's own poses: idle, windup, dizzy, lunge, shake, hit, death) and at an item's
small version, and runs the checks: the maker's rules, the game's own art tests (an outline, filling its frame, idle
frames that keep their feet, a small version that matches, the floors' splash colours) and the importer, as a dry run.
Then save it as usual, or press "Add to the game…", which does what `uv run ptg import` would once you've seen what
that is. The art rules are in its instructions (`src/ptg/maker.py`), so what it makes goes in as it is.

```bash
uv run ptg maker                        # opens http://127.0.0.1:8770
uv run ptg maker --port 8800 --no-browser
```

It needs the claude extra (`uv sync --extra claude --extra web`) and a key: `ANTHROPIC_API_KEY`, an `ant auth login`
profile, or the Claude key in the game's settings. The key stays with the server, which makes every call to Claude:
the page never sees it, and the server answers only this computer. Claude Opus 5.5 at medium effort is the default
(the panel picks Sonnet 5.5 or Haiku 5.5 and the effort too), a declined request is retried on another model, and the
panel keeps a running estimate of what the chat has cost. On GitHub Pages there's no panel.

## Sound

Short 8-bit effects for the moments that matter: the d20 clattering and landing, hits and misses, coins, secrets,
the stairs, level-ups, a natural 20. A terminal can only beep, so the game plays its own sound: a small mixer on a
thread of its own streams to your speakers through [sounddevice](https://python-sounddevice.readthedocs.io)
(PortAudio, bundled on macOS and Windows; on Linux install `libportaudio2`), with the system's player (`afplay`,
`pw-play`, `paplay`, `aplay`) as a fallback. Sound never blocks or crashes the game. F8 turns it on and off,
Settings has the volume, and `PTG_SOUND=0` keeps it quiet (the tests do). Played in a browser, the page plays it
(see "Play it in a browser").

The built-in sounds are synthesized, like the sprites: `tools/build_sounds.py` describes each one as a few
chip-style tones (square, triangle and noise waves, pitch slides, arpeggios, and a low-pass filter to soften one) and
writes 22 kHz WAVs to `src/ptg/data/sounds`: 8-bit for the crunchy ones, 16-bit for music and the softened ones. Tweak
one and rebuild. The fighting and walking sounds come in variations, a bright one and a duller, softer one, played at
random. The music is all original:

- the title screen's, a 20-second loop (a glassy figure in 7/8 over a falling bass, then a slow line and tubular
  bells), with the thunder that follows each flash of lightning there: a deep boom, then a low rumble rolling on;
- a floor's, slow and atmospheric (D minor: a soft pad, notes dripping and echoing, a lonely tune), and on the boss
  floors a darker one (a choir, a heartbeat, a music box);
- a fight's, fast, in the style of the old console RPGs' battle themes (octave bass, racing strings, brass stabs, a
  bold tune), and a boss's own, heavier (a galloping riff, an organ, toms).

A fight's music cuts in as a monster comes for you, and the floor's fades back once it's over.

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

The title screen is a castle on a crag in a thunderstorm, drawn in code at whatever size your terminal has room
for (`title_scene.py`): the rain falls, and every few seconds lightning strikes, the castle lights up, something stands
on the ridge for as long as the flash lasts, and the thunder rolls in after it. The first launch opens Settings: pick LM Studio, Ollama, Apple Intelligence, another OpenAI-compatible server, Claude, or Offline, pixel sprites or ASCII art, and whether dice roll on Space or automatically. Settings, saves and the profile database live in `~/.ptg` (set `PTG_HOME` to move them). The game autosaves every turn; **Continue** on the title screen picks up where you left off, with a line where the story so far stops, the room as you'd see it walking in (anything lying there ready to take) and where you are. While a run is unfinished, Continue comes first, with the run shown under it. Starting a new one instead asks first, and abandoning a run counts as a death: you keep its souls, it goes in the Hall of Legends, and your ghost stays on the floor where you left it.

On a screen at least 110x32 the game plays in **tabs** (Settings, Game screen; Classic is the other choice, and a
touch screen or a smaller terminal always gets it), laid out like an illustrated storybook: the words on the left
(the story, the choices under it, one to a line, and a few lines of what happened lately, notifications included),
and everything else on the right (the room's picture, the arrows, and one pane with tabs). The tabs are Here
(whoever and whatever is in the room: the one in focus at full size with everything about it beside it, the rest as
thumbnails to click; a bare room fills it with the floor and the quests), Map (the floor drawn big, rooms named, with
the goal and how far, the quests open, the tips you've had and the key), Pack, Sheet (every number the status bar
shortens, said in full, then your stats and rolls), Journal and Bestiary. Their keys bring them into the pane;
pressed again, or the ⤢ at the end of the tabs, they open in full as the panels below. A tab stays where you put it
from room to room, and a fight brings Here back. Gold, bombs and small keys you find say so in the story ("+6 ¤
gold (21)") and light up their counter on the status bar. Here wears a ● while another tab is showing and the room
has someone or something in it. Click a room on the map you've been in to **travel** back to it, past nothing hostile;
now and then something that's wandered in stops you on the way (twice a floor at most).

Or choose **Grid** (Settings, Game screen), laid out like an old CRPG's screen, every box a fixed size that lines up
with the one beside it, so nothing moves as choices come and go: the room's picture across the top with the map
beside it (each room a box with its name); under them the story, a column easy to read with the command line at its
foot, the decision beside it at eye height, and Here. The decision is six big buttons in fixed places, in a fight
Attack, Dodge, Heal, Throw, Use and Flee, out of one Search, Rest, Heal, Bomb, Use and Gear, each lit, opened, urgent
(Dodge as a heavy blow comes, Heal when you're low) or greyed out with why. Under them, out of a fight, a compass of
five cells that never move: each way out says where it goes and what's there, a wall stays a faint wall (the arrow
keys move too). Then your things as cards, a picture each with what it would do and how it would go ("weak to
fire!"), lit if you can use it now, dim with why if not; in a fight they take the compass's place, and a button with
several options shows only its own (pick with a click or a letter). Here is in sections, who's here, the things and
what there is to search, a heading each, with the journal's last lines (Lately) in the rows they leave; in a fight,
how the last turn went (hits, misses, damage) under the foe's card. The Map panel is the floor drawn on parchment,
the rooms in ink (in pencil where you've only seen them; one you can travel back to lights up gold under the mouse),
the journal is written on a page of it, and each panel's name is spaced out in its own colour. On a narrower screen the decision goes under the
story, its buttons in a row with the compass beside them.

With a model narrating, you needn't wait for it: a move made while it's still talking cuts it short (what it has
said whole stays) and is made at once, and walking back into a room you've been in, with nothing waiting there, is
told in the game's own line rather than the narrator's.

| Key | Typed | Opens |
| --- | --- | --- |
| F1 | `help` | how to play |
| F2 | `i` | inventory: what you carry, with its art (arrows pick, Enter uses) |
| F3 | `c` | character: perks, traits and progress toward the next one |
| F4 | `l` | the room as it is now: its picture, who and what's in it, its exits and floor plan |
| F5 | `m` | the floor map and the whole descent |
| F6 | `b` | bestiary: art, kills, discovered weaknesses, lore |
| F7 | `j` | journal |
| F8 | | sound on or off |
| F12 | | the debug screen |
| Ctrl+L | | redraw the screen |

Esc closes a panel, and F1-F7 in one switch to that panel instead (its own key closes it); PgUp and PgDn read back through the story, which follows each turn from its start (a taller turn stays put at its command, with the picture under it); in the story, press Esc twice for the title screen (your game is saved). A level-up's cards can wait: close them and the perks stay among the choices. Panels keep their size while they're open, whatever you pick in them, and they, the dice and the campfire fit a terminal as small as 80x24.

Everything works with a mouse too: click a choice, a button on a tile, an arrow on the pad, a highlighted word, a picture (for its card) or the dice (once to roll, again to carry on), and close a panel with its ✕ or a click outside it. Type `n`, `s`, `e` or `w` to go that way.

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
on Textual's `textual-serve`, which runs one game for each browser tab. Laptops and tablets play it fully.

Sound and music play in each player's browser, not on the server: the game tells the page which sound to play, and
the page plays it. Browsers only allow sound once the page has been clicked, tapped or typed in, so it starts with
your first move. An iPhone set to silent may keep it quiet. F8 or Settings turns it off, and so does the ☰ menu on
a phone. The page loads the short sounds in the background once the game first asks for one (1.4 MB) and each piece of
music when it's first wanted (up to 2 MB each), and the browser keeps them. A player's own sounds (below) play only
in a terminal.

The game's page is made for phones too (`src/ptg/web/app_index.html`). It picks a font size that fits at least 40
columns, keeps the game above the phone's keyboard, and scrolls with a swipe. Taps play the game, so the keyboard
stays down until the keyboard button (bottom right) is tapped; a keyboard plugged in types either way. A browser
played with a finger tells its game so (`PTG_TOUCH=1`), whatever the screen's size. Add `?fontsize=12` to a game's
address to pick the size yourself. The narrow layout for phone screens is planned in
`docs/plans/cross-platform-and-mobile.md`.

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
   | `ANTHROPIC_API_KEY` | Your key, for Claude to narrate with: players need no AI of their own (they never see it). On its own it changes nothing: the games stay offline. |
   | `PTG_NARRATOR` | `claude` has Claude narrate every player's game, on your key. Without it (the default), every game is narrated offline: the facts told as they are, nothing spent. With the key set, a test room can still have Claude for itself (below). |
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
in plays out as it would in a run. Lucky Lenny (his bad tooth is in your pack, as if you'd found it first; or, in
`lenny_quest`, still hidden on his floor, for him to tell you where), Swoogy (behind a wall to bomb, with
a bomb), King Mouse (at the floor-2 stairs), either shop (at its door, with a small key, two bombs and 100 gold to
spend; on floor 3, ask Granny for her snakeskin), each boss (at its locked door, with its key: Serpentis's is on
floor 4, the Humongous Fungus's on floor 5), poisoned already beside a shrine with a Pure in your pack (`poison`), by
the web over the Sporefang Matriarch's lair with a torch and the Ring she wants (`matriarch`), the Underbloom's dark
with a torch or without (`underbloom`, `underbloom_dark`), or any monster.

Pick a kit: a new adventurer (`new`), what a run might have by that floor (`random`: gear, level and a perk for each
level), the best of everything (`strong`), or your own (`weapon=war_pick,armor=chain_shirt,items=holy_water+pickle,
level=3,gold=50,bombs=2,keys=1`, anything left out as a new adventurer has it). Most can be tried on any floor, 1 to
5 (4 is Norfel, 5 the Underbloom); the Underbloom's own monsters (the Sporerat, the Hollowed) are tried down there
unless you say, and down in the dark you're given a torch, as a run would bring one (except in `underbloom_dark`).

Nothing in a test room counts: it never saves over your run, banks no souls, and leaves your Hall of Legends,
ghosts and bestiary as they were. Esc twice leaves it.

```bash
uv run ptg --test-room list                                  # who, and the kits
uv run ptg --test-room king_mouse --loadout strong
uv run ptg --test-room shiny_shop --loadout new --floor 3
uv run ptg --test-room serpentis                              # Norfel's boss, at its lair's door
uv run ptg --test-room orc --floor 4                          # anywhere on Norfel: its river, its vent
uv run ptg --test-room matriarch                              # the web door, her lair, her trade
uv run ptg --test-room humongous_fungus --loadout strong      # the Spore Bed: four foes at once
uv run ptg --test-room goblin --loadout "weapon=war_pick,items=pickle+pickle"
```

On the debug screen (F12, then 0) the same choices show the kit you'll get before you go (↻ for another draw). On
the browser version, `PTG_TEST_ROOMS=1` puts a test-rooms page at `/test`, under the tester's own name: when they
leave a test room they're back at their own title screen, their run where they left it. With `ANTHROPIC_API_KEY`
set, its **Narrator** choice has Claude narrate just that test room, to try the narrator out while every other game
stays offline.

## Project layout

How the pieces fit (the layers, a turn's flow, where state lives, where to extend) is in
[docs/architecture.md](docs/architecture.md).

```
src/ptg/
  data/            themes, rooms, items, monsters, perks, unlocks, prop tags, the characters' lines (TOML), art
                   and story/ events
  content.py       loads and validates the data (broken data fails loudly)
  world.py         seeded floors: layout, stairs, fixtures, elites, loot, ghosts, the secret room, the map
  loot.py          what turns up where: loot by kind and tier, read from the items, and where rare things are kept
  powers.py        what items do beyond their numbers: roll bonuses, maps, throwing, distracting, curses
  npcs.py          characters who aren't just monsters: Lucky Lenny, Swoogy, King Mouse, anyone tagged npc; what
                   they say (data/dialogue.toml), Talk, and where their stories have got to
  layout.py        room floor plans and where things stand
  models.py        game state (pydantic; a save file is just this as JSON)
  dice.py          d20 checks with advantage, as data the UI can animate
  rules.py         available actions, movement, items, fixtures, chests, bombs, perks, traits
  combat.py        attacks, intents shown a turn ahead (foresee), danger, dodging, fleeing, defeat and its style
  scene.py         what's here to act on, as typed refs (the room's view): monster, fixture, exits, pack, gold...
  interactions.py  the interaction grid: what (verb, thing, target) comes to, each thing's verbs, pickers
  creative.py      free-text stunts the grid has no row for: props, flair, weaknesses, clamped effects
  game.py          one turn: interpret -> resolve -> (reroll) -> narrate -> save -> profile
  profile.py       SQLite: souls, unlocks, Hall of Legends, bestiary, ghosts, turn log
  meta.py          building the adventurer from unlocks, starting runs, scoring the end
  testrooms.py     test rooms: next door to anyone, with any kit, counting for nothing
  sprites.py       PNG sprites rendered as half-block pixel art, their poses, and monsters' clips
  room_picture.py  pictures of rooms, seen from the doorway, drawn in code from the room itself
  encounter.py     a fight on the stage: the foe big in the dimmed room, its intent and banner, its entrance, its
                   shatter, the spoils card, and the wipe back to the room
  dice_art.py      the pixel-art d20
  sound.py         sound effects and music: the sound bank, your own sounds, and playing them
  library.py       the Monster & Item Maker's library: export it, and import what's made there
  maker.py         `ptg maker`: the maker on this computer, with Claude to draw, and the game's checks for its art
  glossary.py      the terms highlighted in the story
  integrity.py     fingerprints of the shipped data, and noticing edits
  story/           story events: file format, checker, and the engine that plays them
  llm/             backends (OpenAI-compatible, Claude), prompts, interpreter, narrator, guard, check, extras
  ui/              Textual app: title, settings, campfire, game screen, dice, panels, endings, debug screen
  cli.py           `ptg` entry point and plain-text mode
  serve.py         `ptg serve`: the game in web browsers, a name and saves for each player
  web/             the game's web page under `ptg serve`, made for phones too
tests/             world, rules, profile, interpreter and UI tests, plus a bot that plays whole runs
docs/maker/        the Monster & Item Maker page and its library.json (GitHub Pages serves docs/)
tools/             build_sprites.py: the hand-drawn sprite maps; build_sounds.py: the synthesized sounds;
                   make_clip.py: a monster's clips from rendered frames; maker_saves.gs: the maker's shared library
                   (a Google Apps Script)
legacy/            the v1 curses prototype, kept for reference
```

Add a theme with a `[[theme]]` block in `themes.toml`, its room archetypes in `rooms.toml`, and tagged monsters in `monsters.toml`: a monster turns up in every theme whose `monster_tags` it has, unless its `dungeons` keep it to some (`dungeons = ["sunken_crypt", "norfel"]`, theme keys). Give a room feature new powers by adding its keyword to `tags.toml`. No code changes needed. A theme with a `floor` is always that floor (Norfel: `floor = 4`) instead of one of the three shuffled dungeons, and one with a `status` (Norfel's `"poison"`) makes it that status's floor: its shops sell the cure, it always has a shrine, and Granny brings out something against it on the floor above. A new status is a row in `statuses.toml`; items `cures`, `guards` and `wards` it.

## Tests

```bash
uv run pytest
```

It runs in parallel, one worker a core (about a minute); add `-n0` to run tests one at a time, for a debugger or
`print()`. The suite includes a bot that plays 100 seeded runs using only the listed actions. It never improvises, shops or bombs a wall; as a newcomer (no blessings) it wins about one run in seven of the four floors, and as a veteran (every blessing, picking its perks well) about three in five. Those win rates guard against balance regressions (docs/plans/combat-and-balance.md).

For balance, `tools/simulate.py` plays many seeds and reports each floor (who reached it, who died there and of
what, what they took down the stairs) and how poison went:

```bash
uv run python tools/simulate.py 300                  # the plain bot (tests/bot.py)
uv run python tools/simulate.py 200 --compare        # every player, from the careful to the sloppy
uv run python tools/simulate.py 600 --veteran --fights  # a veteran's adventurer, and what each fight cost
uv run python tools/simulate.py 300 --venom orc,troll   # as if they bit with venom
```
