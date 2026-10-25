# Procedural Terminal Game: the design (a living draft)

We write this together, section by section, before building. Each system says how other games do it, what makes
that work, what to avoid, and a proposal for us, with the questions only you can answer. Numbers live in
`progression-loot-difficulty.md`; this document is about *what the game is*.

Status: **first draft**. Nothing here is decided until we've gone through it.

---

## 0. The pitch, in one paragraph

A roguelike you play by **talking**: each run is a descent of 30–40 minutes through dungeons the kids helped build,
with a companion at your side who tells the story, has opinions of its own, and can, once or twice a run, grant a
wish. It starts light and silly (a leprechaun's cousin who lost his
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
- **The endgame** (unlocked, see section 12) adds floors below the sixth: *the Below*.

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
3. **Resources over time.** Fate, potions, bombs, keys, light (section 11), the safe rest: when to spend them.
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

## 8. The companion: the narrator in the dungeon

Today the narrator is a voice with no body. Make it **a character who came down with you**: it tells the story, but it
has a personality, opinions, a memory and an agenda of its own.

**What other games do**
- *Bastion*'s narrator reacts to exactly what you do ("The Kid rages for a while") and made a small game feel
  authored. **Reactivity is the magic.**
- *Hades*: the characters remember your runs, comment on your deaths and your choices, and change over many runs. A
  relationship that grows **across** runs is a reason to come back.
- *Zelda: Twilight Princess*'s Midna has her own agenda, a sharp tongue and a secret that turns the story; she's loved.
  *Ocarina of Time*'s Navi ("Hey! Listen!") and *Skyward Sword*'s Fi are remembered for **nagging and over-explaining**.
- *Interstellar*'s TARS has dials: "humor 75%, honesty 90%". A personality you can **tune** is a joke and a feature.
- *Cult of the Lamb*: you're bound by a pact to a being with its own plans for you. *Disco Elysium*: the voices in
  your head have agendas and can be wrong.
- *Portal*'s GLaDOS and *The Stanley Parable*'s narrator: a narrator who can be **against you**, or lie.

**What makes it work:** brevity, reactivity to your specific actions, memory, a secret or agenda that pays off, real
usefulness. **What to avoid:** nagging, solving the game for you, repeating itself, talking more than the player
does (with a model's latency, every extra sentence is waiting).

**Proposal**
- **Choose a companion at the campfire** (one at first, more as unlocks), each a different voice *and* a different
  way to play:

  | Companion | Voice | What it does for you | Its agenda |
  |---|---|---|---|
  | **The Unit**, an anachronistic machine from the future (a TARS, a Pip-Boy) | dry, precise, dials for humor and honesty | **shows the odds** and analyses foes (weaknesses it has seen) | it's collecting data on the dungeon, for someone |
  | **A fairy** (Navi, but bearable) | bright, curious, scared of the dark | **is a light** (section 11) and finds hidden things | it's looking for its lost court, deep down |
  | **A familiar** bound to you by a life-oath since you rescued it | sly, old, polite in a threatening way | **bargains**: curses and dark deals, and the strongest wishes | the oath has a clause it didn't mention |

- **It's useful on request, quiet otherwise.** Ask it something ("what's this weak to?", "is it safe to rest?") and
  it answers in character, from facts the engine gives it. It never nags.
- **A bond** that grows with the run (and a little across runs): how much it helps, how often it warns you, the
  strength of its wishes. Doing what it likes or hates moves it (*Baldur's Gate 3*'s approval, lightly).
- **It remembers** across runs (the profile already keeps runs, deaths and the bestiary): "Last time a rat king ate
  you on floor one. I'd rather it didn't."
- **Its voice darkens with depth** (the tone ladder), and in the Below its agenda comes out. That's the endgame's
  story (section 12).
- **It's the narrator.** The same model, the same facts; the difference is that it speaks *as* someone. One prompt,
  three personalities.

**Questions**
- Which companion first? (The prototypes you have may decide this.)
- Does the companion ever lie? (Only in the dark? Only the familiar?) Fun, but it must never lie about the *rules*.
- Can it die, or leave you?

---

## 9. Wishes

A rare power: say what you want, and the game makes it, item and picture, with the risk that you get exactly what
you said and not what you meant.

**What other games do**
- *NetHack*'s wish (a wand of wishing, a throne, a fountain) is the most famous moment in the game. Players **study**
  what to wish for; knowledge decides the run. Rare and precious.
- *Scribblenauts*: write any noun and it appears. It works because every word maps onto a **fixed set of
  properties** the game understands; with no limits, "god" solved every puzzle, so the game added costs and limits.
- Tabletop *D&D*'s Wish and the **monkey's paw**: the game master's right to take a wish too literally is half the fun,
  and keeps wishes from breaking the game.
- *AI Dungeon*: anything goes, so nothing is at stake. **The rules are what make a wish mean something.**

**What makes it work:** rarity; the wish lands in the game's real systems; a cost, a limit or a twist; the result is
legible (you can see what you got). **What to avoid:** a wish that bypasses the game ("I wish to win"), and an item
whose words promise what the engine can't do.

The spike shows the second risk already. The **Heartstone Locket of Second Life** is described as "restores its
wearer to full health when opened and permanently adds 15 to maximum HP", but its powers are *None*. The engine check
passed because the item is valid; it just doesn't do what it says. And `#ruby` isn't a tag the game knows.

**Proposal: mechanics first, words second.**
1. **The wish compiler.** The model reads the wish and builds an item **from the engine's parts**: its kind and slot,
   stats, powers (the existing `powers.POWERS`), tags (only from the vocabulary), uses or charges, within a **power
   budget** set by the wish's strength. *Then* it writes the name and description from what it built, and draws the
   picture.
2. **Over budget, the monkey's paw.** A wish that asks for more than its budget is granted **literally, smaller, or
   with a price**: full health once (a consumable, not a locket); +15 HP that's also cursed; a weapon "that never
   misses" that hits for 1. The companion's personality decides the flavour of the twist (the familiar's are cruel).
3. **The library first.** If a kid-made or library item already fits, the wish brings *that* (fast, cheap, and the
   kids' things turn up). New art is generated only when nothing fits, using the library's sprites and palette as
   reference.
4. **Not only items.** A wish can be a **world command** the engine knows: open a way, a key, a safe passage past one
   fight, the boss's weakness revealed. Each maps to an engine action (section 10).
5. **Rare.** One or two a run: from the companion's bond, a boss, a fountain or a seal. Wishes could stack across the
   run as *wish shards*.
6. **Kept.** A good wish can be saved to the library at the end of the run, a new item for the Maker and for later
   runs (with the kids' approval?). Players adding to the game by playing it would be ours alone.

**Questions**
- How literal by default: playful twists, or exactly fair?
- Which models can do this well? (The spike's 24×24 Haiku result took 19 seconds.) A smaller local model could fall
  back to library-only wishes.
- Do wished items go into the shared library automatically, or only when someone approves them?

---

## 10. Words that change the world

Your Kool-Aid Man moment, from a real run: no bombs left, a secret room known to be behind the wall, a *critical*
might roll, and **nothing happened**, because the engine has no way to open a wall except a bomb. The interpreter can
only send back a fixed list of effects (damage, stun, pacify, escape, evade, reveal_secret, find_item, find_gold,
heal_small), so there was nothing to send, and the narrator, told nothing, invented "an empty space where a wall used
to be". That's two problems: a **missing effect**, and a **narrator that made up an outcome the engine didn't
produce**.

**What other games do:** *Breath of the Wild* and *Divinity* let systems change the world (burn the bridge, freeze
the river) because the world is built from things those systems can touch.

**Proposal: give the interpreter a vocabulary of world effects, each a real engine command with rules.**

| Effect | What it does | When it's allowed | Its price |
|---|---|---|---|
| `breach` | opens a cracked wall (a known draft: the secret room) | might, hard; a heavy or sharp tool helps | noise wakes the floor's monsters; a failure hurts you |
| `force_door` | opens a locked door | might or agility, hard; never the boss's door | a shop's keeper is not pleased |
| `light` / `douse` | lights or puts out a fixture, a prop, a room | a fire or water tag | light matters (section 11) |
| `barricade` | blocks a way out | heavy props | a fight can't follow you, and you can't go back that way |
| `collapse` | brings something down on a foe | a heavy fixture or prop, hard | the prop is spent; the room changes |

- The engine checks every effect against the room (a wall with a draft, a locked door), as it already checks props,
  and **an effect that can't apply isn't sent**.
- **The narrator narrates only what happened**: the guard (`llm/guard.py`) gets a rule that a creative action with no
  effect is told as an attempt that didn't change anything. That's already the rule for stunts that come to nothing;
  your crit fell through a gap in it.

This one is small and could be built ahead of everything else.

---

## 11. The darkening descent

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

## 12. The endgame and unlocks

**What other games do**
- *Isaac* unlocks new floors and bosses as you beat the old ones; the "true" ending takes many runs.
- *Slay the Spire* hides Act 4 behind **three keys**, each earned by an optional, costly act during the run (rest
  without healing; fight a burning elite; skip a treasure). Knowing the secret is the unlock.
- *Hades* turns the post-game into a dial (Heat) and a story.

**Proposal**
- **The Below** (floors 7–10) opens after the first win. It's where the companion's agenda comes out (section 8).
- **Three seals** to reach its bottom in a run, each optional and costly:
  - spare a character you could have killed;
  - find every secret room on a floor;
  - descend without the safe rest.
  
  Knowledge of the seals is passed by the narrator, by ghosts and by tips.
- **The dial** (section 3.8 of the numbers plan): named handicaps for more souls, after the Below is opened.
- **Souls** keep buying permanent things at the campfire, but **variety, not power**: new starting kits, new items in
  the pools, pack size. Power creep from meta upgrades makes the early floors trivial (Rogue Legacy's problem).

---

## 13. What's ours alone

1. **Creativity as a skill with rules underneath.** The language engine (section 3) means the best players are the
   most inventive *and* the most knowledgeable.
2. **The narrator as a companion** (section 8): a character with a voice, a memory and an agenda, who tells the
   story, answers questions and grants wishes.
3. **Wishes made real** (section 9): say what you need, and the game builds the item, picture and all, out of its own
   rules.
4. **The kids' Maker feeds everything.** Monsters, items, junk, bosses with rules, named pairs.
5. **Ghosts of your own past runs** (they exist) are knowledge and danger at once.
6. **The terminal itself darkens.** The palette is the mood, and it's data.
7. **The bestiary across runs.** Knowledge persists; a returning player is already stronger, without a single number
   changing.

---

## 14. What to avoid (lessons from other games)

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

## 15. Working through it

Proposed order for our sessions, each ending in decisions written into this document:

1. Pillars and the run (sections 1–2): is this the game?
2. Tags (3): the vocabulary and its rules.
3. Skill (4) and intents: the monster intent set.
4. Synergies (5) and converters: the first families and loops.
5. Bosses (6): one rule each for the three we have.
6. Getting what you need (7) and the economy.
7. The companion (8): who it is, what it does, its agenda.
8. Wishes (9): the compiler, the budget, the twists.
9. Words that change the world (10): the effect vocabulary (small; could be built first).
10. The darkening (11): light, the tone ladder, the palette.
11. Endgame (12) and unlocks.

Then the numbers plan (`progression-loot-difficulty.md`) is revised to match, and the bot report tells us whether it
holds.
