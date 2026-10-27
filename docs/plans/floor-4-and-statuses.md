# Floor 4 and statuses

Status: **steps 1 and 2 built (poison, then floor 4: Norfel, its hazards and look, Serpentis as its boss), with your
second round of answers in.** Marked **✅** where it's decided, **❓** where it's still a choice for you. One new floor
and one new status at a time: this is floor 4 and poison.

What this covers: a status system in the spirit of Final Fantasy 1 (poison first), what cures and wards it, and the
floor it's made for: a fourth floor with Serpentis as its boss, a purple poison cavern after Metroid's Norfair. The
numbers are first guesses; the bot (`tools/simulate.py`) gets to argue with them before anything ships.

---

## 1. In short

- ✅ A **status** stays with you (or a monster) between turns and does something on its own. Statuses live in data
  (`statuses.toml`), like monsters and items, so a new one is mostly a table row.
- ✅ **Poison never kills you on its own**, in a fight or out of one: it stops at 1 HP. But while you're poisoned
  **your rolls are 2 worse**, and it costs you **2 HP a step and 2 a turn of a fight**. So you'll want to deal with it.
- ✅ **Cures**: a shrine (free, as often as you like, but you walk there poisoned), and an **antidote** that also
  **protects you from the next poisoning** (not for a time, not for the floor: the danger stays, so stock up).
- ✅ **Floor 4** is a purple poison cavern after Norfair: poison rivers, gas vent traps to disarm, poison puddles
  across some doorways to jump with agility, and Serpentis waiting at the bottom. Metroid and Final Fantasy 1 nods
  throughout.
- ✅ An easter egg after Kid Icarus's eggplant curse: something rare turns you into an eggplant. You can't fight and
  can't quick travel until you walk to a shrine.

---

## 2. The status system

### 2.1 What a status is

A row in `src/ptg/data/statuses.toml`:

```toml
[status.poison]
name = "Poisoned"
icon = "☠"                  # on the HUD, and beside a monster's name
colour = "#b55088"
ticks = ["step", "round"]   # when it does its thing: a step, a fight's turn
damage = 2                  # each tick
lethal = false              # never takes you below 1 HP
penalty = 2                 # off your rolls, while it lasts (or disadvantage = true: two dice, the worse kept)
shrine = true               # a shrine's prayer cures it
blurb = "Venom in your blood: your hands shake (-2 to your rolls), and every step and every turn of a fight costs you health."
```

Anyone can carry one: the player (`Player.statuses`) and a monster (`MonsterState.statuses`). Some of what's in the
code now is a status already, just not called one: a monster's **stun**, the **tangle** a vine monster wraps you in, a
**cursed** item. They'd move over in time, so there's one way to show, tick and cure all of them.

Items say what they do with statuses, also in data:

```toml
[item.pure]
cures = ["poison"]          # used up: ends these
guards = { poison = 1 }     # ...and stops the next one before it takes hold
[item.shed_snakeskin]
wards = ["poison"]          # ✅ built: while it works for you (worn, for gear; carried, for anything else), poison
                            # can't take hold of you at all: statuses.inflict checks what wards it, for any status
[item.bloodbath]
inflicts = { poison = 1 }   # its hits poison what they hit (its maker wrote that it does)
```

### 2.2 When statuses tick

| Tick | When |
|---|---|
| **step** | you walk into a room; each room you pass through on quick travel |
| **round** | each round of a fight, after the monster's turn |
| **rest** | when you rest (resting poisoned heals half) |

### 2.3 Showing it

- **HUD**: `☠` beside your HP, in poison's colour, pulsing when it ticks.
- **The story**: a chip line when it ticks (`☠ -1 HP, poison`). Poisoned, a ⚠ warning line saying what cures it.
- **Dice**: a poisoned roll says so (`disadvantage: poisoned`), like a weakness's advantage does now.
- **Sheet tab**: a "Statuses" block: each one, what it does, what you carry that cures, guards or wards against it.
- **Here pane**: a monster's statuses beside its health.
- **Narrator**: told as a fact ("You are poisoned"), so it can mention the sweat and the shaking hands.
- **Journal**: poisoned, cured, guarded.

### 2.4 Later statuses (one a floor)

| Status | Does | A floor for it |
|---|---|---|
| Burning | HP a round for 3 rounds, then gone | a forge floor |
| Blind | your attacks at a disadvantage | a dark floor |
| Webbed (today's tangle) | can't flee | spiders |
| Silenced | can't talk monsters down or bargain | a cult floor |
| Stone (FF1's) | a few steps' warning, then a game over unless a Soft cures it | a late boss |

---

## 3. Poison

### 3.1 How you get it

- ✅ **Bites** (built): a monster with the `venom` trick poisons you on a quarter of its hits; `deadly_venom`, on every
  hit (a trick, like `steal` and `tangle`: `tricks = ["venom"]` in monsters.toml). Serpentis has `venom` for now:
  `deadly_venom` took its floor-3 lair from 19% of fights lost to 50%, plain `venom` to 32% (20% with a Pure in your
  pack). `deadly_venom` waits for its floor-4 self (§4.6).
- ✅ **Nothing rolls as you walk in** (your playtest: two surprise rolls in one step, puddle then river, was no fun).
  Each Norfel has **one river and one vent**, never next door to each other, and no puddles; you see them as you come
  in, and choose (`hazards.py`).
- ✅ **The poison river** is in a room on the way to the boss: the way on is on its far bank. **Leap** it (agility 12:
  miss, and you're poisoned, but over), **wade** it (poisoned for sure), or **vault** it with a ten-foot pole (no
  roll). Over once, you know its stepping stones: it's a stroll from then on, both ways (quick travel too).
- ✅ **The gas vent** sits under a crust of crystals with something good in it (a strong potion, a rare thing, or a
  Pure, and gold). **Disarm** it first (wits 13; the ten-foot pole's +2; 15 XP; a miss gasses you), or grab what's
  there and take the gas. No resting beside a live vent.
- **Needles**: on floor 4, a chest's needle trap poisons as well as hurting.

### 3.2 What it does

- ✅ **It never kills you**: it stops at 1 HP ("the poison leaves you barely standing").
- ✅ **-2 to your rolls** while you're poisoned (shown as a bonus of its own: "- 2 poisoned"). A disadvantage (two
  d20s, the lower kept) was the first try: too much (§3.6). The code still has it for a later status.
- ✅ **2 HP a step** (rooms walked into, and each room passed on quick travel, told as one line) **and 2 a turn of a
  fight**.
- ✅ **It doesn't wear off**: a cure ends it. Resting while poisoned does half the good.

### 3.3 Cures

| Cure | How | |
|---|---|---|
| ✅ **Shrine** | pray: cures poison, as often as you like | the walk there ticks; quick travel ticks too, room by room |
| ✅ **Pure** (the antidote: FF1's own name for it; built) | drink it: cured, and **guarded against the next poisoning**; drunk ahead of time, just the guard (they don't pile up) | 60 gold on floor 4 (75 at Granny Kamultruk's); floor 4's shop always has two; venomous monsters drop one 25% of the time; one lies about on floor 4 |
| **Bitterroot** (food) | eat it: cured, no guard | found by searching on floor 4 |
| **Holy water**, drunk | cured (and your throw's gone) | a choice: your weapon against undead, or your cure |
| **Superior healing potion** | heals and cures | |

### 3.4 Guards and wards

- ✅ **A guard** is a charge: the next poisoning that would take hold doesn't, and the charge is spent. Pure gives
  one. The danger stays: the second bite still poisons you, so a Pure or two in your pack is worth the gold.
- **A ward** works while you carry it:

| Ward | What | Where from |
|---|---|---|
| ✅ **Shed Snakeskin** (armor, +2; built) | poison can't take hold of you while you wear it: not a bite, the river or the vent | **Granny, on floor 3**: asked what she knows, she brings out "this old smelly snakeskin, HUGE, purple stains all over" (her fingers tingle, she says nothing) for 80 gold, on top of her wares. Floor 3 always has her shop now. The forward-thinking buy: you haven't met poison yet |
| **Bezoar** (rare trinket) | a guard back at every shrine you pray at | chests on floor 4 |

Why +2 and poison-proof, not +1 and half poison: against the floor-3 armor everyone has by then (+3), the bot died on
Norfel 42% of the time in a +1 skin that halved poison, 28% in its +3 armor; a +2 skin that keeps poison off
altogether, 29%. A real trade: a point of defense for no poison.

### 3.5 The eggplant (an easter egg)

After Kid Icarus's Eggplant Wizard: a very rare monster on floor 4 (❓ 1 run in 15?) throws an eggplant at you. You
**become an eggplant**:
- you **can't fight**: no attacks, no stunts that hurt anything, no bombs at a monster
- you **can't quick travel**: you walk
- **a shrine cures it** (Kid Icarus's hospital); Pure doesn't
- the Here pane shows you as an eggplant, and the narrator has fun with it

A status like poison in every other way: one row and a few rules.

### 3.6 Simming it

The bot learns: drink Pure when poisoned (it has one), walk to the shrine if it's close, jump puddles or go round,
disarm vents it's seen, buy Pure on floor 4. The habit players hoard Pure like they hoard potions, and blunder into
vents. The simulator reports, for floor 4: how often you're poisoned, steps spent poisoned, HP lost to poison, rolls
lost to the disadvantage, cures used, and deaths with poison in the mix.

Targets (to argue with): poisoned **2-4 times** on floor 4; poison costs **10-25%** of your HP over the floor; deaths
with poison in the mix are **under a third** of floor 4's deaths.

**First numbers** (phase 1, `tools/simulate.py --venom all`: every roaming monster on floors 1-3 given a venomous
bite, a what-if far past anything we'd ship). The plain bot's wins fell from **44% to 25%**, floor 1's deaths from
18% to 42%; the average player's from 19%. Only **2% of the HP lost** was the poison's own burn: the **disadvantage is
what kills**, and 60% of deaths had poison in them. So floor 4 should have fewer venomous monsters than "most", or
the -2 instead of a disadvantage, or longer walks for the burn to matter. The 10-25% HP target needs the burn to be
bigger, or the target smaller. Floor 4 will tell.

---

## 4. Floor 4: Norfel, Domain of Serpentis ✅ (the name)

### 4.1 Where it sits in a run

✅ One new floor at a time: runs become **four floors**. Floors 1-3 stay as they are, and floor 3's boss is still
floor 3's boss, but beating it opens the stairs down instead of ending the run. Floor 4 is always this cavern for now,
and Serpentis is the final boss.

### 4.2 Size

Floors grow by a room or two each: today 7, 7, 8 (plus the secret room). **Floor 4: 10**, one of them a guaranteed
shrine (poison's free cure has to be somewhere), and a shop half the time (it's 25% on other floors), which always
has Pure.

### 4.3 The look: Norfair

From your screenshots: **purple bubbled rock** (the round-cell walls), **magenta poison rivers and pools** on the
floor, grey stone pillars with lighter caps, round blue and purple doors, and the boss's room after Ridley's lair: a
ring of fangs on the ceiling, round red cells in the floor. The room picture gets a theme of its own (walls, floor,
liquid, light) like the other three, and the title's palette already has every colour in it.

- **Rooms**: a bubbling cavern, a river crossing, a vent field, a pillar hall, an egg chamber, the lair.
- **Features**: bubble clusters, pillars, vents (traps), shed skins (search: bitterroot, sometimes Pure), old
  old bird-headed statues holding an orb (a Metroid nod, by its look, not its name: search it for something good).
- **Light**: dim magenta from the rivers. The narrator gets "the air stings your throat" as a fact.

### 4.4 Nods to Metroid and Final Fantasy 1

✅ Nods by look and by what things do, never by their trademarked names: the Watcher's Orb, not a Chozo one.

| Nod | In the game |
|---|---|
| Norfair | the floor itself: purple rock, poison rivers |
| Varia suit | the Riverwalker Cloak: rivers can't hurt you |
| Energy Tank | a rare find: the Life Canister, +10 max HP |
| Maru Mari | a narrow crack in a wall you can squeeze through rolled up: a shortcut between two rooms |
| Zoomers, Rippers, Squeepts | monsters: a spiky crawler on the walls, a flyer that only goes left and right, a jumper out of the river |
| Ridley's lair | Serpentis's room |
| FF1's Pure | the antidote |
| FF1's Garland | a line for a ghost on the floor: "I, the ghost, will knock you all down!" |
| FF1's Temple of Fiends | the floor's tips speak of "the fiend below" |

### 4.5 Monsters

Floor 4 needs a tier-4 roster, most of them `venomous`. A brief for the Maker (❓ the kids could draw these):

| Monster | Idea | Poison |
|---|---|---|
| Spikecrawler (a Zoomer) | crawls the walls, drops on you | bite 25% |
| Riverjumper (a Squeept) | leaps out of the poison river at you | 30%, and wet |
| Skimmer (a Ripper) | armoured, flies straight; only hurt from behind (a creative act) | none |
| Venom Spitter | keeps its distance; its heavy blow is a spit | 50% (dodge it and you're fine) |
| Eggplant Wizard | rare, harmless to fight, throws eggplants | the eggplant (§3.5) |

Plus tier-3 monsters with the depth bonus from the progression plan. Venomous ones drop Pure 25% of the time.

### 4.6 Serpentis, the boss

Its maker's numbers: **75 HP, defense 15, +3 to hit, 2d8**, weak to holy and water. Behind a locked door, its key
somewhere on the floor, like the other bosses.

Its rule (one weakness, one rule, as in `game-design.md`'s bosses): ❓ **"It smells the venom in you."**
- Every bite poisons you (guards can stop it).
- **While you're poisoned it has +2 to hit**: curing yourself mid-fight takes that away.
- Its tell "SSSSSS..." is a heavy blow: a venom spit. Dodge it and nothing happens.

Its sword, **Bloodbath** (2d7+2), poisons what it hits: monsters can be poisoned too (they tick each round, and at a
disadvantage to hit you).

**The floor-3 lair** is gone: Serpentis has a floor of its own. Its shed skin is Granny's to sell on floor 3 (§3.4).

### 4.7 Economy

Gold is easy to come by (searching everything, resting, fights), so Pure doesn't need to be rare, just not free:
✅ **60 gold**, two in every floor-4 shop (Granny has a shop there half the time, not a quarter), a 25% drop from
venomous monsters. ✅ Her potions come in twos on every floor now. The floor's question: did you buy the right
things before you went down?

---

## 5. Build order

1. ✅ **The system and poison** (built): `statuses.toml` and `statuses.py`, statuses on the player, the step's burn,
   the disadvantage (the dice say why), never lethal, purple hearts and ☠ Poisoned by your health, the Sheet's rows,
   the story's burn lines and the narrator's facts. Pure (its own pale-blue bottle) and its guards, the shrine's
   cure. The `venom` trick (Serpentis has it). The bot cures itself; the simulator reports poison (and `--venom` to
   try it on anything). A test room: `ptg --test-room poison`. Statuses on monsters wait for Bloodbath (step 3).
2. ✅ **Floor 4** (built): four-floor runs (floor 3's boss, beaten, opens the stairs in its own room), Norfel
   (`themes.toml`: always the fourth floor, `status = "poison"`), seven room kinds in `rooms.toml` (a bubbling cavern,
   a poison ford, a vent field, a pillar hall, an egg chamber, a bird-headed statue's alcove, Serpentis's lair), its
   look (`room_picture.py`: purple bubbled rock, glowing pink pools, grey pillars), 10 rooms, always a shrine, a shop
   half the time with two Pure, the Watcher's Orb for its key (an old bird-headed statue's: Nintendo's own names
   stay out of the game), holy water for its trinket. One river on the way and one trapped vent (§3.1), and Granny's
   snakeskin a floor above (§3.4). The floor-3 lair is gone. Test rooms: `ptg --test-room serpentis` (its lair).
3. **Monsters and the boss** (started): ✅ Norfel's monsters for now are the dungeons' tier 3, deeper (x1.3 HP, +1
   to hit and damage; the plan's x1.6 and +1 defense killed the bot three times in ten there), half of them
   venomous ("Venomous Troll"), elites a quarter of the time. ✅ Serpentis at its maker's numbers: its bite poisons a
   quarter of the time, and its heavy blow ("SSSSSS...") is a **spit of venom** that always does: dodge it. Still to
   come: the kids' roster, Bloodbath (it says Serpentis drops it, but beating Serpentis ends the run: Norfel's secret
   room?) and its poisoning monsters, the floor-3 shed skin, more nods.
4. **The eggplant.**
5. **Balance**: the bot against §3.6's targets, and the whole run's curve with a fourth floor.

Each step ships on its own, and the game stays playable in between.

---

## 6. Still open

1. Serpentis: at its maker's numbers it wins 41% of fights against a floor-4 kit (bite and spit; 26% with no
   venom at all). Keep it the hardest thing in the game, or trim its HP or its 2d8? (§4.6)
2. The roster: drawn by the kids in the Maker? (§4.5) Until then, the deeper dungeons' own.
3. How rare is the eggplant? (§3.5)

## 7. The numbers now (300 seeds, `tools/simulate.py`)

| | won | F1 | F2 | F3 | F4 |
|---|---|---|---|---|---|
| plain bot, 3 floors, bosses at 34 HP (before) | 44% | 18% | 41% | 9% | |
| plain bot, 3 floors, bosses at 68 HP | 40% | 18% | 41% | 17% | |
| plain bot, 4 floors | 23% | 18% | 41% | 19% | 42% (Serpentis 25) |
| average habits, 4 floors (200 seeds) | 5% | 27% | 66% | 51% | 58% |
| plain bot, one river and one vent, no surprise rolls (200 seeds) | 30% | 16% | 41% | 16% | 27% |
| careful / average / sloppy habits, the same | 24% / 7% / 2% | | | | 36% / 42% / 67% |

Floor 4 alone (bots dropped in with a floor-4 kit): 45% died with the old hazards (4.4 poisonings a visit, 3.6 of them
walking into rooms; 30% of the HP lost to poison's burn), 28% now (1.8, from the river, the vent and bites; 13%).

Poison, plain bot: poisoned a median **3 times** on floor 4 (target 2-4), **11% of the HP lost** to its burn (target
10-25%), cured by Pure about one time in three and by a shrine the rest. Deaths with poison in you: most of floor 4's,
well over the third we aimed for, since nearly everything there poisons you.
