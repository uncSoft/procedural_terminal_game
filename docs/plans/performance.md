# Performance: what makes play stutter, and the fixes

Written 2026-10-28 after the owner played all four floors and found animations and sounds stuttering and competing
with each other. This is the analysis; the fixes are at the end, in the order they pay.

## How it was measured

A scratch harness ran the real game screen (the Grid, 160×48, headless, the offline narrator) with the real sound
mixer feeding a stand-in sound device that plays in real time, so a starved mixer would show as gaps. It played a
script: three new rooms, a room already seen, a fight walked into, two turns of it, the kill, the Goblin King's
entrance (his clip and name card), a turn with him, his death, a quick travel and the stairs down. Throughout, it
logged every stall of the screen's event loop longer than 34 ms (two frames: while it lasts, nothing animates and no
key is read), sampled what the screen's thread was doing every 2 ms, timed each step of each turn, and counted gaps
in the sound. Then it ran again with each suspect fixed in memory, to see what each fix is worth.

| Run | Stalls | Stall time | Over 100 ms | Longest |
|---|---|---|---|---|
| As the game is | 57 | 4.5 s | 8 | 269 ms |
| Music prepared with `audioop` (fix 1) | 58 | 3.7 s | 5 | 123 ms |
| Fix 1, and pixel art drawn in runs (fix 2) | 31 | 1.7 s | 0 | 89 ms |

The sound itself never ran dry in any run: the mixer takes about 0.1 ms to mix each 10.7 ms block. What you hear as
sounds stuttering is the screen's thread falling behind: sounds and pictures that should land together don't, and
the music starting late.

## What blocks, worst first

**1. The music is prepared in pure Python the first time each track plays.** Every track is resampled from 22,050
samples a second to the speakers' rate, a whole loop at once, sample by sample: the floor music 226-264 ms, the
battle music 141 ms, the boss music 150 ms, the title's 117 ms. It runs on a thread of its own, but Python runs one
thread at a time, and it starts at the worst moments: a fight starting, a boss arriving, a new floor. For that time
the screen gets half the interpreter at best, and anything it does that waits on the disk waits much longer: the
save at the end of the turn that starts a fight took 128 ms, against 7 ms with the music prepared in C. Python's own
`audioop.ratecv` does a track in 5 ms.

**2. Pixel art becomes one styled piece of text per terminal cell.** `sprites.image_text` gives each cell its own
style: a fight frame on a 110×16 stage is 1,760 pieces and 54 KB of terminal codes. Building it is 4 ms; Textual
laying it out and drawing it is most of the rest. A fight frame took 11-22 ms on average in play, 75 ms at worst,
and the kill drew all seven shatter frames at once (106 ms). Neighbouring cells of the same colours could be one
piece: 372 instead of 1,760, 4.7 times fewer. With that, frames take 4-6 ms, the shatter 27 ms, and a terminal or a
browser is sent about a quarter of the bytes. That matters most served: an entrance at 12 frames a second is about
650 KB a second of screen today, and the browser's sounds travel in the same stream as the screen, behind it.

**3. A fight's start and end happen in the wrong order.**
- *The start:* the whole entrance (about 0.6 s for a sweep, about 4 s for the King's clip and card) plays before the
  status bar, Here, the map and the buttons change, and before the battle music starts (refresh_panels and
  refresh_music come after `_encounter`). The screen shows the last room's state while the fight comes in, then
  everything changes at once, just as the battle music's preparation (1) begins.
- *The end:* the spoils card (about 3 s) plays before Here, the map and the buttons drop the foe and before the
  floor's music returns; then the floor music's first preparation runs under the narration.

**4. Room pictures are drawn on the screen's thread.** A room's picture takes 18-22 ms each time you walk in
(`room_picture.picture_text`; the first of a new floor, 108 ms), even into a room seen a moment ago. Then the second
frame of its idle animation is drawn on a worker thread (16-28 ms), right as the narration starts.

**5. Each sound is decoded the first time it plays, on the screen's thread** (0.5-12 ms each). The first fight of a
session plays a dozen of them.

**6. A floor's card decodes the floor's splash art (five PNGs) on the screen's thread** as the floor starts.

**7. Small, but in the way:** the Bestiary is read from the profile's database every time Lately is redrawn and every
time a turn's narration starts. On their own, the save and the profile's writes are 0.2 ms each and the narration's
re-colouring 0.1 ms: not problems, except while (1) runs.

**8. Not measured here: a narrator on the same computer.** With LM Studio, each turn asks the model twice (the
narration, then a suggested idea in the background), and the idea is asked for as soon as the turn ends, while the
next turn's animations play. Generation on the same machine takes CPU and GPU from the game just then.

## A turn, as it runs now

What `GameScreen._turn` does, in order, each step waiting for the one before:

1. The player's line in the story; `Game.begin` (the rules: about 1 ms).
2. The dice screen, if there's a roll (its tumble).
3. The roll lines, each event's sound, the damage and heart popups (`_roll_feedback`), the gold popups.
4. The foe's flash and lunge on Here and on the stage; a kill's shatter and spoils card (`_fight_animations`).
5. A fight starting: the entrance on the stage (`_encounter`).
6. A fixture's moment (a chest opening, the stairs dissolving), a new floor's header, a secret room's or a shop's
   banner.
7. **Only now** the status bar, the stage's picture, Here, the map and the buttons (`refresh_panels`), and the
   music (`refresh_music`).
8. The narration (`Game.finish`: the narrator, then the journal, the profile's writes and the save).
9. The story's extra lines and cards, toasts, `refresh_panels` again, a level-up.
10. The turn logged; the next idea asked for (`suggest_later`), in the background.

## The fixes, in the order they pay

1. **Music and sounds ready before they're needed.** Resample with `audioop.ratecv` (C, 5 ms a track) where Python
   has it (3.11 and 3.12, which the game and its Docker image use); fall back to today's way where it doesn't (3.13
   dropped it). And prepare every sound and every track in the background while the title shows, so play never
   waits on one.
2. **Pixel art drawn in runs.** `image_text` merges neighbouring cells of the same colours and reuses its styles; the
   shatter draws its frames as they're shown, as the entrance does.
3. **A fight's moments in the right order.** Update the status bar, Here, the map and the buttons before the entrance
   (they take about 5 ms), start the fight music on the landing cue, and bring the floor's music back as the spoils
   card comes up.
4. **Rooms drawn once.** Keep each room's picture until something in it changes, and draw its second idle frame once
   the turn has settled.
5. **Preload the next floor's splash art during the stairs**, and keep the Bestiary in memory, updated as the
   profile writes it.
6. **Ask a local narrator for the next idea later:** not in a fight, and only once the turn's animations are done.
7. **Keep the harness** as `tools/perf.py`, so a change can be measured the same way.

## Done (fixes 1-5, and the map)

Built the same day, measured with the same harness (the game as it is now, nothing patched in):

| | Before | After |
|---|---|---|
| Stalls over 34 ms | 57 | 24 |
| Stall time over the script | 4.5 s | 1.35 s |
| Stalls over 100 ms | 8 | 0 |
| Longest | 354 ms | 83 ms |
| Walking back into a room seen | 1-2 stalls | none |
| Down the stairs | 251 ms of stalls | 38 ms |

1. `sound.resample` uses `audioop.ratecv` where Python has it (every track in about 5 ms), and `Sound._open`
   prepares every sound and track (`Mixer.prepare`, music first) on its background thread as the game opens: all 79
   in about a tenth of a second, so a first play takes 0.01 ms.
2. `sprites.image_text` writes runs of cells alike as one piece (`_cell` works out each pair of pixels once): a fight's
   frame is 339 pieces, not 1,760, and takes 1-2 ms to make. `Fight.shatter` draws its frames as they're shown.
3. A fight starting brings the status bar, Here, the map and the buttons up to date before its entrance
   (`refresh_around_stage`), and its music comes in 0.8 s after the sting rather than after the whole entrance; at
   the kill, the floor's music and the status bar come back as the spoils card does, Here and the map just after.
4. `room_picture.picture_text` keeps the last 48 pictures (keyed on the room as it is, and the size): walking back in,
   the stage's second idle frame, and the room after a fight's wipe all come from them.
5. The run's floors' splash art and its bosses' and guardians' clips are read on a worker thread three seconds into
   a run (`GameScreen._preload`); `Profile.bestiary` is kept in memory until the bestiary changes.

**The map (F5) going unresponsive.** It wasn't drawing the map that was slow (12-21 ms) but what came after: the
parchment was one styled piece a cell (6,600 at 190×52) for the screen to lay out; it was drawn twice as it opened;
and every room the mouse crossed drew the whole map again, so a mouse over the map as it opened queued redraws for
seconds. Now the parchment is drawn in runs (1,825 pieces, 10 ms), once per size, each drawing kept while the map is
up, and a room is lit only once the mouse rests on it (60 ms): three sweeps of the mouse over every room cause no
redraw at all.

Still on the screen's thread: a new room's picture (about 20 ms, then kept), a fight's backdrop (about 20 ms at its
start), and Textual laying out what changed (most of what's left in the stalls). The harness is in the session's
scratch space; keeping it as `tools/perf.py` (fix 7) and asking a local narrator for ideas later (fix 6) are still
open.

**The small map taking clicks.** Three things made it feel as if it didn't:
- A move made mid-turn was dropped unless the narrator was talking. With a fight's entrance and spoils lasting
  seconds now, a click on the map, the compass or a big button in them was lost. Now the first move made mid-turn is
  made once the turn's done (`GameScreen.later`), and a big button's too.
- On a narrow side column the map falls back to the marks alone, and a room's three cells (`[#]`) were all that took
  a click. Now a room's place is four cells by two (the passage after it, the row under it); and on the box map, a
  door in a room's wall is that room's too.
- The map was drawn again only when its rooms changed, not when you could set off again (a fight's end in the same
  room, a perk picked, a scene over), so it could stay unclickable. And a room there's no way to did nothing at all
  when clicked; now it says why (`rules.no_way`: "You haven't been in there yet.", "Not in the middle of a fight.").

**The arrow keys stopping, the map with them.** Not an animation: a click outside the level-up's cards (on the map,
say, just after a kill) puts the pick off, and while the perks waited as the choices, an arrow or a room on the map
did nothing at all, with nothing to say why, until a perk was picked from the choices. Now either brings the cards
back, and the move is made once one's picked (`GameScreen.pick_perk`). Any other arrow that can't go says why
(`rules.no_go`: "There's no way west from here.", "Not with the Goblin in the way: fight it, or flee."); ↑ and ↓ go
even with words left in the command line; and a move made during the recap of a run picked up again is made, where
it used to be kept and never made, blocking every mid-turn move after it.
