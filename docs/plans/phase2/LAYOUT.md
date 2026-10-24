# Phase 2: the new game screen (W11, with W10's story-flow fixes) and the panel actions (W13)

Built in the integration worktree, where every track is merged: the engine (W1 rules, W5 items/equip/sell/curses,
W6 the interaction grid, W8 character quests and dialogue, W7 the interpreter, W9 narration), the interface (W2 art
pipeline, W4 room pictures, W3 the Picture widget, W12 panels that keep their size) and art/phones (W14 kids' sprite
touch-ups, W15 the phone page and config.touch()).

THE APPROVED DESIGN is the spike `docs/plans/phase2/layout_spike.py` (read it all,
and run it: `cd /Users/johnt/Developer/procedural_terminal_game && uv run python docs/plans/phase2/layout_spike.py`, keys 1-4).
Owner-approved points, all of which must hold in the real game:
- A fixed stage at the top of the left column with the room's picture (room_picture.picture_text), shaped like a room
  (about 2.4:1), hidden when the screen is too short; the story under it is TEXT ONLY (player lines, narration,
  mechanics, dice lines, speech cards, quest banners) — no pictures, loot cards or sprites inline any more.
- A Here panel (right column on wide screens; a strip under the stage on narrow ones) listing the room's characters
  first, then the shop's keeper and wares, then items lying here, then the fixture and searchable features, as tiles:
  card (24-px picture, animated), mini card (12 px), row (12 px beside the words) or chip (words only), each group in
  the biggest form that fits, "+N more ▸" when even chips overflow. Each tile: name (★ badge for a quest-giver), how
  it is (HP bar and "⚠ big hit next!" for a foe; "wants his bad tooth back" for Lenny; "▲ better than your Rusty
  Sword" for gear; "cursed! sticks to you"; a ware's price, greyed "need 12¤" if you can't afford it), and its verbs
  as buttons coloured by meaning (Attack red; Talk/Give green; Take/Equip/Buy amber; the rest blue).
- Tile verbs are NUMBERED FIRST (1, 2, 3... in Here's order), and the choices strip continues the numbering, so
  typing a number does what clicking does. Actions on one thing live only on its tile; the choices strip keeps the
  rest (exits, room searches, fight tactics like dodge/flee/bomb, take-all, level-up perks, Swoogy's guesses...).
- The choices are a compact strip of chips under the story, 1-3 lines, only as tall as needed, side by side when
  wide, "▼ N more" paging when they overflow. No fixed-height choices box.
- Side column (two-column layouts): Here, then the floor map (only when there's room), then the arrow pad.
- One column below 88 columns (with hysteresis), or a wide-short landscape screen keeps two columns: stage, Here
  strip, story, a ways bar (◀ W ▲ N ▼ S ▶ E) above the choices, no arrow pad.
- The story keeps at least 8 rows always, 12 whenever the stage shows; the stage gets what's left; nothing shrinks
  as the window grows except at the one moment the stage appears; ±2 hysteresis on every switch; resize debounced.
- Small screens (one column, or under 30 rows): no footer, 1-row command line, a short status bar
  "♥30/30 ⛨12 ✦1 ¤27 Lv1 F1/3" with a ☰ menu (Bag, Map, Quests/Journal, Help, Settings).
- Touch mode (config.touch(), from the served page): verbs and ways buttons 3 rows tall, solid colour blocks.
- Characters are always in colour (W3 made sprites.posed("calm") a no-op).

APIS FROM THE TRACKS (read their docstrings in the integration worktree):
- W3 `ptg.ui.widgets.Picture(key, kind="", max_w=24, max_h=None, pose="idle", animate=True, action=None, *,
  content=None, loop=None, flicker=False, ascii=None, style=..., sprites=None)`: draws an item/monster/fixture
  the same way everywhere (24 px if it fits, else the 12-px small or halved, else grey stand-in, else ASCII), never
  wraps, fixed height, shared PictureClock; `.play(steps, delay)`, `.freeze()`, `.resume()`, `.become()`, `.fit()`,
  `.set_pose()`; pure `art_for(...)` sizes it before mounting.
- W6 `ptg.scene.RoomView(state, content)`: `.things()` (refs in the room, characters first), `.carried()`; each Ref
  has `.id, .kind, .name, .sprite, .state`. `ptg.interactions.verbs(state, content, ref_id)` -> the tile's Actions
  (only ones that would do something); `interactions.is_picker(id)` + `interactions.choices(state, content, id)` for
  "Give…" / "Use on…" pickers (working options first, refused ones hinted "NO"); `use_id(verb, subject, target,
  amount)`, `parse()`. Send any id through the game's normal turn (game.begin(label, Action(id, label))).
- W8: character lines arrive as story events (kind "story", voice "exact", title = speaker, sprite = character key)
  and possibly a quest-stage event — read W8's report/code for the exact shape; render them as speech cards (a left
  accent bar, the speaker's name in bold as the first line, the quote in italics) and quest starts/ends as banners.
- W12: `PTGApp.HORIZONTAL_BREAKPOINTS` (-narrow/-wide at 88 columns) and `VERTICAL_BREAKPOINTS` (-tiny/-short/-tall
  at 28/34 rows) put size classes on every screen; panels keep their size; F1-F7 inside panels; toasts top-right.
- W15: `config.touch()`.

LOOSE ENDS THE TRACKS LEFT FOR THIS PHASE (from their reports):
- W7: clicks must send the ACTION itself (its id), not "the nth choice": with tile verbs numbered first, Swoogy's
  guesses would no longer be choices 1-6. `interpreter.guessed(...)` already makes a bare 1-6 the guess while he's
  guessing. `interpreter.looks(raw)` says a typed "look around" should open the Look panel: route it there.
- W8: `TERM_STYLES` needs "character": "bold #ffd166" (characters are plain white in the story until then);
  `MAP_STYLES` and the map legend need ☺ (a quest-giver waiting); the journal should list open quests
  (`npcs.quest_log`); item cards should say who wants an item (`npcs.wanted_by`); the shop counter greets with
  `npcs.line(...)`; story cards (now speech cards) should come in the right order relative to the narration.
  Speech events: Event("story", text, data={"voice": "exact", "title": name, "sprite": key, "speaker": key,
  "moment": moment, "met": key on a first meeting}); LogEntry(kind="card", speaker=key) in the log.
- W6: the per-item numbered choices (Eat/Drink, Throw, Distract for each item) still exist because today's inventory
  panel finds its Enter action among the choices; W13 replaces them with the pickers ("Use an item…", "Give…") and
  makes the panels run engine actions directly. Exchanges carry {item, how, from, to} (gold: {gold, how, from:
  "purse", to}): show them as compact "given to / a gift from" lines.
- W3: monsters and characters have no hand-made 12-px smalls, so their halved portraits look rough at 12 px; prefer
  24 px for characters in Here wherever it fits (the group rule already gives characters the room first).
