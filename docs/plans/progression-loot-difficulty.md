# Progression, loot and difficulty: the next phase

The plan for growing the game from 3 floors to 6, and later 10, without the run going soft halfway down. Written after
run 59 (a 167-turn win, reviewed turn by turn) and a look at how other roguelikes handle the same problems.

## 1. Where we are

**Run 59, in numbers.** Level 7 by floor 3; the boss died in three rounds.

| | |
|---|---|
| Damage taken from monsters, whole run | 30 HP (plus a 4-point chest trap); lowest point 24/42, turn 12 |
| Healing potions found / drunk | 8 / 0 |
| Gold found / spent | ~350 / 10 (one bribe); no shop visited |
| Small keys at the end | 5, unused |
| Room entries that were revisits | 40 of 62 |

**The bot agrees, and says more.** `tests/bot.py` (an action-only player: explores, fights, dodges heavy blows,
drinks under 35% HP, rests, descends) over 300 seeds of today's game:

| | |
|---|---|
| Win rate | 43% (the test in `test_rules.py` keeps it between 20% and 75%) |
| Deaths by floor | **floor 1: 56 · floor 2: 106 · floor 3: 10** |
| Level at the end | median 4, best 7 |
| Turns | median 84 |
| Potions drunk a run | 4.8 |
| HP when taking the stairs | median 72% |
| Most deaths | Rat King and Hobgoblin on floor 1, Orc and King Mouse on floor 2 |

**The curve is upside down.** Runs die on floors 1–2, before the perks and the gear arrive; a bot that gets past
floor 2 almost always wins, boss included. A person who improvises (run 59) gets past floor 2 easily, and then
nothing can stop them. Both say the same: the early floors spike, the late game flattens.

**Why it's easy late (from the code, not the run):**

- **Attack outgrows defense.** A hit adds the player's whole level (`+7` at level 7) to might and items. Monster
  defense is fixed by tier (8–16), and tiers stop at 3 (`world.tier_for` caps at 3, so floor 3 onward is all tier 3).
- **Damage multiplies.** Ruthless doubles the whole total, after Glass Cannon +3, Brute +1, Sharp Start +1 and a
  weakness +2: 24–32 a hit, against monsters of 14–45 HP.
- **Defence perks remove what's left.** Acrobatics dodges the first damaging hit *in every room*, and most fights are
  2–3 rounds. A cursed item (Swoogy's Diaper) helped more than it hurt (−2 every hit, −2 max HP a staircase).
- **Healing is free.** Rest can be used in every room (one ambush in seven rests); Vampiric adds more; potions keep
  dropping.
- **Gold, keys and bombs pile up.** Shops are behind locked doors and don't always appear; gold has few other uses
  (a shrine, a bribe). Pickups are told in a line of text and easy to miss.
- **The run is short and flat.** 3 floors, 3 tiers, levels to 8 (`LEVEL_XP` ends at 700), 15 perks, unlimited
  carrying.

## 2. What other games do

**Difficulty that scales with depth**

- *Slay the Spire* is built in acts of floors, each act with its own enemy pool, elites and a boss. Enemies in later
  acts have far more HP and hit harder, and the game's difficulty dial (Ascension 1–20) stacks small, named
  handicaps for players who want more.
- *Risk of Rain 2* raises difficulty with time and stages, and **chest prices rise with it**, so money never stops
  mattering.
- *Dungeon Crawl Stone Soup* chooses monsters by depth, sometimes from deeper down ("out of depth") for spikes, and
  generates better items deeper.
- *Hades* lets the player raise difficulty in exchange for better rewards (the Pact of Punishment's Heat).

**Player power that grows, but slowly at the core**

- *D&D 5e* is the model for a hit bonus: a proficiency bonus of +2 at level 1 that reaches only +6 by level 20.
  Power comes from choices and gear, not a raw number climbing every level.
- *Brogue* has no experience levels at all: you grow by what you find and what you invest it in (enchant scrolls).
- *Slay the Spire* and *Hades* offer a choice of three rewards, with rarity, and a "pity" rule that makes a rare more
  likely each time one doesn't appear.

**Loot tables that know what floor they're on**

- *Diablo II*: every drop has an item level (the monster's level), which gates which affixes and items can appear;
  treasure classes carry an explicit "no drop" weight, so not everything drops something.
- Roguelikes generally fill their tables with **common, cheap things** so the good things feel good: *Isaac*'s
  pennies and hearts, *Brogue*'s plain darts and food, *Shiren*'s grass and staves.

**Carrying less, and choosing**

- *Brogue* has a fixed number of inventory letters; *Shiren the Wanderer* has a limited bag and *pots* that hold
  several items in one slot (and can be found or bought), so capacity is itself loot.
- *Darkest Dungeon* limits stacks per slot, so supplies compete with treasure for space.

**The coins / bombs / keys triad (*The Binding of Isaac*), which PTG already has**

- Each has an on-screen counter, a distinct pickup sound and sparkle, and **several uses**: keys open treasure rooms,
  shops and golden chests; bombs open secret rooms and break rocks; coins buy from shops, beggars, slot and fortune
  machines and a donation machine (which unlocks things across runs).
- *Rogue Legacy* takes what you didn't spend when you go back down: spend it or lose it.

## 3. The design for PTG

### 3.1 Floors in pairs: a theme is two floors

Each theme becomes an **upper** and a **deep** floor. The deep floor has the theme's boss behind its key; the upper
floor has a **warden** (a named elite, already in the code) by the stairs.

| Run length | Themes | Bosses |
|---|---|---|
| 3 floors (now) | 3, one floor each | final boss only |
| 6 floors | 3 themes × 2 floors | a boss every second floor; the last is the final |
| 10 floors | 5 themes × 2 floors | the same (two new themes: good projects for the Maker) |

Floor count stays a setting (`models.FLOORS`), so the run can grow without changing the design.

### 3.2 Monsters scale with the floor, not only the tier

Keep tiers 1–4 for *what* a monster is (the maker's number), and add a per-floor **depth bonus** for *how strong*
it is on this floor. With depth `d = floor − 1`:

| | formula | floor 1 | floor 3 | floor 6 | floor 10 |
|---|---|---|---|---|---|
| HP | × (1 + 0.2·d) | ×1.0 | ×1.4 | ×2.0 | ×2.8 |
| to-hit | + ⌊d/2⌋ | +0 | +1 | +2 | +4 |
| defense | + ⌊d/3⌋ | +0 | +0 | +1 | +3 |
| damage | + ⌊d/2⌋ | +0 | +1 | +2 | +4 |
| elite chance | 10% + 4%·d | 10% | 18% | 30% | 46% |
| out-of-depth | 5% a room draws one tier higher | | | | |

`world.tier_for` keeps choosing which tier (by distance into the floor), but its cap of 3 moves to 4 on the deep
floors. And **the start gets gentler**: today floor 1's far rooms are already tier 2 (the Rat King, the Hobgoblin and
the Dire Wolf are the bot's top killers there). Floor 1 should stay tier 1 bar its warden, so the first floor
teaches and the climb comes after. Bosses get the same depth bonus plus their own. All of this is data (a table in `world.py`), so it's tuned by
numbers, not code.

### 3.3 The player grows more by choices, less by raw numbers

- **To-hit:** might + a *proficiency* that grows slowly: +2 at level 1, +3 at 4, +4 at 7, +5 at 10 (`2 + ⌊(level−1)/3⌋`),
  replacing `+ level`. At level 7 that's +4 instead of +7.
- **Levels:** extend `LEVEL_XP` to about 12 for a 10-floor run, with each level costing more (roughly ×1.45). On 3
  floors you'd still reach 6–7.
- **Perks** keep their fun but lose their stacking:
  - Ruthless doubles **the weapon's dice**, not the whole total.
  - Acrobatics: the first hit **in each fight**, not each room. (The same for most rooms, but not when you rest.)
  - Glass Cannon: keep it, it already has a price.
  - Ranked perks (I, II, III) give later levels something to choose that isn't a new multiplier.
- **Healing** stops being free: one **safe rest** per floor (at a campfire-like spot, or the first rest); after
  that, an ambush risk that grows with depth (25% on floor 1, up to 50% on floor 10). Potions matter again.
- **Curses** cost: a cursed item's drawback scales with depth, and any upside it has is smaller than the cost.

### 3.4 Gear slots and a pack with a size

| Slot | Holds | Today |
|---|---|---|
| Hand | one weapon | the same |
| Body | armor | the same |
| **Head** | a hat or helm | the Hard Hat competed with the Chain Shirt for the body |
| **Trinkets ×2** | rings, charms, dice… only *worn* trinkets work | every carried trinket works |
| **Pack ×6** | everything else; potions and food stack 3 to a slot | unlimited |

Gold, bombs and small keys are **counters**, not pack items (as now).

The pack grows, and growing it is a reward:
- **with souls**, at the campfire (Bigger Pack I/II/III);
- **with a found bag** (a satchel, a bandolier for potions), the way *Shiren*'s pots expand his bag;
- **from quests** (Lenny's reward could be a pouch).

A full pack asks what to leave behind when you pick something up (the Take flow already asks about cursed things).
Trinkets that work only when worn turn twenty-odd always-on bonuses into a choice of two.

### 3.5 Loot tables with rarity, junk and a "nothing"

- **Item level = floor.** A slot asks for a rarity and a level, instead of a fixed tier per floor:

  | rarity | floor 1 | floor 3 | floor 6 | floor 10 |
  |---|---|---|---|---|
  | junk | 30% | 25% | 20% | 15% |
  | common | 45% | 40% | 30% | 25% |
  | uncommon | 20% | 25% | 30% | 30% |
  | rare | 5% | 9% | 15% | 20% |
  | legendary | 0% | 1% | 5% | 10% |

- **Junk**: cheap things with tags, which in this game aren't useless. They're **props for creative actions** (the
  narrator and interpreter already work with tags), sell for a little gold, and give quests something to want.
  Examples: cracked mirror (shiny), ball of twine, candle stub (fire, small), rusty nails, sack of flour (cloud),
  bent spoon, goblin tooth, old boot, chalk, fishing hook, cowbell (loud), single glass marble (slippery). They're
  easy to make in the Maker, and the kids can fill this tier fast.
- **A "nothing" weight** for searches and drops (*Diablo*'s NoDrop): today every feature hides something or nothing
  fixed at generation, and every chest is full. With fewer, better things, finding one means something.
- **Fewer potions**: potions move from "every floor's list ×3" to about one a floor plus shops, with junk taking
  their place.
- **No repeats of what you wear**: a gear slot never rolls the armor or weapon already equipped (run 59 found a
  second Chain Shirt).
- **Pity for the essentials**: a floor always places at least one small key per locked thing and one bomb per cracked
  wall (already true: `loot.ESSENTIAL`).

### 3.6 Gold that's always worth having

Shops can't be the only use. Every floor should offer **at least one place to spend**, with prices that rise with
depth (the *Risk of Rain* rule), so gold stays relevant on floor 10:

| Spend on | Cost (× floor) | What it gives |
|---|---|---|
| A **peddler** (a wandering NPC, a chance a floor) | the shop's prices | a small counter of three things |
| A **gilded chest** (needs gold, not a key) | 15 | a rare roll |
| The **shrine** (exists) | 10 | full heal; deeper, a blessing |
| A **forge / anvil** fixture | 20 | your weapon or armor +1 (once each per item) |
| A **wishing well** (a fountain variant) | 5 a coin | a chance at Fate, a junk item, or nothing |
| A **beggar / donation** (a calm NPC) | any | a blessing at thresholds; tips about the floor |
| **Bribes** (exist: Swoogy, talking down) | scales with tier | skip a fight |
| **Healer** (a calm NPC, sometimes) | 8 | heal to full |

And what's left at the end of a run turns into **souls** (say 10 gold : 1 soul, or more with an unlock), so a
miser's run still pays back at the campfire. (The *Rogue Legacy* variant, "spend it or lose it at the stairs", is
crueler and an option for a harder mode.)

Keys get more uses too: **vault rooms** (a locked side room with a chest and a junk-guarding monster), shop doors,
chests. Bombs keep their uses (walls, chests, fights). Counters get a cap (bombs 9, keys 9) so hoarding has a ceiling.

### 3.7 Pickups announce themselves

Gold, bombs and keys are only words today. The *Isaac* treatment, in this game's terms:
- a **chip that rises from the room's picture to the status bar**: `+6 ¤`, `+1 ●`, `+1 ⚷` in the counter's colour,
  the counter itself flashing (the HUD already flashes for HP);
- **a sound each**: the coin sound exists; a fuse fizz for a bomb, a jingle for a key;
- a line in the story that's a **chip, not prose** (as items already are: `+ Healing Potion → pack`):
  `+6 ¤ gold (21)`, `+1 ● bomb (3)`;
- the docked **Lately** journal shows them with their glyphs.

### 3.8 Difficulty you can choose

Once the curve is right at the default, a *Heat*-like dial at the campfire: named, stackable handicaps (monsters +1
to-hit; one rest a floor; no shrine heals; gold left at the stairs is lost…) each worth a percentage more souls. Daily
runs could pick a fixed set.

## 4. How we'll know: the bot, grown into a report

The repo already has the start of this: `tests/bot.py` and the win-rate guard in `tests/test_rules.py`
(`test_bot_games_finish_without_errors`). The next step builds on them rather than starting over:

- **`tools/simulate.py`** (or `ptg simulate`): plays N seeds with the bot through `rules.perform` (no model) and
  prints a report like the table in section 1, **per floor**: deaths, HP at each staircase, damage taken per fight,
  rounds to kill by tier, potions drunk, gold earned and spent, level reached, causes of death.
- **A smarter bot as well as the plain one**: today's picks the first perk and never improvises, so it plays weaker
  than a person; a second policy that picks perks sensibly, uses keys on shops and buys potions brackets the real
  player from above. The target win rate is for the plain bot; the smart one shows the ceiling.
- **The guard grows with it**: a test per floor count (3, 6, 10) that keeps the plain bot's win rate in a band, and a
  test that deaths are spread over the floors (no floor taking more than about half of them), so the curve can't
  quietly flip upside down again.

**Targets** for the default difficulty (first guesses, to argue about):

| | target |
|---|---|
| A normal fight | 2–4 rounds; costs 10–25% of your HP |
| An elite | 4–6 rounds; 25–45% |
| A boss | 8–12 rounds; you'd want a potion or two |
| Win rate, the plain bot | 35–55% at any floor count (it's 43% on 3 floors now) |
| Where the plain bot dies | spread over the floors: no floor more than about half the deaths (now floor 2 has 62%) |
| HP when arriving on a new floor | 50–80% of max |
| Potions drunk a run | about one a floor |

The bot won't play like a person (no creative actions), but it shows the curve, and every change to a number
afterwards gets its before-and-after.

## 5. Phases

1. **Measure.** `tools/simulate.py` on top of `tests/bot.py`, the per-floor report, a smarter second bot, and the
   baseline written down (section 1 has its first numbers).
2. **The curve.** Proficiency instead of `+level`, perk fixes (Ruthless, Acrobatics), depth bonuses for monsters,
   tier 4 deep down, the rest rule. Re-run the report until the targets hold on 3 floors.
3. **Feedback.** Pickups that announce themselves (3.7): small, and it makes everything after this visible.
4. **Slots and the pack.** Head and trinket slots; a pack of six with stacks; growing it with souls, bags and quests.
5. **Loot.** Rarity and item level, the junk tier (with the kids making junk in the Maker), the "nothing" weight,
   fewer potions, no repeats of worn gear.
6. **Gold.** The gold sinks (peddler, gilded chest, forge, wishing well, beggar), gold to souls at the end, caps on
   bombs and keys, vault rooms.
7. **Six floors.** Themes as upper/deep pairs, wardens and bosses, the simulation tuned for 6.
8. **Ten floors.** Two new themes, tuning for 10, the difficulty dial.

## 6. Questions for you

- **Run length per sitting:** is a 6-floor run meant to be one sitting (an hour?) or saved and continued? That sets
  how many rooms a floor should have.
- **How hard by default:** what win rate feels right for someone who knows the game: one in three, one in two?
- **Pack size:** six slots to start, or tighter (four) with more ways to grow it?
- **Gold at the end:** turned into souls, lost, or a choice (the dial)?
- **Junk:** should the kids design the junk tier in the Maker (fast, fun, theirs), with a few placeholder pieces from
  us so the tables work meanwhile?
- **Levels:** keep experience levels (with slower to-hit), or move closer to *Brogue* (growth only from finds)?
