# Floor 4 and statuses: a draft

Status: **first draft, to argue about.** Nothing here is built. Marked **❓** where it's a choice for you.

What this covers: a status system in the spirit of Final Fantasy 1 (poison first), what cures and wards it, and the
floor it's made for: a fourth floor with Serpentis as its boss. Numbers are first guesses; the bot (`tools/simulate.py`)
gets to argue with them before anything ships.

---

## 1. In short

- A **status** is something that stays with you (or a monster) between turns and does something on its own: poison
  hurts you a little with every step. Statuses live in data (`statuses.toml`), like monsters and items, so a new one is
  mostly a table row.
- **Poison** hurts 1 HP a step (a room walked into, each room passed on quick travel) and 1 a round in a fight, more if
  it's stronger. **On its own it never kills you**: out of a fight it stops at 1 HP. In a fight it can finish you,
  so a poisoned fight is a dangerous one.
- **Cures**: a shrine (as often as you like, but you have to walk there, poisoned), an **antidote** (sold on every
  poison floor; venomous monsters sometimes drop one), and a few things that cure as a side effect.
  **Wards**: a few things that make poison weaker, or keep it off you, while you carry them.
- After a cure you're **immune for a while, counted in steps**, not minutes (§3.5).
- **Floor 4** is the Coiled Temple: a bit bigger than floor 3, venomous monsters, a shop that always has antidotes,
  and Serpentis at its maker's own numbers, with one rule built around the poison.

---

## 2. The status system

### 2.1 What a status is

A row in `src/ptg/data/statuses.toml`:

```toml
[status.poison]
name = "Poisoned"
icon = "☠"                # on the HUD, beside a monster's name
colour = "#63c74d"
ticks = ["step", "round"] # when it does its thing: a step, a fight's round, a rest
damage = 1                # each tick, times its strength
strongest = 3             # how far more of it can stack it
lethal = "fights"         # "never", "fights" (it can't take you below 1 HP out of one), or "always"
wears_off = 0             # ticks until it goes on its own (0: never)
immune_after = 15         # steps you're immune for, after an antidote (the shrine's are fewer: §3.5)
blurb = "Venom in your blood: it costs you health with every step, and every round of a fight."
```

Anyone can carry one: the player (`Player.statuses`) and a monster (`MonsterState.statuses`), each a status's key and
its strength. Some of what's in the code now is a status already, just not called one: a monster's **stun**, the
**tangle** a vine monster wraps you in, a **cursed** item. They'd move over in time, so there's one way to show,
tick and cure all of them.

Items say what they do with statuses, also in data:

```toml
[item.antidote]
cures = ["poison"]            # used up, it ends these
[item.snakeskin_cloak]
wards = { poison = 1 }        # while you carry it: poison is that much weaker (enough wards: none at all)
[item.bloodbath]
inflicts = { poison = 1 }     # its hits poison what they hit (its maker wrote that it does)
```

### 2.2 When statuses tick

| Tick | When | Notes |
|---|---|---|
| **step** | you walk into a room; each room you pass through on quick travel | the thing that makes backtracking poisoned annoying |
| **round** | each round of a fight, after the monster's turn | |
| **rest** | when you rest | resting poisoned heals less (half) |
| **floor** | going down the stairs | a few statuses end there; poison doesn't |

### 2.3 Showing it

- **HUD**: `☠2` (icon and strength) beside your HP, in the status's colour; it pulses when it ticks.
- **The story**: a chip line when it ticks, like gold's: `☠ -2 HP (poison)`. When you're poisoned: a ⚠ warning line,
  like a boss's, the first time each floor, saying what cures it.
- **Sheet tab**: a "Statuses" block: each one, its strength, what it does, what you carry that cures or wards it.
- **Here pane**: a monster's statuses next to its health (`☠ poisoned`, `✦ stunned`).
- **Narrator**: told as a fact ("You are poisoned"), so it can mention the sweat and the shaking hands.
- **Journal**: poisoned, cured, immune again.

### 2.4 The FF1 roster, in our terms (later)

Poison first. The rest is a menu for later floors, each one a theme's signature:

| Status | Does | Comes from | Cured by | Floor idea |
|---|---|---|---|---|
| **Poison** | HP a step and a round | bites, needles, gas | antidote, shrine | 4 (now) |
| Burning | HP a round for 3 rounds, then gone | fire attacks, oil + flame | water, rolling (a creative act) | a forge floor |
| Blind | your attacks miss more (disadvantage) | ink, sand, flash | eye drops, light | a dark floor |
| Webbed (today's tangle) | can't flee | spiders, vines | cutting free (sharp), fire | spiders |
| Silenced | can't talk monsters down or bargain | a gag, a curse | holy water, shrine | a cult floor |
| Weakened | -2 might | a ghoul's touch | food, rest | undead |
| Stone (slowly) | three steps' warning, then a game over unless cured | a gaze | gold needle (rare) | a late boss |

The engine wouldn't change for any of these: a row, items that cure or ward it, monsters that inflict it.

---

## 3. Poison

### 3.1 How you get it

- **Bites**: monsters tagged `venomous` have a chance on a hit to poison you (a trick, like `steal` and `tangle`
  now). Serpentis always does (§4.4).
- **Needles**: on poison floors, a chest's needle trap poisons as well as hurting.
- **Gas**: a few room features vent it (a cracked urn, a vent in the floor). You're told before you touch one, and a
  wits roll lets you see it coming.
- **Your own mistakes**: eating something you shouldn't (a creative act with a `venomous` thing).

### 3.2 What it does

- **1 HP a step, times its strength; 1 a round in a fight, times its strength.** It stacks up to 3: a second bite
  while poisoned makes it stronger.
- **It never kills you on its own out of a fight**: it stops at 1 HP and tells you so ("The poison leaves you
  barely standing"). In a fight it can finish you. That's the "annoying, not a game ender" line: the poison doesn't
  end your run, but the next fight might, and you'll want to deal with it.
- **It doesn't wear off** (like FF1). ❓ Or it wears off slowly, say a strength every 20 steps, so a player with no
  cure isn't stuck. My lean: it doesn't wear off on floor 4, the shrine is always there to walk to, and the shop always
  has antidotes. That's the floor's whole puzzle.

A worked example, on a 10-room floor: poisoned (strength 1) a third of the way through, with ~20 steps and 2 fights
to go and no cure: about 20 HP from walking and 4-8 from fights. The bot reaches floor 3's boss with 40 max HP
(32-48), so about 45 on floor 4: that's half your health. Annoying, and survivable with potions. At strength 2 with
no cure it would take you to 1 HP: you'd go and cure it. (If that's too harsh, poison ticks every other step.)

### 3.3 Cures

| Cure | How | Cost |
|---|---|---|
| **Shrine** | pray (as now for a curse): cures poison, as often as you like | the walk there (it ticks); quick travel ticks too, room by room |
| **Antidote** (new, tier 1) | drink it: cured, and immune for a while | ~15 gold at a shop; poison floors' shops always have 2-3; venomous monsters drop one 25% of the time |
| **Bitterroot** (new, food) | eat it: cures strength 1 only | found by searching on poison floors |
| **Holy water**, drunk | cures it (and you lose your throw) | a choice: your weapon against undead, or your cure |
| **Superior healing potion** | heals and cures | the best potion becomes a little better |
| **Fountain** | its good roll cures as well as heals | luck |

### 3.4 Wards (things that help while you carry them)

| Ward | What | Where from |
|---|---|---|
| **Snakeskin cloak** (armor, +1) | poison strength -1 (strength 1 does nothing) | floor 4 chests and shops |
| **Bezoar** (rare trinket) | you can't be poisoned | floor 4's secret room, or a warden |
| **Serpentis's shed skin** (trinket) | poison strength -1 | floor 3's secret room: what Serpentis left behind, a warning and a help (§4.5) |

Wards stack: cloak + shed skin together make you immune.

### 3.5 Immunity after a cure

You suggested immunity for x real-world minutes. I'd count it in **steps** instead:

- The game is turn by turn, so real minutes would reward a player who just waits (or walks away from the screen,
  or leaves a served game idle) and punish a quick one. Steps cost the same for everyone and can't be waited out.
- **After an antidote: immune for 15 steps. After the shrine: 8.** The antidote is worth buying, and the shrine is
  still a fine free cure.
- ❓ Your other idea, cured once a floor and then immune for the rest of it: simple and generous. My worry is it
  makes the first poisoning the only one that matters, and floor 4's monsters stop being a threat once you're cured.
  Steps keep each bite worth dodging. We could try both and let the bot tell us.

### 3.6 The bot plays it too

The test bot learns: drink an antidote when poisoned (if it has one), walk to the shrine if it's close, buy antidotes
on poison floors when it can. The habit players hoard antidotes like they hoard potions. The simulator reports, for
poison floors: steps spent poisoned, HP lost to poison, cures used, and deaths where poison was a factor.

Targets: poison costs **10-25%** of your HP over floor 4 on average; deaths with poison involved are **under a
third** of floor 4's deaths.

---

## 4. Floor 4: the Coiled Temple

### 4.1 Where it sits in a run

❓ Two ways:

- **A (my lean, now):** runs are 4 floors. Floors 1-3 stay as they are, and floor 3's boss is still floor 3's
  boss: beating it opens the stairs down instead of ending the run. Floor 4 is always the Coiled Temple for now, and
  Serpentis is the final boss.
- **B (the long plan):** go straight to the plan's themes in pairs (`progression-loot-difficulty.md` §3.1): 6 floors,
  3 themes × 2, with the serpent theme as one pair. More content to make before anyone plays it.

A gets Serpentis and poison played soonest, and fits into B later: the Coiled Temple becomes the deep half of a
serpent theme.

### 4.2 Size

Floors grow by a room or two each, as you suggested: today 7, 7, 8 (plus the secret room). **Floor 4: 10, one of
them a guaranteed shrine** (poison's free cure has to be somewhere). A second shrine 40% of the time, and a shop more
often (50%, from 25%), which always has antidotes.

### 4.3 The temple

- **Rooms**: a snake idol hall, flooded baths, an egg chamber, a moulting pit, a venom press, the coiled stair.
- **Features**: coiled pillars, offering bowls, venom jars (`venomous`: careful), shed skins (search them:
  sometimes bitterroot, sometimes an antidote someone dropped).
- **Hazards**: two or three gas vents a floor, told before you step to them, a wits roll to spot.
- **Light**: dim and green. The narrator gets "the air is thick and sweet" as a fact.

### 4.4 Monsters

Floor 4 needs a tier-4 roster, most of them `venomous`. A brief for the Maker (the kids could draw these):

| Monster | Idea | Poison |
|---|---|---|
| Temple Asp | small, fast, in twos | bite 30% |
| Venom Spitter | keeps its distance: its heavy blow is a spit | spit 50% (dodge it and you're fine) |
| Naga Guard | armoured, slow, guards doors | none: it's the wall the asps hide behind |
| Snake Cultist | intelligent: can be talked down, or bribed | a poisoned blade, 25% |
| Egg Clutch | doesn't fight: hatches asps if you take too long | the asps do |

Plus tier-3 monsters with the depth bonus from the progression plan. Each venomous monster drops an antidote 25% of
the time ("you squeeze an antidote from its venom sac").

### 4.5 Serpentis, the boss

Its maker's numbers: **75 HP, defense 15, +3 to hit, 2d8**, weak to holy and water. Behind a locked door, with its key
somewhere on the floor, like the other bosses.

Its rule (one weakness, one rule, as the bosses section of `game-design.md` has it): **"It smells the venom in
you."**
- Every bite poisons you (strength +1, up to 3).
- **While you're poisoned, it has +2 to hit.** Curing yourself mid-fight (an antidote, holy water drunk) takes that
  away, and buys immunity long enough to finish it.
- Its tell "SSSSSS..." is a heavy blow: a **venom spit**. Dodge it and nothing happens; take it and you're
  poisoned at full strength.

Foreshadowed: the bestiary (once you've seen it), the floor's tips ("bring something for the venom"), shed skins in
its rooms, and the warning line on its door, like the one we added for the big ones.

Its sword, **Bloodbath** (2d7+2), poisons what it hits: its maker wrote that it does. The first player weapon that
inflicts a status, so monsters need statuses too (§2.1).

**The floor-3 lair we just built** stops making sense once Serpentis has its own floor. Instead, floor 3's secret
room sometimes holds **Serpentis's shed skin** (a ward, §3.4): a warning of what's below, and a help against it.

### 4.6 Economy

Gold is easy to come by (searching everything, resting, fights), so antidotes don't need to be rare, just not free:
~15 gold, 2-3 in every poison floor's shop, a 25% drop from venomous monsters. The shop (and Granny Kamultruk's
better one) sells the snakeskin cloak sometimes. The question the floor asks is whether you spent your gold on the
right things before you went down.

---

## 5. Build order

1. **The system**: `statuses.toml`, statuses on the player and on monsters, ticks (step, round, rest, floor), the HUD,
   sheet, story chips and the narrator's facts. Poison only. Tests.
2. **Cures and wards**: antidote, bitterroot, the shrine's cure, holy water drunk, the superior potion, immunity in
   steps; snakeskin cloak, bezoar, shed skin. The bot learns to cure; the simulator reports poison.
3. **Floor 4**: four-floor runs (floor 3's boss opens the stairs), the Coiled Temple theme (rooms, features, vents,
   look), the shop's antidotes, a guaranteed shrine, 10 rooms.
4. **Monsters**: the venomous roster (from the Maker, or drawn here as stand-ins), Serpentis's rule, Bloodbath
   poisoning monsters, the floor-3 shed skin.
5. **Balance**: the bot against the targets in §3.6, and the whole run's curve with a fourth floor.

Each step ships on its own and the game stays playable in between.

---

## 6. Questions for you

1. **Run shape**: four floors now (A), or straight to themes in pairs (B)? (§4.1)
2. **Poison's floor**: never kills you out of a fight, as drafted, or can it (harsher)?
3. **Wearing off**: never, or slowly? (§3.2)
4. **Immunity**: steps (15 after an antidote, 8 after the shrine), or once cured, the rest of the floor? (§3.5)
5. **Serpentis's rule**: "smells the venom" (+2 to hit while you're poisoned), or something else you have in mind?
6. **The roster**: shall the kids draw the floor-4 monsters in the Maker from the brief in §4.4?
7. **Status number two**: which comes after poison, and for which floor? (§2.4)
