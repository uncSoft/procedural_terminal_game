# Procedural Terminal Game: the design (a living draft)

We write this together, section by section, before building. Each system says how other games do it, what makes
that work, what to avoid, and a proposal for us, with the questions only you can answer. Numbers live in
`progression-loot-difficulty.md`; this document is about *what the game is*.

Status: **first draft**. Nothing here is decided until we've gone through it.

---

## 0. The pitch, in one paragraph

A roguelike you play by **talking**: each run is a descent of 30–40 minutes through dungeons the kids helped build,
narrated by a game master who loves the players. It starts light and silly (a leprechaun's cousin who lost his
tooth, a goblin who cooks with his own helmet) and gets **darker and more desperate** the deeper you go, in what you
meet, how the screen looks and how the narrator speaks. You win with **chance, skill and creativity**: the dice
decide a lot, but players who learn how the dungeon works (what's weak to what, what combines with what, which risks
pay) win far more often, and anything you can describe, you can try.

---

## 1. Pillars

Every system should serve at least one of these; anything that serves none is cut.

1. **Chance, skill and creativity, in every run.** Dice for drama; decisions that matter; improvising with what you
   have.
2. **Knowledge is power.** The rules are knowable, visible and combinable. Learning them gives a real edge, and once
   in a while lets you *break* a run, the way Isaac players do. Broken runs are earned, rare and the best memories.
3. **There's always a way.** If you lack what you need, there are chances to get it, or to work around it. Bad luck
   costs you, but it shouldn't leave you helpless.
4. **Light on top, dark underneath.** The tone darkens with depth, and the endgame is desperate.
5. **Made by the kids.** Their monsters, items and junk flow into every system through the Maker.

---

## 2. The run

**Proposal.**
- A run is **6 floors** (3 themes × an upper and a deep floor), **30–40 minutes**. A floor is about 5–7 minutes:
  8–10 rooms and 25–35 turns, fewer than today's (run 59 spent 40 of 62 room entries walking back).
- **A boss on every deep floor**; the last one ends the run.
- **The endgame** (unlocked, see section 9) adds floors below the sixth: *the Below*.

**Questions**
- Does 30–40 minutes include the narrator's waiting time? With a local model, a turn is often 4–10 seconds; 200 turns
  is 15–30 minutes of waiting alone. (This may argue for fewer, meatier turns.)
- One sitting, always? Or can a run be saved and continued (it can today)?

---

## 3. The dungeon's language: tags

This is the heart of the depth, and we already have the start of it: items, props and monsters carry **tags**
(fire, holy, shiny, slippery, loud, heavy, food…), monsters are weak to some, and creative actions use them.

**What other games do**
- *Divinity: Original Sin 2* and *Breath of the Wild* build "chemistry": water conducts lightning, fire spreads on
  grass, **metal attracts lightning**. A few clear rules that combine give a huge space of tricks.
- *NetHack* is famous for "the DevTeam thinks of everything": strange combinations of items have consequences
  someone wrote on purpose, and finding them is the joy.
- *Noita* and *Spelunky* are systems colliding: the world reacts consistently, so players can plan with it.

**What makes it work:** few rules, consistently applied, visible to the player, combinable.
**What to avoid:** rules that exist only in prose; exceptions everywhere; effects you can't see coming.

**Proposal**
- **A fixed vocabulary of about 15 tags**, each with a rule written down, for example:
  - *fire* burns plants and cloth, lights things, scares beasts;
  - *wet* puts out fire and conducts *shock*;
  - *metal* conducts *shock* and is eaten by *rust*;
  - *holy* hurts undead; *shiny* distracts the greedy;
  - *loud* wakes and scares; *slippery* trips;
  - *heavy* breaks things; *sharp* cuts rope and webs.
- **Monsters get weak, resist and immune**, not only weak. A thing that's immune to sharp makes you think.
- **Tags combine on purpose**: an oil flask makes something *flammable*; fire on a flammable thing *burns*. Wet
  plus shock *conducts*. These are the dungeon's "chemistry", and the bestiary and the item cards say them out loud.
- **The narrator and the interpreter use the same vocabulary**, so a creative action ("I pour the oil on the vines
  and light it") is judged by the same rules a player can learn.

**Novel for us:** in most games chemistry is physics. Here it's **language**: the player describes, and the rules
decide. That's what lets a terminal game have a chemistry engine.

**Questions**
- Are these the right fifteen? What did the kids already use most in the Maker's tags?
- How strict: does an action with no tag that applies just fail, or get a small "it was clever" bonus?

---

## 4. Skill in a dice game

The worry: the game is random all the way through. But dice games can have plenty of skill, *if* the player decides
things with the odds visible.

**What other games do**
- *Slay the Spire* shows each enemy's **intent** (attack for 12, defend, buff…). Every turn becomes a puzzle: block
  now, or kill it first? We have the start of this: telegraphed heavy blows.
- *Into the Breach* shows **everything** the enemy will do; all the skill is in the answer.
- *Darkest Dungeon* and *Spelunky* reward **push-your-luck**: one more room, one more search, one more turn in the
  dark, for better loot or a worse ending.
- Every good deckbuilder shows the **numbers**: the odds are the player's to weigh.

**Where skill can live for us**
1. **Reading intents.** Monsters announce more than heavy blows: *guard* (attacking now is wasted), *steal*,
   *summon*, *charge* (next turn's double), *flee* (it gets away with your gold). Each has an answer: dodge, wait,
   strike, block the door, throw something.
2. **Preparation.** Bosses have rules (section 6), and the map, the bestiary and tips from characters warn you.
   Showing up with the right tags is the skill.
3. **Resources over time.** Fate, potions, bombs, keys, light (section 8), the safe rest: when to spend them.
4. **Routing.** The map shows what's behind doors you've seen (a chest, a shrine, a fountain); choosing a path is a
   decision.
5. **Push your luck.** Extra searches, cursed chests, optional elites, resting in a dangerous place.
6. **Creativity.** The best answer is often one nobody listed.

**What to avoid:** hidden math; skill that's only "pick the bigger number"; decisions with one obvious answer.

**Proposal:** show the odds everywhere a player chooses ("needs 9+ · 60%"), give monsters three to five intents
each from a shared set, and make every resource have at least two good uses that compete.

---

## 5. Synergies and ways to break a run

This is the Isaac feeling you described: if you know the mechanics, you can make the dungeon work for you.

**What other games do**
- *The Binding of Isaac*: hundreds of items that interact. Known loops: the **Blood Donation Machine** turns health
  into coins; a **restock machine** refills the shop so you can look for the item you need; certain items make
  others absurd. Even then the win rate isn't 100%. **Transformations**: collect three items of a family and you
  become something stronger.
- *Hades*: **Duo boons** exist only when you have boons from two gods: knowing the pairs means steering toward them.
- *Enter the Gungeon*: specific item pairs have a **named synergy**, and the game shows a sign when you have one,
  so discovering it feels like a reward.
- *Balatro*: jokers whose rules multiply each other; reading how to order and combine them is the game.
- *Risk of Rain 2*: items stack and chain (on-hit effects proc other on-hit effects).

**What makes it work:** each piece is simple and visible; the power is in the combination; strong combos are rare
enough to feel special; the game still has answers to you (bosses, scaling).
**What to avoid:** combos that every run finds; infinite loops with no cost or ceiling; "math soup" (twenty small
always-on bonuses no one can follow, which is where we are with every carried trinket counting).

**Proposal**
- **Converters on purpose**: a few things that turn one resource into another, each with a cost or a ceiling:
  - the shrine already takes blood for Fate;
  - a blood fountain: HP for gold;
  - a beggar: gold for blessings;
  - a wishing well: gold for a chance at Fate;
  - a forge: gold for a weapon +1, once per item.
  
  Knowing which converter feeds which is a strategy.
- **Families and transformations**: three things of a family (shiny things, food, holy things, kid-made characters'
  belongings…) make you something: *Magpie* (shiny: the greedy follow you, distractions always work), *Glutton*
  (food: eating heals double and gives Fate), *Pilgrim* (holy: undead fear you). Visible on the Sheet as progress
  ("Magpie 2/3").
- **Named pairs**: specific items made for each other, with a sign when you have both (Lenny's good tooth and the
  pliers…). The kids can write these in the Maker: "goes with".
- **A shop restock** (gold, rising each time) and **choice of three** at the big rewards (a boss, the secret room),
  so building toward something is possible.

**Questions**
- How breakable do you want it? Isaac-level (some runs are silly), or only a little?
- Should transformations change how your character looks in the portrait or the HUD? (Isaac's do, and it's part of
  the fun.)

---

## 6. Bosses with rules

**What other games do**
- *Slay the Spire*'s bosses each change the rules: the Time Eater ends your turn after twelve cards; the Awakened
  One gets stronger every time you use a power. You learn each one and build for it.
- *Breath of the Wild*: metal draws lightning in a storm. A rule about **what you're wearing** is memorable because
  you planned your gear for it.
- Classic games give bosses a **weak point** that needs the right tool (Zelda).

**Proposal: every boss has one weakness and one rule, both foreshadowed.**

| Boss | Hurt only (or mostly) by | Its rule | How you're warned |
|---|---|---|---|
| The Drowned Abbot | fire and holy | it fills the room with water: *wet* things are *shocked* when it rings its bell | the floor's tips; the bestiary; drowned candles in its rooms |
| A storm boss (new) | anything but shock | **every metal thing you wear draws its lightning**: +1 damage per piece | a warning on its door: "your blade hums" |
| A rust boss (new) | blunt, not sharp | its touch **rusts metal**: your weapon loses a die size each hit you take | rusted bones in its rooms |
| The Thornmother | fire, sharp | it regrows unless burned | vines that grow back after you cut them on the way |

A boss you aren't ready for should still be beatable (creativity, Fate, a desperate improvisation), just much harder.

**Questions**
- Do bosses stay one per theme, or can a theme have two or three bosses that rotate?
- Should the kids design bosses in the Maker (with weaknesses and a rule picked from a list)?

---

## 7. When you don't have what you need

**What other games do**
- *Slay the Spire*'s **rarity offset**: every time a rare doesn't appear, the next one is more likely (pity).
- *Hades* shows what's behind each door, so you can **steer** toward what you need.
- *Isaac*: the shop restock, the **D6** (reroll an item), crafting (the Bag of Crafting), devil deals (pay health for
  the item you want).
- *Hades*' **Chaos gates**: take a curse now for a reward later.

**Proposal: five ways to get what you lack.**
1. **Ask.** Characters and some calm monsters tell you where things are (tips exist; extend them to "where's
   something fire?").
2. **Make it.** An alchemy bench or a campfire: two things' tags into a coating or a potion (oil + a rag = a fire
   bomb; holy water on your blade = holy for three hits). Coatings already exist in the rules.
3. **Buy it.** The peddler and shops, with a paid restock; you can ask the peddler for a tag ("anything holy?") for
   more gold.
4. **Trade it.** Characters want things (Lenny wants his tooth); the trade economy can grow from there.
5. **Bargain for it.** A dark altar: the item you need now, for a curse (deeper down, more of these).

And pity everywhere a missing thing would stop you: the floor's boss key and the essentials always appear.

---

## 8. The darkening descent

**What other games do**
- *Darkest Dungeon*'s **torch**: light burns down; in the dark, monsters surprise you more and stress climbs, but the
  loot is better. One resource carries both the mood and the risk.
- *Inscryption* changes its whole tone (and genre) as it goes; the shift is the story.
- *The Binding of Isaac* goes from a basement to the womb to hell: each chapter more grotesque, with its own monsters
  and music.

**Proposal: light, and three registers of tone.**
- **Light** is a resource: torches, candles, the glow stick and the jar o' light already exist as items. It burns down
  floor by floor. In the dark:
  - ambushes come more often, and the dark's own monsters appear;
  - searches find more (Darkest Dungeon's rule);
  - **the screen dims**: the palette desaturates and shifts toward red, and the room picture loses its colours;
  - the narrator gets terse.
- **Three registers**, set by depth, and by light within a floor:

| Depth | Feel | Monsters | Screen | Narrator |
|---|---|---|---|---|
| Floors 1–2 | light, slapstick | the kids' sillies, vermin, goblins | the full phosphor palette | darkly funny (today) |
| Floors 3–4 | eerie | undead, drowned things, the wrong-shaped | cooler, dimmer | quieter, unsettling |
| Floors 5–6 | grim | fewer, worse things | low light, red accents | spare, serious |
| The Below | desperate | the dark's own; echoes of what you killed above | near-monochrome, flicker | barely there |

The narrator's tone is already a setting (`Config.tone`); a ladder by depth is a small change with a big effect.

**Questions**
- Can the kids' monsters appear darker deeper down (a "hollow" Lenny?), or are their characters always kept light?
- Does light burn per floor, per room, or per turn?

---

## 9. The endgame and unlocks

**What other games do**
- *Isaac* unlocks new floors and bosses as you beat the old ones; the "true" ending takes many runs.
- *Slay the Spire* hides Act 4 behind **three keys**, each earned by an optional, costly act during the run (rest
  without healing; fight a burning elite; skip a treasure). Knowing the secret is the unlock.
- *Hades* turns the post-game into a dial (Heat) and a story.

**Proposal**
- **The Below** (floors 7–10) opens after the first win.
- **Three seals** to reach its bottom in a run, each optional and costly:
  - spare a character you could have killed;
  - find every secret room on a floor;
  - descend without the safe rest.
  
  Knowledge of the seals is passed by the narrator, by ghosts and by tips.
- **The dial** (section 4 of the numbers plan): named handicaps for more souls, after the Below is opened.
- **Souls** keep buying permanent things at the campfire, but **variety, not power**: new starting kits, new items in
  the pools, pack size. Power creep from meta upgrades makes the early floors trivial (Rogue Legacy's problem).

---

## 10. What's ours alone

1. **Creativity as a skill with rules underneath.** The language engine (section 3) means the best players are the
   most inventive *and* the most knowledgeable.
2. **The narrator as a character.** It can hint, warn, tease and, in the dark, go quiet. A good game master is part of
   the challenge's fairness.
3. **The kids' Maker feeds everything.** Monsters, items, junk, bosses with rules, named pairs.
4. **Ghosts of your own past runs** (they exist) are knowledge and danger at once.
5. **The terminal itself darkens.** The palette is the mood, and it's data.
6. **The bestiary across runs.** Knowledge persists; a returning player is already stronger, without a single number
   changing.

---

## 11. What to avoid (lessons from other games)

- **Hidden math.** Every bonus that counts is visible on the Sheet and in the roll.
- **Math soup.** Twenty small always-on bonuses are worse than three that matter. (Worn trinkets only.)
- **Power creep from meta upgrades.** Unlocks widen the game, they don't flatten it.
- **Dead items.** Every item has a use, even junk (props, trades, converters).
- **Unfair creativity.** The interpreter and the narrator must judge by the same rules each time, or creativity
  feels like luck.
- **Tedium.** Backtracking, "search everything" chores, waiting. A walk-to-room action; searches that are decisions,
  not chores.
- **Despair without agency.** Dark is good; hopeless is not. There's always a way (pillar 3).

---

## 12. Working through it

Proposed order for our sessions, each ending in decisions written into this document:

1. Pillars and the run (sections 1–2): is this the game?
2. Tags (3): the vocabulary and its rules.
3. Skill (4) and intents: the monster intent set.
4. Synergies (5) and converters: the first families and loops.
5. Bosses (6): one rule each for the three we have.
6. Getting what you need (7) and the economy.
7. The darkening (8): light, the tone ladder, the palette.
8. Endgame (9) and unlocks.

Then the numbers plan (`progression-loot-difficulty.md`) is revised to match, and the bot report tells us whether it
holds.
