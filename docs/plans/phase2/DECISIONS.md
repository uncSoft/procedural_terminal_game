# The owner's decisions (JT, 2026-10-24) — build to these, don't re-ask

- LAYOUT: "Stage + Here sidebar", exactly as the approved spike `docs/plans/phase2/layout_spike.py` in the main checkout
  (docs/plans/phase2/layout_spike.py, read it): a fixed stage (the room's picture)
  above a text-only story; a Here panel of the room's characters and things as tiles with verbs; the floor map and arrow
  pad in the side column; choices as a compact strip of 1-3 lines under the story (only as tall as needed); one column
  on narrow screens (stage, Here strip, story, ways bar, choices); a compact status bar and 1-row command line on small
  screens; a touch mode with 3-row buttons. Reactive to the display size (browser and phones too). Tile verbs are
  numbered first, then the choices continue the numbering. (The layout itself is built in a later phase, after the
  tracks merge: W11.)
- CHARACTERS ARE ALWAYS IN COLOUR: no grey "calm" tone anywhere (sprites.posed "calm" must not grey them out). Friendly
  shows through the status line / badge, not greyscale.
- GEAR: a weapon or armor you pick up goes to your pack, NEVER the floor. Offer "Equip X (replaces Y: 1d6 -> 2d6+2)"
  with the comparison. It equips by itself ONLY into an empty slot (not when "better"). The old piece goes to the pack.
- FINDS (search finds, chest contents, monster drops) lie in the room (room.items, shown in Here) to take one by one or
  all at once, or leave. Gold, small keys and bombs are counted straight away.
- NPC LINES: a dialogue data file (e.g. src/ptg/data/dialogue.toml) with lines for each character and quest stage,
  written in the spirit of the kids' descriptions (silly is good; it's for kids). Shown as speech cards when you meet
  them. A Maker "lines" field comes later (note it in docs/plans/ideas.md, don't build it).
- CURSES: cursed things are sticky once taken; praying at a shrine lifts the curse; taking one warns you first (so
  you can leave it).
- SELLING: yes, at half the shop price; both grannies buy anything except quest items and the boss key.
- OFF-GRID TYPED INTERACTIONS (not in the interaction grid): the model's creative attempt still resolves with a roll,
  but nothing is used up and no Fate is paid unless something actually changed.
- KIDS' ART: touch up the weak kid-made sprites (add a dark outline, tidy colours toward the Endesga palette, pull
  limbs in from the frame edge) while keeping each design recognisably theirs; add missing small (12x12) versions.
  Fix and regenerate the game's own art freely (stairs, chest, shrine, tombstone, crown, props).
- Lenny's bad tooth is always hidden on Lenny's own floor (you can't go back up a floor).
- Killing a monster you already pacified pays no reward.
- Weapon and armor powers and stats work only while equipped (trinkets work from the pack).
- No pack limit.
