# Ideas and later work

Things we've decided are worth doing, but not yet. Newest at the bottom of each section.

## The long quest: a reason to come back

Something that lasts beyond stats and unlocks: an overarching quest, like collecting a number of something rare and
random across runs, that unlocks the real boss fight. It's for replayability, so each run has a slim chance of
moving the long story along.

What the game already has to build it on:

- **The profile outlives every run** (`profile.py`, SQLite): souls, unlocks, the bestiary, the Book of Secrets and
  ghosts are all kept there.
- **Story events** (`docs/writing-events.md`) can set marks on the profile and show cards in the writer's own words,
  so the quest's moments can be written by hand.
- **Secret rooms and rare loot** (items found only in certain places) are natural homes for the pieces.

Open questions for later: what the pieces are and how many, whether they show at the campfire, what "the real boss"
is and where its fight happens (a fourth floor? a hidden door on the last one?), and whether dying costs any of them.

## Combat polish

Special moves for enemies, and polish around fights generally. A session card was proposed for it ("Combat polish:
special moves for enemies"). It starts with a design for you to agree before any code.

## Your ghost's secret

Meeting your own ghost should be able to go somewhere a fight can't: a secret interaction, written by hand. The story
hooks are in (see "Your ghost" in `docs/writing-events.md`): `{ghost}`, `{ghost_cause}` and `{ghost_epitaph}`, the
`[calm]` effect, and ghost scenes that play out mid-fight. The scene itself is still to write.

## Stealing from the grannies

Later, after shops. Grab a ware with an agility roll; if you're caught, the granny fights you (Granny Gristle: "Steal
from her and find out why"; Granny Kamultruk: "NO TAKE CANDLE!"). Stealing should also have a secret, additive side:

- **A running secret tally**, kept in the profile across runs: every item stolen and what it was worth. Nothing shows
  it at first.
- **A bounty** that grows with the tally: shopkeepers (and maybe others) start to know your face.
- **Achievements** for it, found rather than listed.

The tally is to be used later, so it's worth recording from the first theft even before anything reads it.

## Shops, next

- **A back way in:** when a shop sits next to the floor's secret room, bomb into the secret room, then through its
  wall into the shop (two bombs, one per wall). Only the door (a key, or two bombs) is built.
- **The maker** can't say an item is sold in shops (`found = ["shop"]`) yet, so shop-only things go in by hand.
- **Selling to her:** Granny Gristle "buys anything". Not built: shops only sell.

## Loot, rarity and the maker

Loose ends from adding item powers, rare things, keys, bombs and secret rooms:

- **The maker can't set `powers` or `found` yet.** Items made there come in without them (an import keeps what an
  existing item already had). A power picker and a "where it's found" picker would let JT and others make rare
  things without touching `items.toml`.
- **Warden drops repeat.** Each floor caps the warden's rare drop by tier, and there are few rare things of tier 1
  or 2: floor 1's warden has none and gives a small key, and floor 2's almost always gives the Snitch. More rare
  items with `found = ["warden"]` (or a monster's own key) would make them a surprise again.
- **Nothing is salty.** The Living Armor is weak to `salt`, and no item or room feature is tagged with it.
- **Balance, as the bot plays it** (`tests/bot.py`, which never bombs a wall): 45% of runs won before this work,
  46% after (800 runs). Wardens giving a strong potion when they had nothing rare left took it to 59%, which is why
  they carry a small key instead. Spreading each floor's loot out (one thing to a hiding place) took it to 50%, since
  loot that isn't piled in one cupboard gets found; a healing potion less on floor 2 put it back to 46%. Shops
  and free pickups left it there (46.5%).
