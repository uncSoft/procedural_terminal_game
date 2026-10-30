# Fights with several foes, timed statuses, and floor 5 in the run

Status: **built** (2026-10-29; what's still yours to settle: §6). Marked **✅** where it's decided, **❓** where it's
yours to settle. JT's ask: make
floor 5 playable, with a small quest (a web-sealed door, burnt open with the torch, the Sporefang Matriarch behind it,
who gives the Philter of Light for the Important Ring), a boss that's the game's first fight against several foes at
once (the Humongous Fungus: four parts, each with its own health and its own job), and more statuses (burn, stun,
buffs) like poison. Floor 5 is reached ✅ **after a first win**: once you've beaten Serpentis in any run, later runs go
on down past her.

---

## 1. Several foes at once ✅

**The foe you face, and the others.** A room's `monster` stays what it's always been: the one in front of you, the
one your blows, throws and words go to. A fight can now have `others` beside it (`Room.others`): the rest of the
fight. Everything that works on one foe today keeps working on the one you face, so a fight against one is just as it
was, and a save from before loads as it was.

- **Who you face**: "Face the Rot Gill" turns you to another foe, and costs nothing (no turn). The choices and Here
  have it for each of the others; your attacks, throws, burns and words go to whoever you face.
- **Their goes**: after yours, every foe still standing has its go, the one you face first, then the others in turn,
  each with its own intent shown over its head.
- **One falls**: its XP, gold, souls and drops are yours as ever, and the next foe still standing is the one you face.
  The fight is won when the last of them falls (its style, its spoils card, the room's music back).
- **Fleeing** gets you away from all of them, at one roll; it's as hard as the hardest of them makes it (one that
  holds its ground, holds it for all).
- **A bomb** goes off at the feet of the one you face, and the blast catches the others for half. Smoke hides you from
  all of them. A distraction, a dazzle, talking one down: the one you face.
- **Who comes together** (`party` in monsters.toml): a monster can bring others into its fight: a Sporerat never comes
  alone (its party: another Sporerat), and a boss can be a party (the Humongous Fungus). Data, so the maker can
  give any monster one later.

**The stage** shows every foe side by side, each in its own place (smaller the more there are), each with its own
health bar under it and its next move over its head; the one you face stands in the light with a ▼ over it, the
others a little dimmer. The banner is the one you face's. Here has a tile for each.

## 2. Timed statuses, on you and on them ✅

Statuses (statuses.toml) can now **wear off** (`lasts`: rounds or steps), **cost a go** (`skip`), and **help**
(`mend`: health back each tick), and monsters have them too (`MonsterState.statuses`).

| Status | What it does | Where it comes from |
|---|---|---|
| ☠ Poisoned | as now: -2 to your rolls, 2 a step and a round, never the last | bites, vents, the river |
| ♨ Burning (`burn`) | 2 a round for 3 rounds (and a step), it can kill; water puts it out (a fountain) | monsters with the `burn` trick; on a monster (3 a turn): your torch, lamp oil thrown, a fire-coated blade |
| ✶ Stunned (`stun`) | your next go is lost (the foes go on); a stunned monster loses its next go, as now | the Puff Mound's spores; on a monster: a bomb's blast, a distraction (as now) |
| ✚ Mending (`mend`) | 3 back a round for 3 rounds | on a monster: the Spore Mother mends its side; on you, ❓ later (a shrine's blessing, a potion) |

The status bar shows each, with the rounds it has left (`🔥3`); a monster's are under its health bar.

## 3. The Underbloom's own things ✅

- **Its monsters** (JT's, from the maker): the **Sporerat** (tier 3, a pair: its party), **the Hollowed** (tier 3),
  and **Lady Bogmire** (tier 3, added from the maker 2026-10-30). Kept to the Underbloom (`dungeons`), so the floors
  above don't change. ❓ The **Green Slime** and **Ra-bit** are in the maker's saves too, waiting for a floor.
- **The web door**: one room on the floor has a door sealed with web as thick as a sail. Standing by it you're warned
  (something hisses on the other side, spore dust puffs through). No hand, blade or bomb gets through: only fire (your
  torch: a flame). Behind it, **the Matriarch's Lair**.
- **The Sporefang Matriarch** (JT's art; tier 4, 120 HP): she comes in with her own **screech** (a new sound, her
  `cry` in monsters.toml: it plays as she lands, in place of the sting, and as she rears up for a heavy blow), called
  out on a card as a guardian is ("GUARDIAN OF THE UNDERBLOOM"), and fights you. Give her **A Ring, Probably
  Important** (it's cursed: nobody else will take it) and she takes it, stops, and leaves you the **Philter of Light**
  (JT's art) at your feet: her `wants` and `gives`, so the maker could give any monster a trade. Killed, she leaves no
  Philter. ❓ Her clips come from JT's 3D pipeline; till then she comes in as any monster does.
- **The Philter of Light**: a light that never burns down (a torch's light, not its fire), and it warms you: +5 most
  HP while you carry it. Great spiders fear it ❓ (later: the Matriarch's kin flee its glare).
- **The boss: the Humongous Fungus** (after the giant mycelium out west), the first fight against several foes, in the
  **Spore Bed** behind the floor's locked door (its key: the **Glowcap Key**, somewhere past halfway). Four parts, each
  with its own health; which to kill first is the fight:

  | Part | HP | Its job |
  |---|---|---|
  | **The Humongous Fungus** (its great cap) | 50 | the one that hurts: 2d6, and a boss's heavy blows (2d6 twice) |
  | **The Spore Mother** | 14 | mends the most hurt of the others instead of striking (✚ Mending: 5 a turn, 3 turns) |
  | **The Rot Gill** | 16 | its bite can poison you, and its heavy blow is a spit that always does |
  | **The Puff Mound** | 14 | bursts spores that stun you (✶): half its blows, every heavy one |

  The three helpers barely scratch you (1d2): what they do is their job. Facing is free, so the way to play it is
  to turn to whoever's winding up a heavy blow and dodge, then back to whoever you're killing. Mother first is the
  quick way (alive, she mends the Fungus faster than most can hurt it).
  ❓ Their art: stand-ins drawn here (in the palette) till JT draws them in the maker.

## 4. Floor 5 in the run ✅

- A run is five floors once you've beaten Serpentis in any run (a win in the profile): the Underbloom is the fifth.
  Before that, runs are four floors, as now.
- On a five-floor run, Serpentis is no longer the end: her lair's floor cracks when she falls, and its stairs go down.
  The run is won by beating the Humongous Fungus.
- Tiers spread over the run, as they always have (world.tier_for: the top tier from three quarters of the way down,
  for the 10-12 floors to come), so a five-floor run's third floor has tier-2 monsters, not tier 3: a first win makes
  the dungeons a little gentler, and the Underbloom the test. Floor 5 is deeper still (DEPTH: 1.35× HP, +2 to hit,
  +1 defense, +1 damage), and floor 4 is as it was. Four-floor runs are exactly as before (the same 400 seeds, the
  same results).
- The intro card shows the floor's splash (the stand-in, ❓ till a painting replaces it:
  `uv run python tools/make_splash.py picture.png --floor underbloom`), its lore (now with its hints: it hates light
  and fire, its family minds it, its key has a little blue cap) and its goal.
- A daily run stays four floors for everyone, as everyone's daily is the same.
- On a dark floor the key is never put inside a thing wrapped in threads (only fire opens those): no torch mustn't mean
  no way on.

## 5. Building it, in order

1. The maker's art in the game: the Matriarch, the Philter, the Sporerat, the Hollowed.
2. Timed statuses: burn, stun, mend; monsters' statuses.
3. Several foes: the rules (who you face, their goes, falling, fleeing, bombs), then the stage and Here.
4. The web door, the Matriarch's lair and her trade; her screech.
5. The Humongous Fungus: its four parts, its room, its key; floor 5 in the run after a first win.
6. Test rooms for each (the Matriarch, the boss), a run to the end, and the tests.

## 6. Built, and what's still yours ❓

All of it is in (2026-10-29), with tests (tests/test_foes.py, tests/test_underbloom.py) and test rooms:
`uv run ptg --test-room matriarch` (by the web, a torch and the Ring) and `uv run ptg --test-room humongous_fungus`.

**How hard it is** (tools/simulate.py, 400 seeds, `--deep` for five floors; the bots only attack, dodge and drink,
never turn to another foe, burn, bomb or trade):

| | newcomer bot | veteran bot |
|---|---|---|
| four floors, won | 11% (as before) | 49% (as before) |
| five floors, won | 5% | 40% |
| died on floor 5, of those who got there | 72% | 38% |
| the Spore Bed: rounds, HP it costs (median) | 7, 38% | 6, 37% |

The Humongous Fungus is what kills most on floor 5, then the Hollowed. A player who turns to dodge the Fungus's heavy
blows and kills the Mother first does better than the bots; one who brings a torch has fire for it (it's weak to fire
and light). Tune in monsters.toml (each part's numbers) and world.DEPTH[5].

**Yours to settle:**

- The boss parts' art: stand-ins (in the palette, two frames each) till you draw them; the Glowcap Key's too (its
  3D model is made from it: `uv run ptg models glowcap_key` after a new sprite). Their 3D clips (below) were made
  from the stand-ins: a new drawing means running its part through the pipeline again.
- ✅ Clips from the 3D pipeline (2026-10-30): the Sporefang Matriarch and all four of the Spore Bed, each with an
  entrance, an idle, an attack and a windup at 40, 48, 64 and 84 (spikes/goblin3d). The Spore Bed's four come in
  together, stand side by side at one size, and swing at once when they strike.
- The splash: a painting to replace the stand-in.
- The balance above, once you've played it: the Spore Bed's numbers, the Underbloom's depth, and whether a first win
  should soften floor 3 (it does now, tiers spreading over five floors) or leave it as it was.
- More for the floor: the Green Slime, Lady Bogmire and Ra-bit are in the maker's saves, waiting for a floor; Bloom
  and the puffball path (floor-5.md §5); the Matriarch's kin fleeing the Philter's glare.

