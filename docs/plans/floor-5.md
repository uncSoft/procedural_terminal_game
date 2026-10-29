# Floor 5: the Underbloom

Status: **its look, its rooms and the torch are built; its monsters are being made (JT's), and its boss comes
last.** Marked **✅** where it's decided, **❓** where it's yours to settle. It's in no run yet:
`themes.toml` has it as floor 5, below the run's four (`models.FLOORS`), waiting for its boss.

What this covers: the floor under Norfel, its look (dark, lit by what grows there and the torch you bring), its rooms,
and the torch. The floor's status, its hazard, its people and its boss are sketched at the end, from the pitch.

---

## 1. In short

- ✅ **Under Norfel, the poison drips down, and something learned to drink it.** A fungal deep: black rock furred with
  white threads, glowcaps as tall as trees, puffball fields, curtains of threads with things wrapped in them, and the
  dead of the floors above washed down and grown over.
- ✅ **It's the gear, level and strategy check.** Norfel asked "did you buy the right things?"; the Underbloom asks
  "how long can you stay?" (the pitch: resting isn't free here).
- ✅ **Dark and light.** No light but what grows (cold teal, violet, mint) and what you carry. Bring a torch and the
  floor near you is warm; without one, you see by the glow. One room glows not at all.
- ✅ **The boss is last**, once there's a sprite you love.
- ✅ **The torch**: in your pack, five flames of light, each thing you burn costs one, lamp oil fills it; harder
  without one, and you can see at a glance which you've got (section 4).

---

## 2. The look ✅ (built: `room_picture.py`, the `underbloom` look)

A dark floor (`Look.dark`): the room's own light is very low, and your carried light is a torch's, warm, if you have
one (`carries_light`: a `torch` in your pack), else only eyes used to the dark (`Look.glimmer`). What grows there
gives off a cold light of its own, which turns any surface it falls on teal (`Look.glow`, a third kind of light beside
a candle's warmth). Pictures keep to the sprites' palette, and to the colour budget a terminal's cache needs.

- **Walls**: dark rock with white threads hanging from the ceiling, some all the way down (`walls = "hyphae"`), and
  shelf fungi growing out of them in glowing clusters, which light the wall round them (`sconces = "brackets"`).
- **Floor**: dark soil, pale mats of threads creeping over it (`ground = "mycelium"`).
- **Ceiling**: glow-worms in the rock, and their silk hanging down with a glowing bead at the end
  (`above = "glowworms"`).
- **The air**: spores drifting up, a pixel a frame on the stage, so the room breathes.
- **Things that grow** (decor): glowcaps as tall as trees (`caps`), curtains of threads (`threads`), puffballs that
  glow pale (`puffballs`), and the little mushrooms every floor has, here in cyan, violet and mint.
- **Everything's overgrown**: props sprout little glowing caps on pale stalks along their tops, the chapel's pillars
  are furred white, and what you can use glows enough to be seen (`Look.overgrown`).
- **The Dark Hollow** (`decor` has `dark`): nothing grows, nothing glows. Without a torch it's black but for what's
  in it; with one, your torch is the room's only light.
- **Your torch**, in the bottom left of the picture, its flame flickering between the stage's frames.
- **The floor's card**: a stand-in splash drawn by the same renderer (a glowcap grove, no torch), at every size a card
  draws. A painting can replace it: `uv run python tools/make_splash.py picture.png --floor underbloom`.

See it in a terminal:

```bash
uv run python -m ptg.room_picture 7 underbloom
uv run python -m ptg.room_picture 7 underbloom torch
```

---

## 3. The rooms ✅ (built: `rooms.toml`)

| Room | What's there | What it's for |
|---|---|---|
| Glowcap Grove | mushrooms as tall as trees, spores like slow snow | the floor's postcard; light without a torch |
| Puffball Field | puffballs from fist- to cart-sized, glittering spore clouds | ❓ the floor's hazard (§5) |
| Thread Hall | curtains of threads, cocoons, a bundle that might be a backpack | loot wrapped up, and things that move |
| The Compost | the dead of the floors above, furred in mould and sprouting caps | ❓ the Hollowed (§5), and old gear |
| The Drip | Norfel's poison dripping into a pool the fungus drinks from | the link to floor 4 |
| Sporerat Burrow | gnawed tunnels, a hoard of shiny bits | ❓ the sporerats (§5) |
| The Dark Hollow | nothing grows, nothing glows | the torch's room: harder without one |
| The Swallowed Chapel | a chapel eaten by fungus, an altar still glowing faintly | a shrine, overgrown |

Each has two names, a blurb (said as it is when there's no narrator) and three things to search, as the others have.
The boss's room comes with the boss.

---

## 4. The torch ✅ (built: `light.py`; JT, 2026-10-29: "Build as proposed", and a cue for torch or no torch)

The game's Torch (a tier-1 trinket that was already about: +1 searching) is the light. It has a new power, `torch`
(powers.py), so the maker could make another light some day. The rules live in `light.py`:

- **What it is**: a light you carry in your pack (no slot), so it never costs you your sword. On a dark floor
  (`dark = true` in themes.toml) it's lit as soon as you're there: "You light your torch."
- **Its light: five flames** (`light.FLAMES`). Walking about costs none: it lasts the floor. Each thing you **burn**
  with it costs a flame, so light and fire compete: the strategy check. The last flame spent, the torch is gone, and
  the next one in your pack is lit. A **Flask of Lamp Oil** poured over it puts every flame back ("Fill your torch").
- **Without one**, down there:
  - **by the glow** (any room that grows something): your searches for secrets are at a disadvantage;
  - **in the dark** (a room nothing lights: the Dark Hollow, `dark` in its decor): every roll of yours is at a
    disadvantage ("attack, in the dark" on the dice), and whatever's there **gets the first blow** as you walk in.
  - Granny's shop has her own lamp.
- **With one**: none of that, and fire on hand:
  - **burn a monster**: a might roll for 1d6 of fire, with advantage and +2 if it's weak to fire (the Walking
    Toadstool is). A flame when it lands; a miss costs only the turn;
  - **burn open what's wrapped in threads** (a cocoon, a curtain of threads, a bundle): no hand gets into those, only
    fire, and what's inside is yours;
  - still to come: burn the Bloom off you, and a path through the puffballs (§5).
- **Up above it's packed away**: on a lit floor there's no burning with it (its flames are for the dark).
- **Where you get it**: on the floor above a dark one, there's always a shop, with two torches and two flasks of oil
  on the counter (and on a dark floor, a shop as often as on Norfel, with the same). It can still turn up as a
  trinket anywhere.
- **The cue** (you asked for one):
  - **the status bar**: `☼ torch ▲▲▲▲△` in orange, a flame for each it has left; `☼ no light` in grey; `☼ in the
    dark` in red;
  - **the stage**: your torch, big in the bottom-left corner, its flame flickering, the floor round you warm;
  - **the story**: a line when it's lit, filled or goes out. Without one, you're told what you're in for, and "A
    light source would be super helpful down here!"
  - **the status tab**: what it does, or what you're missing.
- **Try it**: the test rooms `underbloom` (a torch and lamp oil) and `underbloom_dark` (no light), on floor 5,
  next door to the Dark Hollow with something in it. From the debug screen (F12, Test rooms), or:

  ```bash
  uv run ptg --test-room underbloom
  ```

- **Still yours to decide**: whether a torch burns out going down the stairs ("a floor's worth"), once there's a
  dark floor below a dark floor. Today it carries on. The **Fire Rod** for your hand (a weapon that's a light and a
  fire), and an **Ice Rod** beside it, are for later.

---

## 5. To come (from the pitch)

- **Bloom**, the floor's status ❓: spores take root in you, and grow when you rest (the fungus loves a sleeper): an
  itch, then worse, then you've sprouted (most HP down until it's burned out). Fire burns it out at a cost; a shrine
  cures it. It's what makes resting cost something here.
- **The puffball field**, the floor's hazard ❓: cross it by burning a path, tiptoeing (agility), or walking through
  and blooming.
- **Its monsters** (JT's, rendering now) ❓: the **Hollowed** (the dead from above, the fungus wearing them, your own
  past characters among them, with what they died with), **sporerats** (swarms that steal), **puffbacks** (burst into
  spores when they die), **lantern caps** (walking lights that lure you). Their tags should take in `fungus` or
  `spores`, the floor's `monster_tags`, or the maker can keep them to the Underbloom.
- **A gold sink** ❓: a mushroom monk who sells grafts, power with a price (the Glowcap Eye, the Mycelial Arm).
- **The boss** ❓: last. The pitch's Pale Gardener (weak to fire; it eats poison, so it heals while you're poisoned)
  until a sprite you love says otherwise.
- **Getting there** ❓: the first step of the endgame you reach over runs: once you've beaten Serpentis, her death
  cracks her lair's floor, and later runs go on down.
