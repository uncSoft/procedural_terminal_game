# Writing story events

Story events are the hand-written parts of the game: scripted moments, scenes with choices, magic words,
secrets. The game code watches for them and plays them out exactly as written. The AI narrator never
rewrites them, and they work with no AI at all.

This format is a starting point. If your writing wants a different shape, we'll change the format to fit
your writing, not the other way round.

## Where they live and how to test them

- One file per event, in `src/ptg/data/story/`, ending in `.md`.
- Check every story file for mistakes (each one names the file and line):

  ```bash
  uv run python -m ptg.story
  ```

- Jump straight into an event, ignoring its trigger and conditions:

  ```bash
  uv run ptg --event mirror_trial            # in the full game
  uv run ptg --plain --offline --event mirror_trial
  ```

The two shipped examples, `mirror_trial.md` and `old_word.md`, are placeholders to copy from and delete.

**Before you commit:** the game fingerprints its data files and notices when they've been edited. After
real changes, accept them so they count as the official version (a test fails until you do):

```bash
uv run python -m ptg.integrity --sign
```

## Anatomy of a file

```
---
id: mirror_trial
title: The Mirror Trial
when: enter_room
if: floor >= 2; first_visit; not in_combat; chance 25%
once: profile
voice: exact
secret: yes
hint: Not every fight is won by fighting.
---
A tall mirror stands where a wall should be. Your reflection draws
its weapon a heartbeat before you do, and waits.

* Attack your reflection (attack, fight, strike)
  -> Glass explodes outward. [hp -6] [flag mirror_broken]
* Lower your weapon (lower, sheathe, put down, yield)
  -> It hesitates, then bows. [goto bow]
* (anything else)
  -> It copies you exactly. A little too exactly. [hp -2]

## bow
The glass clouds over...

* Step through (step, enter)
  -> Warmth. Light. [heal] [fate +1] [secret]
```

### The header (between the `---` lines)

| Key | Meaning |
| --- | --- |
| `id` | A unique name: lowercase letters, numbers and `_`. |
| `title` | Shown on the story card and in the Book of Secrets. |
| `when` | What sets it off (see Triggers). Required. |
| `if` | Conditions, separated by `;` (see Conditions). Optional. |
| `once` | `run` (default: at most once per descent), `profile` (once ever), or `always`. |
| `voice` | `exact` (default): your words, shown as written on a story card. `narrated`: your words become facts the AI narrator retells in its own voice. `silent`: effects only, no text. |
| `secret` | `yes` puts it in the Book of Secrets. It only counts as found when a `[secret]` effect fires. |
| `hint` | What the Book of Secrets shows before it's found. |

Lines starting with `#` in the header are notes to yourself and are ignored.

### The body

- **Text** at the top is shown when the event fires. Blank lines separate paragraphs.
- **Choices** start with `* `. Words in brackets at the end are keywords: if the player types something
  containing one of them, that's the choice they meant. `* (anything else)` catches everything else.
- **Outcomes** start with `-> ` under a choice. Indent the next lines to keep going.
- **Parts:** `## name` starts another part of the scene; send the player there with `[goto name]`.
- **A scene ends** when an outcome doesn't `[goto]` anywhere, or a part has no choices.
- An event with no choices is a one-off **moment**: its text shows, its effects apply, done.

### How players answer a scene

Players can type a number, click a choice, or write anything. Typed text is matched against your keywords
first; then the AI picks the closest choice if one is running; then the catch-all applies. If there's no
catch-all, the narrator reacts and the scene stays open. Questions ("what is this mirror?") are answered
without leaving the scene.

## Triggers (`when:`)

| Trigger | Fires when |
| --- | --- |
| `enter_room` | The player walks into a room (including arriving on a new floor). |
| `say xyzzy \| open sesame` | The player types one of these words or phrases. Checked before the AI sees the input, and it doesn't use up a turn. |
| `roll nat20` / `roll nat1` | The player rolls a natural 20 / natural 1. |
| `defeat` | A monster is killed. Use `if: monster troll` to pick which. |
| `pacify` | A monster is talked down or distracted. |
| `run_start` | A new descent begins. |
| `turn` | Every turn. Pair it with conditions to watch for a situation (`hp <= 3`, `turn >= 100`). |

## Conditions (`if:`)

Separate with `;`. Put `not ` in front of any of them to flip it.

| Condition | True when |
| --- | --- |
| `floor >= 2` | Compare `floor`, `level`, `hp`, `gold`, `fate`, `souls`, `turn` (this run), or `runs`, `deaths`, `wins` (ever). Use `>=`, `<=`, `>`, `<`, `=`. |
| `chance 25%` | A seeded roll: the same seed always gives the same answer, so daily runs share events. |
| `first_visit` | The player is entering this room for the first time. |
| `in_combat` | A fight is going on. (Scenes never start mid-fight.) |
| `theme sunken_crypt` | The current floor's theme. |
| `room ossuary` | The room type (an archetype key from `rooms.toml`). |
| `fixture shrine` | The room has this fixture (`shrine`, `chest`, `fountain`, `stairs`). |
| `monster troll` | That monster is here (or was just defeated/pacified). |
| `has oil_flask` | The player carries or wears this item. |
| `flag name` | A flag set earlier this run with `[flag name]`. |
| `mark name` | A mark set on any earlier run with `[mark name]`. Marks survive death. |
| `seen` / `seen other_id` | This event (or another one) has ever fired. |
| `tampered` | The game's own data files have been edited since they were signed (this run is "modded"). |

## Effects (in square brackets)

Put them anywhere in text or outcomes; they're removed from what the player reads, and shown as a short
line under the card instead (`◆ -6 HP · +1 Fate`).

| Effect | Does |
| --- | --- |
| `[hp -6]`, `[hp +5]` | Change HP. Story damage never kills: it stops at 1. |
| `[heal]` | Restore all HP. |
| `[gold +10]`, `[souls 15]`, `[fate +1]`, `[xp 20]` | Change gold, souls, Fate or XP (XP can level you up). |
| `[give healing_potion]`, `[take oil_flask]` | Give or take an item (keys from `items.toml`). |
| `[perk iron_skin]` | Grant a perk (keys from `perks.toml`). |
| `[spawn goblin]` | A monster appears and a fight starts (keys from `monsters.toml`). Ends the scene. |
| `[flag name]`, `[unflag name]` | Set or clear a flag for this run. |
| `[mark name]` | Set a mark that lasts across runs, for stories that continue after death. |
| `[secret]`, `[secret other_id]` | Record this event (or another) in the Book of Secrets. |
| `[goto part]`, `[end]` | Jump to another part of the scene, or end it. |

## Tips

- Keep keywords short and specific. "put down" is better than "down".
- Give big scenes a catch-all, so whatever the player tries, something written by you happens.
- Use `mark` for anything a later run should remember, and `flag` for this run only.
- Short names for callbacks are fine; long quotes from other works are not. Borrow ideas and moods, not
  words, names or characters.
