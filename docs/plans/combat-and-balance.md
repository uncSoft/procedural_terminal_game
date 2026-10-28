# Combat as an event, and the balance under it

The plan for the next phase: fights that feel like events, and numbers that keep them dangerous to the end. Written
2026-10-28 after a won run ("Adventurer the Nosy", level 8, 20 kills, 249 turns) and the owner's notes on it:
high-tier things turn up too often, the player's damage runs away from the monsters by the end, nothing feels rare,
levels come too fast, and a fight is "monster appears, click attack, dodge or heal until it dies".

It builds on [progression-loot-difficulty.md](progression-loot-difficulty.md), whose diagnosis still holds; most of
its §3.2–3.3 ("the curve") was never built. This plan takes the parts the numbers below support, at gentler strengths.

**Status:** steps 1 and 2 of §7 are built (2026-10-28): the balance pass, the cleanup, the simulator's veteran and
fights report, and the encounter, intents, finish and spoils, with narration kept for a fight's opening and end. §9
has what was built and how it measures. The run is to grow to 10–12 floors, each darker and more desperate, with an
endgame reached over several runs, so the tuning is written by depth (how far down the run a floor is), not by floor
number.

## 1. What the run and the bots say

### The run

| | |
|---|---|
| Level | 8 (the cap) by floor 4, with 7 perks and 8 campfire blessings |
| The player's hit | 36–44 on the big swings: Ruthless doubled a stack of +5 might, +3 Glass Cannon, +1 Brute, +2 holy and 2d6 |
| Serpentis (75 HP) | down in four swings; its attack is +3, a floor-1 goblin's, and bosses don't get the depth bonus |
| Rare things | 14 on the run's list, at least 11 in hand; two Silvered Blades on floor 3 (a stash, then a chest) |
| Potions | 10 healing potions unused at the end |

### The bots

`tools/simulate.py`'s bot plays as a newcomer would: no blessings, the first perk it's offered. A second bot, the
**veteran**, has the run's eight blessings and the Rabbit's Foot and picks perks the way the run did (Ruthless, Glass
Cannon, Brawler, Acrobatics, Iron Skin first). Neither shops, bombs walls or improvises, so a person who does (the
run did all three) does better than either. 600 seeds each:

| | plain bot | veteran bot |
|---|---|---|
| Wins | 21% | 72% |
| Deaths on floors 1 / 2 / 3 / 4 | 21% / **50%** / 23% / 31% | 3% / 16% / 5% / 7% |
| Level at the stairs of floors 1 / 2 / 3, and at the end | 3 / 5 / 6, 7 | 3 / 5 / 6, 7 |
| HP an ordinary fight costs on floor 4 (median) | 19% | **0%** |
| HP the last boss costs (median) | 49% | 22% |

The curve is wrong at both ends: a newcomer meets tier-3 monsters on floor 2 and dies there half the time, while a
veteran's floor-4 fights cost nothing at all (Acrobatics takes the first blow in every room, and the monster is dead
by the third).

## 2. The balance pass

### Target levels

**Leave floor 1 at level 2, floor 2 at 3–4, floor 3 at 5, and meet Serpentis at 6** (7 for a thorough clear). That's
a level-up or two a floor, each one a perk you'll feel. Level 8 stays the cap: there for anyone who grinds (resting
draws ambushes, quick travel meets wanderers) and for the longer runs to come. `models.LEVEL_XP` becomes
`[0, 30, 80, 150, 280, 460, 720, 1100]` (today `[0, 20, 55, 110, 200, 320, 480, 700]`); the monsters' own XP is left
as their makers wrote it.

### The changes

| Change | Why |
|---|---|
| The level table above | Fewer levels means fewer perks, less HP and less to-hit: the biggest lever (alone, a slightly steeper table took the veteran from 71% to 50% wins) |
| Ruthless doubles **the weapon's dice** (and a crit's), not the whole total | It multiplied every flat bonus; the run's 36s become 25s |
| Floor 1 is all tier 1 (its warden tier 2); floor 2 is all tier 2, and its warden is a tier-2 elite | The Rat King, Hobgoblin and Venom Toad killed newcomers on floors 1–2 |
| Depth bonus on floor 3 too: HP ×1.1, damage +1 (floor 4 stays about as now: HP ×1.25, to-hit +1, damage +1) | So floor 3 isn't where the monsters stop growing |
| Rare things from fewer places: a warden leaves something rare a third of the time (something good otherwise), an elite 10% (20% now), Granny Gristle 20% (a third now) | About one rare thing a floor, from the secret room |
| A character cut down to size pays XP for that size | Swoogy on floor 1 pays his full 120 today: two levels at once |

Together, 600 new seeds:

| | plain bot, now → after | veteran bot, now → after |
|---|---|---|
| Wins | 21% → 13% | 72% → 57% |
| Deaths on floors 1 / 2 / 3 / 4 | 21/50/23/31% → 10/24/57/55% | 3/16/5/7% → 1/5/26/18% |
| Reaching floor 3 | 39% → 69% | 82% → 94% |
| Level at the stairs, floors 1 / 2 / 3, and at the end | 3/5/6, 7 → 2/3–4/5, 6 | 3/5/6, 7 → 2/3–4/5, 6 |
| HP lost, floor 3: ordinary / elite / boss | 17/24/45% → 30/43/73% | 6/10/29% → 20/27/56% |
| HP lost, floor 4: ordinary / elite / boss | 19/17/49% → 21/21/74% | 0/8/22% → 12/16/39% |

The deaths now climb with depth, as they should, and a fight on the last floors costs something again. A newcomer gets
much further (seven runs in ten see floor 3, not four) but wins less: the campfire's blessings are what carries them
over, which is what they're for. These are first numbers, tuned in the simulation; the build re-runs it with the new
mechanics below and keeps the bot test (`test_bot_games_finish_without_errors`) in a band for both bots.

**Tried and left out:**
- A slower to-hit (1 + level/2 instead of + level): alone it took the veteran from 71% to 57%. With fewer levels
  it isn't needed; it's for the 6- and 10-floor runs, where levels go higher.
- The depth bonus on bosses, and +2 to their to-hit: the boss fights went to 80–95% of the HP, and floor 4 to 50–65%
  deaths. Bosses get a second act instead (§3.5): longer and stranger, not just bigger.
- Fewer potions: together with the rarer rare things and nothing else, they took the veteran from 71% to 59% wins,
  since a bot drinks what it finds. The run hoarded ten, so potions belong in the loot pass (§5), where they're made
  scarcer *and* more worth finding.

The harness behind these numbers (the veteran bot, and per fight: rounds, HP lost and the player's hit, by floor and
kind of foe) goes into `tools/simulate.py` as part of the build.

## 3. Combat as an event

What a fight has today: a heavy blow told one turn ahead ("A heavy blow is coming!"), dodging (a perfect dodge of a
heavy blow gives advantage and Fate), guarding, a monster's tricks (steal, tangle, venom), poses on its tile (wind-up
glow, lunge, flash, death dither), damage popups, and battle and boss music. What's missing: a fight looks like the
room with a monster in it, every turn offers the same choice, and the kill is a line of text.

### 3.1 The encounter

When a fight begins (you walk in on it, it ambushes you, you provoke it), the stage becomes the fight:

- the room's picture dims and the monster **sweeps in** from the side it's coming from, drawn twice its size, while
  the battle music cuts in with a sting (boss and warden versions);
- a **banner** under it: its name and traits, a danger mark (☠☠○ against your level), and what you know (weak to
  fire — the Bestiary, or Lorekeeper);
- its **HP bar** and its first **intent** (3.2) above it.

```
 ✦ The Feast Hall ───────────────────────────────────────
                     ‼ 8–20  HEAVY
                  ▄▄██████████████▄▄
                  ██  (the toad, ×2) ██
                  ▀▀██████████████▀▀
      HULKING · VENOMOUS  Venom Toad              ☠☠○
      ██████████████████████░░░░  45/45      break ▱▱▱▱
      weak to fire, salt
```

The sweep is the same code the room-to-room transitions will use (§6).

### 3.2 Intents you can read

Every monster's next move is shown above it, with numbers, as *Slay the Spire* does: ⚔ 3–8 (a strike),
‼ 8–20 HEAVY (a heavy blow, its wind-up pose), 🛡 (guarding: +4 defense), ✋ (about to grab something),
🌿 (vines), ☠ (spit). The game already picks a monster's move a turn ahead; this shows it. Then each turn is a real
choice: swing into a strike, dodge the heavy (and counter with advantage), don't swing into a guard (drink, throw
something, set up). Acrobatics stops covering heavy blows, so reading the tell stays your job (no measurable change
in the bot's wins).

### 3.3 Traits that fight differently

The elite traits (Frenzied, Armored, Hulking, Cursed) are numbers today: +2 here, ×1.5 there. They become behaviors,
each with a tint on the sprite and a line on the banner:

| Trait | In the fight |
|---|---|
| Frenzied | attacks twice a turn once it's below half HP |
| Armored | plates soak 3 of every hit until a critical hit or a heavy weapon cracks them ("CRACK!") |
| Hulking | huge HP and crushing heavy blows, but every wind-up takes two turns: time to dodge |
| Cursed | its hits put −1 on your rolls for the fight; it pays double |
| Venomous | (as now) its bite may poison |
| Swift (new) | strikes first when the fight begins, and is harder to dodge |
| Regenerating (new) | heals 2 a turn until it's been burned |
| Gilded (new) | glitters, drops gold and something better, and runs off after three rounds if you don't finish it |
| Explosive (new) | bursts when it dies: dodge the last blow or take it |

Deeper floors have more of them (first guesses, for the simulation to settle: floor 2: 20% of monsters, floor 3: 35%,
floor 4: 50%; today 25/40/25%), and from floor 3 a warden has two. The kids can name new ones in the Maker later;
each is a name, a tint and one rule.

### 3.4 Break

A meter under the monster's HP bar fills when you hit a weakness, land a critical hit or dodge perfectly. Full, it
**breaks**: stunned for its next turn and taking double damage, with a flash, a crack and a "BREAK!" banner. It
gives the weakness system (holy water, fire, the shiny things goblins can't resist) and the perfect dodge a payoff in
every fight, and a fight a rhythm: find the weakness, break it, finish it.

### 3.5 Bosses in two acts

At half HP a boss turns: it roars, the screen flashes, the music lifts, its sprite changes (an enraged tint, or a
clip: §4), and it gets new moves: it calls a minion, swaps its weakness, or gains a signature attack. Each boss gets
one or two moves of its own, in `monsters.toml`, so the Maker can write them for the kids' bosses. Serpentis keeps
its maker's numbers and gains its act: a coil that pins you for a turn, say.

### 3.6 The finish and the spoils

- The **killing blow** holds for a beat, shows its number big, and the sprite shatters into pixels flying away from
  the blow (the dither dissolve stays for ghosts and calmer exits).
- A **spoils card** follows: the XP bar fills on screen (the level-up fanfare if it's earned), the gold pops, and each
  drop bursts out in its rarity's colour with a sound of its own, then lies on the floor to take.
- **Style pays**: Flawless (no damage taken), Exploited (finished with a weakness) and Broken (finished while broken)
  add XP and gold, so playing well is rewarded and not just survived.
- The stage sweeps back to the room, and the floor's music returns.

### 3.7 Pace

A six-round fight makes six paragraphs today. In a fight the narrator would tell the opening and the finish in prose,
with the exchanges between as quick lines (the dice, the animation, one sentence), unless something unusual happens
(a creative action, a trick, a break). Outside fights nothing changes.

## 4. Animation, and the Blender pipeline

Code first: the poses are already made from each sprite's own frames when they're drawn, so every monster (the
Maker's too) gets them free. The fight needs a few more: **enter** (the sweep), **flinch** (knocked back a pixel or two,
white), **shatter**, a **slash or impact** drawn over the monster by your weapon's tag (sharp: a slash; heavy: a burst;
holy: a glow), and **you**, on the stage's edge, lunging and dodging.

The Blender pipeline (`spikes/goblin3d`: the sprite voxelized, animated and rendered back into pixels) can do what
code can't: turning around, real squash and stretch, a swing with weight. But it's work for each creature, and at 24
pixels wide the frames need touching up (in the recording's squash frame the goblin's face is gone). So it's for the
moments worth that work, not for every monster:

- the game looks for **optional clips**, `data/clips/<monster>/<clip>.<size>.png` (entrance and idle now; attack,
  hurt, death and act two later), and plays one when it's there, the code pose when it isn't;
- the pipeline makes clips for **bosses first**: the Goblin King from the goblin model already built, then the
  others' entrances and second acts;
- the Maker can be the touch-up step, as it already is for small sprites.

## 5. Loot by floor (planning)

For the longer runs:

- **Item tier by depth, not floor number**: the best tier a floor gives is `ceil(3 × floor / floors)`, one tier more
  in its secret room. On 4 floors that's 1/2/3/3 (and its stashes and chests give that tier, not "3 or more"); on 6
  it's 1/1/2/2/3/3. A tier 4 for the last floors of a 10-floor run is a later choice (Bloodbath's home).
- **Rarer rare things** (§2), and **fewer, better potions**: one a floor in the scattered loot, a potion from a kill
  half as often, and strong potions only from the special places.
- No second copy of gear you have (the two Silvered Blades: §6).
- Then the old plan's §3.4–3.5: junk with tags (the kids can fill it in the Maker), a "nothing" weight on searches
  and drops, a pack with a size.

## 6. Cleanup from the run

1. **A potion clicked in a fight was thrown.** The first move against the Lantern Moth threw the Healing Potion: at
   full HP a potion's only move in a fight is Throw, and the click went into the story as just "Healing Potion". A
   wasted potion. The button should say Throw, and a healing thing shouldn't be thrown without asking.
2. **"Venomous Venom Toad"** (and "Frenzied Venomous Venom Toad"): Norfel's venom prefix lands on a monster already
   named for venom.
3. **Bare echoes**: some clicks go into the story as just "Use", "Equip", "Unlock" or "Take", without what was used.
4. **Two Silvered Blades**: when a chest's first pick is gear you have, `loot.produce` falls back to a fresh pick that
   no longer leaves out what you have.
5. **Swoogy's 120 XP on floor 1** (§2).

And from the transitions note: rooms should sweep from one to the next in the direction you walked, with the same
sweep as the encounter.

## 7. Order of work

1. **The balance pass** (§2), the cleanup (§6), and the simulator's per-fight report with the veteran bot.
2. **The encounter and the finish**: the stage's fight view and sweep, readable intents, the spoils card and style
   bonuses (§3.1, 3.2, 3.6).
3. **Fights that differ**: traits as behaviors, Break, bosses' second acts (§3.3–3.5); the simulation re-tuned.
4. **Bodies on the stage**: flinch, shatter, weapon effects, the player's sprite, and the optional clips; a Blender
   pilot on the Goblin King (§4).
5. **Travel and drops**: the room-to-room sweep, drop moments outside fights, and loot by depth (§5), ahead of more
   floors.

## 8. Questions for you (answered)

The owner kept the targets and the narration's pace as written. The hero is theirs: they're making a status portrait
that reacts as Doom's does, an animated full-body sprite, and the Goblin King's entrance through the Blender pipeline
(§4), and the game's look takes after *Wizards & Warriors* (NES): strange, vivid and hard. The questions as asked:

- **The targets**: level 2 / 3–4 / 5 / 6 at the stairs, and the veteran bot winning a little over half its runs. Does
  that feel right, or should a veteran win more?
- **Newcomers**: with these numbers a new player sees much more of the game but wins about one run in eight. Fine
  for a roguelite with blessings, or should floor 3 be gentler for them (a blessing that's cheap, say)?
- **Pace**: narration only at a fight's opening and finish (§3.7)?
- **The player on the stage**: is there a hero sprite to use, or should the kids draw one in the Maker?

## 9. What was built (steps 1 and 2)

**The balance pass** (§2), as planned: `LEVEL_XP` slower; Ruthless doubles the weapon's dice; Acrobatics never takes
a heavy blow; monsters' tiers by depth (`world.tier_for(floor, floors)`: 1/2/3/3 on four floors, 1/1/2/2/3/3 on six)
and a warden at least tier 2; the depth bonus from floor 3, and a longer run repeats its deepest row
(`world.depth`); a warden leaves something rare a third of the time and otherwise a small key or a bomb; elites 10%,
Granny Gristle 20%, a potion instead of a strong one once the rare things run out; a character cut to size pays XP
for its size.

**The cleanup** (§6): a picker's option is told as the whole use ("Throw the Healing Potion at the Lantern Moth",
`interactions.said`), the Grid's Use never offers to throw what heals, a pack's buttons and Here's say what they were
used on ("Use · Pure"), a Venom Toad in Norfel is always venomous and never "Venomous Venom Toad", and a chest tries
its other slots before handing you a second of your gear.

**The simulator**: `tools/simulate.py --veteran --fights` (the veteran is `tests/bot.py`'s, made by the campfire's own
`meta.make_player`), and the bot test holds both bots in a band (a newcomer 3–35% of runs, a veteran 35–80%).

**The fight as an event** (§3.1, 3.2, 3.6, 3.7; `ptg/encounter.py`, the stage in `ui/game_screen.py`): the foe sweeps
onto the dimmed stage with a sting (a boss's deeper), stands in a pool of light with its next move over its head and
its damage range (`combat.foresee`: ⚔ 1–10, ‼ 2–20 HEAVY · venom, ⛨ GUARDS, ✶ REELING), its banner under it with its
traits, ☠☠○ (`combat.danger`: what beating it toe to toe would cost you), its health and its known weaknesses; it
flashes when hit and lunges when it swings; slain, it holds a beat, shatters, and a spoils card fills the XP bar and
shows the gold, souls, style and drops in their rarity's colours, each with its sound, before the room sweeps back
(`encounter.wipe`, ready for room-to-room travel). Winning in style pays: Flawless (it went for you and never drew
blood) and Exploited (the killing blow found a weakness), each a fifth more XP and 3 gold a tier, with epithets of
their own. With a narrator, a fight's blow for blow is told in a line; its opening, its end and anything out of the
ordinary (a crit, a perfect dodge, a trick, a weakness found) in prose.

Measured with everything in (600 seeds from 1000):

| | newcomer bot | veteran bot |
|---|---|---|
| Wins | 15% | 59% |
| Deaths on floors 1 / 2 / 3 / 4 | 10 / 23 / 54 / 53% | 1 / 5 / 21 / 21% |
| Level at the stairs, floors 1 / 2 / 3 | 2 / 4 / 5 | 2 / 4 / 5 |
| HP lost, floor 3: ordinary / elite / boss | 31 / 44 / 70% | 20 / 25 / 52% |
| HP lost, floor 4: ordinary / elite / boss | 21 / 23 / 58% | 12 / 16 / 42% |

Style pays a little: the veteran wins 3 points more than without it, and leaves floor 2 at level 4 more often.

**The owner's art** (step 4, begun): clips are in. The Goblin King's entrance from the Blender pipeline
(`spikes/goblin3d`) ships as `data/clips/goblin_king/` (entrance and idle, 40, 48 and 64 pixels, from
`tools/make_clip.py`), and `encounter.Fight` plays it when the boss fight starts: he drops in from above, the boss
sting on the frame he lands, his name is spelled out on a crimson card under him ("THE GOBLIN KING", "boss of the
Goblin Warren"; every boss gets one), and he fights in his 3D idle at the biggest size the stage fits. The swing at
the end of his fall is his `attack` clip, played each time he goes for you in place of the lunge, and the pan held
high before it his `windup`, how he stands while a heavy blow is coming. Any monster with an `entrance` and an `idle`
gets the same; the others sweep in. Still to come: attack, hurt and death clips, a second
act's, and the hero (the body sprite on the stage's edge, facing the foe, and the portrait beside the hearts on the
status bar), which wait on the files and their format.
