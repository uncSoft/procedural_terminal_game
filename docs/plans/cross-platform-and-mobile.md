# ptg on Windows, Linux and phones: feasibility and plan

Analysis only: no game code was changed. Written 23 Oct 2026 against the `v2` working tree (Textual 8.2.8,
Python 3.12), with a live browser experiment and a few measurements (see "What I checked"). Screenshots from
the experiment are in `portability-screens/` next to this file.

## Bottom line

- **Desktop (macOS, Windows, Linux) is about 95% there already.** The game is pure Python on Textual with no
  platform-only code in its core. Data loads through `importlib.resources`, every text read and write names
  UTF-8, the profile is stdlib SQLite, and sound already falls back from PortAudio to `afplay`, `pw-play`,
  `paplay`, `aplay` or `winsound`. A wheel built from the tree is `py3-none-any` (938 KB) and carries every
  sprite, sound, data and story file. Three things are missing:
  - **One confirmed Windows bug:** CRLF line endings make all the shipped data look edited.
  - **No testing off macOS:** the tests have never run on Windows or Linux.
  - **No install instructions** for players.

  **About 1-2 days.**
- **Phones (iOS, Android) work without a rewrite, by serving the Textual UI to the phone's browser** with
  Textual's official `textual-serve`. I ran the game that way unchanged:
  - **At desktop size, everything worked:** clicks, typing, the footer as tap targets, sprites and the d20.
  - **At phone size it ran but isn't playable yet,** for two fixable reasons. textual-serve's page has no
    mobile viewport tag, and the game's layout assumes 80+ columns.
  - **Narrator, saves and profile stay on the Mac.** Your LM Studio keeps working as it is.
  - **Sound needs a small bridge** to play on the phone.

  **About 1.5-2 weeks** for a good phone experience for you, **plus about a week** to host it safely for friends.
- **Python in the browser (Pyodide/WebAssembly)** would give an offline, server-free version on GitHub Pages, but
  it isn't the first step:
  - Its only Textual driver is textual-wasm, a one-month-old alpha with one maintainer.
  - Pyodide has no threads, and the sound mixer uses them.
  - LM Studio is effectively out of reach from a phone page.
  - Phone performance is unmeasured.

  **Worth a spike later.**
- **Skip these two.** A native GUI rewrite redoes about 4,300 lines of UI and the half-block pixel art for no
  gain. Textualize's textual-web relay is dead: no commits since August 2024, and its domain no longer resolves.
- **The phone narrator will be the phone's own model** (decided after this analysis; see section 4): Apple's
  Foundation Models on iPhone and Gemini Nano on Android. The game's per-turn prompts already fit their small
  context. Those models are reachable only from native code, so the phone version ends up as an app that runs
  the game on the phone.

**Recommendation:** do the desktop hardening (Phase 1). Then build the served phone version and run it on your
Mac behind Tailscale (Phase 2). Then add hosting for friends (Phase 3). Later, for on-device narration, run the
game on the phone inside an app (Phases 4 and 5). The narrow layout built in Phase 2 is reused by every later
phone build, so nothing on this path is wasted.

## What I checked

- **Code:** read the portability-relevant parts: `ui/`, `app.tcss`, `sound.py`, `llm/`, `config.py`,
  `profile.py`, `integrity.py`, `sprites.py`, `dice_art.py`, `cli.py`, `library.py` and `pyproject.toml`.
- **Browser experiment:** served the game with textual-serve 1.1.3 (the latest, from Nov 2025), using the offline
  narrator, sound off and a scratch `PTG_HOME` (your `~/.ptg` was not touched). I played it at desktop size, at
  an emulated phone size (375x812, portrait) and in landscape (812x375).
- **Windows line endings:** simulated a CRLF checkout against the data fingerprints.
- **Packaging:** built the wheel into a scratch folder and ran it from an isolated install.
- **Measurements:** one served session's memory, and the cost of the pixel-art code.
- **Claude cost:** estimated per run from `llm.log` request sizes and the profile's turn counts, both read-only.
- **External projects:** checked the current state of textual-web, textual-serve, textual-wasm, Pyodide's
  package list and Briefcase's console-app support.

Not checked: a real iPhone or Android device (the phone results are Chrome's mobile emulation), a real Windows or
Linux machine, and PyInstaller builds.

## 1. Desktop: macOS, Windows, Linux

### Already works everywhere

| Area | Why it's portable | Where |
| --- | --- | --- |
| UI | Textual 8 runs in macOS, Linux and Windows terminals; the pixel art is plain half-block text, no image protocol | `sprites.py`, `dice_art.py` |
| Data and assets | Loaded with `importlib.resources`: works from a checkout, an installed wheel or a frozen app | `content.py:122`, `sprites.py:50`, `sound.py:120`, `story/parser.py:311` |
| Text encoding | Every read and write names UTF-8, so Windows' cp1252 default never applies | `config.py`, `content.py`, `integrity.py:59`, `llm/base.py:85` |
| Settings, saves, profile | `~/.ptg` via `Path.home()` (on Windows, `C:\Users\<you>\.ptg`), `PTG_HOME` overrides it; SQLite and `tomllib` are stdlib | `config.py:33`, `profile.py` |
| Sound | sounddevice's wheels bundle PortAudio on macOS and Windows; otherwise a system player; never crashes or stalls | `sound.py:308-341` |
| Platform branches | The debug screen's "open folder" already handles Windows, macOS and Linux | `ui/debug.py:134-138` |
| Narrator | Plain HTTP (httpx, Anthropic SDK) | `llm/` |
| Packaging | `uv build` gives a pure-Python wheel with every sprite, the 39 sounds, the data, the story files and the `.tcss`; it runs from an isolated `uv tool run` | `pyproject.toml` |

### What bites

1. **Windows line endings make the shipped data look edited (confirmed).** `integrity.py:34` hashes raw bytes.
   Git for Windows' default (`core.autocrlf=true`, also the setting on GitHub's Windows runners) checks text files
   out with CRLF. In a simulated CRLF checkout, all 12 fingerprinted files read as "changed", with these effects:
   - Every run is marked modded (`meta.py:63`). That shows in the Hall of Legends and on the share card.
   - The Hackerman secret unlocks on the first descent (`story/hackerman.md`: `when: run_start`, `if: tampered`).
   - `test_shipped_data_is_signed` fails.
   - `ptg import` run on Windows writes CRLF (`library.py:414`, text-mode `write_text`) and signs it, so a Mac
     checkout then sees the data as edited.

   Fix: hash with `\r\n` normalised to `\n`, and add a `.gitattributes` that keeps `src/ptg/data` text files LF
   and PNG/WAV files binary.
2. **Never tested off macOS.** There's no CI. The suite already runs headless (Textual's `run_test`, with
   `PTG_HOME` and `PTG_SOUND=0` set in `conftest.py`). A GitHub Actions matrix on `macos-latest`,
   `windows-latest` and `ubuntu-latest` is the cheapest way to make "cross-platform" true and keep it true. Expect
   the first Windows run to turn up a few small things.
3. **Linux sound** needs the PortAudio system library (`libportaudio2` on Debian/Ubuntu) for the low-latency
   mixer. Without it the system-player fallback works, but starts slower, and `aplay` can't set the volume.
4. **Function keys.**
   - GNOME Terminal takes F1 (its help) and F11 (full screen). Windows Terminal takes F11. Mac keyboards need fn.
   - None of this blocks play: every panel has a typed command (`i`, `c`, `l`, `m`, `b`, `j`, `help`), and the
     footer is clickable.
   - F8 (sound) has no typed equivalent; a `sound` command would close that gap.
5. **`--plain` mode on Windows** prints emoji and box-drawing characters. That's fine in a console, but output
   redirected to a file or pipe uses cp1252 and raises `UnicodeEncodeError`. One
   `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` in `cli.py` fixes it.
6. **Colour.** The sprites need 24-bit colour. On 256-colour terminals Textual downsamples, so the art degrades
   rather than breaks. Recommend Windows Terminal (the default on Windows 11) and any modern macOS or Linux
   terminal.

### Ways to ship it to desktop players

| Option | What players do | Effort | Code kept | Notes |
| --- | --- | --- | --- | --- |
| **`uv tool install` from GitHub** | Install uv (one line), run `uv tool install git+https://github.com/uncSoft/procedural_terminal_game@v2`, then `ptg` | Docs only | 100% | Wheel verified. Needs a terminal. **Do this first.** |
| Publish to PyPI | `uvx <name>` | Half a day | 100% | Needs a free name on PyPI. |
| PyInstaller per OS, built in CI | Download a zip, run `ptg` in a terminal | 2-4 days | 100% | Expect some tuning of hidden imports and data files. Unsigned builds get SmartScreen/Gatekeeper warnings; Apple's signing program is $99/yr. |
| Briefcase console app | Run a `.pkg`, `.msi` or Linux package | 2-4 days | 100% | Briefcase supports console apps on macOS, Windows and Linux (not iOS, Android or web). |
| The game in its own window (after Phase 2) | Double-click an app; no terminal | 2-3 days on top of Phase 2 | 100% | A small launcher shows the served page in a native web view (pywebview). Sound plays locally, with no bridge needed. Best for non-technical friends on desktop. |

## 2. Phones: iOS and Android

A Textual app needs a terminal, and phones don't give apps one. Briefcase's console mode doesn't target iOS or
Android either, so "package the terminal app" isn't available. The real choices are where the Python runs and
what draws the terminal.

### The options

| Option | Python runs on | Phone shows | Code kept | Effort | Verdict |
| --- | --- | --- | --- | --- | --- |
| A. SSH from a phone terminal app (Blink or Termius on iOS, Termius or Termux on Android) | Your Mac | The terminal app | 100% | None | Works today for you; not something to hand friends. No sound on the phone. |
| **B. Serve the UI to the browser (textual-serve)** | Your Mac, or a small server | xterm.js in the browser | 100%, plus roughly 600-900 new lines | 1.5-2 weeks | **Recommended.** Tested below. |
| C. Python in the browser (Pyodide, via textual-wasm or your own driver) | The phone | xterm.js, all client-side | About 95% | 2-4+ weeks, uncertain | A later spike, for offline and server-free play. |
| D. Home-screen web app (PWA) around B or C | - | Full screen with an app icon | - | 1-2 days | Fold into Phase 2. |
| E. Native app shell (Capacitor, or a WKWebView/WebView app) around B or C | - | An App Store or Play app | - | 1-2 weeks on top | Only if a store listing matters. Thin web wrappers can fail App Store review, and there are store fees. |
| F. Textualize's textual-web relay | - | - | - | - | **Don't.** Last commit Aug 2024, still "beta", and its relay domain (`textual-web.io`) no longer resolves. Textualize wound down as a company in 2025; Textual itself continues as open source (last release June 2026). |

### B in practice: what I saw

**At desktop size, unchanged, everything worked.** That covered the title, campfire, intro and game screen,
clicking choices, typing commands, tapping the footer (F2 opened the inventory), story highlights, combat, and
the d20 rolling on a click.
- **Sprites:** xterm.js draws the block characters itself, so the sprites are crisp, with no gaps between rows
  (screenshot 1).
- **Resources:** each browser tab is its own `ptg` process, using about 83 MB of memory and about 0.2% CPU at
  rest, plus about 50 MB for the server.

**On a phone, three things stand in the way:**

1. **The page isn't mobile-ready.**
   - **The problem:** textual-serve's page template has no `<meta name="viewport">`, so phones lay it out as a
     980-pixel desktop page. In the emulated 375-pixel phone, the game was given about 102x110 cells and showed
     a cropped corner (screenshot 2).
   - **Tested fix:** a one-line change to the template (textual-serve accepts a `templates_path`) plus
     `?fontsize=12`. The game then got about 52x55 cells and filled the screen.
2. **The layout assumes 80+ columns.** At 52 columns:
   - The sidebar keeps its fixed 31 columns and leaves the story about 17 (screenshot 3).
   - The dice box is 76 columns wide. The die shows, but the box and the verdict run off the right edge
     (screenshot 4). An advantage roll's two dice need 68 columns, which would push the second die off screen.
   - Campfire names are cut to "Vigo" and "Fortu", "Daily" is clipped (screenshot 5), and so is the compact title.
   - The footer fits only F1-F4.

   Landscape (about 112x25) fits the full layout across, but shows only about 5 lines of story and has no room for
   the 30-row dice box (screenshot 6).

   Textual 8 has the tool for this: `HORIZONTAL_BREAKPOINTS` and `VERTICAL_BREAKPOINTS` on the App set a class
   such as `-narrow` by screen size. The game already adapts in two places: the map hides under 38 rows
   (`game_screen.py:117`), and the title goes compact under 96x48 (`screens.py:42`). The 12x12 small sprites
   (`sprites.SMALL`, in progress when this was written) are what a phone layout needs for monster cards and
   item tiles.
3. **Touch input:**
   - **Taps work as clicks:** choices, the d20, panels and highlighted words all work.
   - **Hover tooltips** on highlighted words (`widgets.py:51-62`) don't exist on touch. Show the hint on the first
     tap instead.
   - **Typing works,** but the soft keyboard covers half the screen. In the narrow layout, keep tapping choices as
     the main way to play.

Not yet known: how iOS Safari's keyboard and text input behave with xterm.js, and how play feels on cellular.
Each keypress is a round trip to the host, which is fine on Wi-Fi or a tailnet.

**Narrator, sound and saves under B:**

- **Narrator:** runs on the host. When the host is your Mac, LM Studio at `localhost:1234` keeps working with no
  change. On a cloud host you'd use Claude or the offline narrator.
- **Sound:** today it plays on the *host's* speakers. Textual's web driver can only send links and file downloads
  to the browser, and textual-serve drops any other message type ("Unknown meta type"). The fix is small, in
  three parts:
  - **Game side:** a web player in `sound.py`, used when `app.is_web`, which sends a custom message through the
    driver.
  - **Server side:** a roughly 20-line subclass of textual-serve's `AppService` that forwards the message.
  - **Page side:** about 30 lines of JavaScript in the page template that play the WAVs (450 KB in all) with Web
    Audio.

  iOS needs a first tap to unlock audio, and the silent switch may mute it.

  **Built on 2026-10-28** along these lines: `sound.Browser` (the game runs with `PTG_SOUND=web`), `on_meta` in
  `serve.py`'s `PlayerService`, and the page's last script. The sounds had grown to 7.9 MB by then, so the page
  loads the short ones in the background and each piece of music when it's first wanted.
- **Saves and profile:** stay in `PTG_HOME` on the host. They're durable, backed up with the Mac, and the same
  profile you play in the terminal. Phones drop background connections, which ends the session ("Session ended
  -> Restart"). The game autosaves every turn, so serving it with `--continue` resumes where you were.
- **Security once anyone else can reach it:**
  - textual-serve has no login, so anyone who can open the URL starts a process.
  - All tabs share one `PTG_HOME`, so everybody gets one profile and one autosave.
  - Settings lets a player set the narrator URL and API key (`screens.py:96-104`), and detecting models makes the
    server fetch that URL (`openai_compat.py:38`).
  - The F12 debug screen shows `llm.log` (other players' turns), file paths and state, and can make LM Studio
    load other models.

  For you alone, keep it on Tailscale. For friends, see Phase 3.

### C (Pyodide) in more detail

- **Possible in principle.** Pyodide's current release (CPython 3.14) ships pydantic and pydantic_core, Pillow,
  httpx, rich and platformdirs. Textual installs from PyPI, `sqlite3` is in the distribution, and IndexedDB can
  back a persistent filesystem.
- **No official driver.** textual-wasm (MIT; created Sept 2026; v0.2.1; alpha; one maintainer) runs unmodified
  Textual through the `TEXTUAL_DRIVER` hook, with a Web Worker mode and storage helpers. It lists mobile as
  untested and warns that iOS has a tighter WebAssembly memory limit.
- **What the game would have to change:**
  - **No threads in Pyodide.** That affects the sound mixer and device opener (`sound.py:232` and `:363`) and
    the debug screen's thread worker (`ui/debug.py:563`).
  - **Sound** goes through Web Audio.
  - **No subprocesses.** The folder opener and `ptg import`'s git/gh calls stay out of a web build.
  - **Saves** need an explicit flush to IndexedDB after each turn.
  - **The narrator's HTTP** goes through the browser's fetch, so CORS applies.
  - **`pillow>=13`** has to relax to Pyodide's Pillow 12.2.
- **Narrator:**
  - **Claude:** called straight from the browser with the player's own key. The API allows browser calls when the
    request sets `anthropic-dangerous-direct-browser-access: true`. That's fine for bring-your-own-key, never for
    a shared key.
  - **Offline:** the offline narrator works as it is.
  - **LM Studio:** effectively out of reach. Browsers block, or ask about, an HTTPS page calling `http://` on a
    home network, unless you put HTTPS and CORS in front of it.
  - **The phone's own model:** only from inside an app; see section 4.
- **Saves:** live in the phone browser's IndexedDB. Browsers can clear site storage (Safari is the strictest), so
  add export and import.
- **Cost to players:**
  - **Download:** a first visit fetches about 10 MB of interpreter plus packages, cached after that, and boot
    takes seconds on a phone.
  - **Drawing:** the game's own drawing is cheap natively (a sprite pose about 0.6 ms, a d20 about 1 ms, imports
    about 130 ms), so even 10x slower is fine.
  - **Unmeasured:** Textual's renderer on a phone is the real unknown.

### The narrator on a phone, and what Claude would cost

Until the on-device backend in section 4 exists, the narrator runs here:
- **Under B:** on the host. That's LM Studio on your Mac (free, but the Mac must be on), Claude, or offline.
- **Under C:** Claude with the player's own key, or offline.

**If you host for friends with Claude:**
- **Requests:** `llm.log` shows a median narration request of about 2,700 characters (about 0.75k tokens) that
  returns about 350 characters. An interpreter or suggestion request of about 1,900 characters comes on about
  40% of turns.
- **Turns:** the finished runs in the profile took up to about 100 turns.
- **Tokens:** that's roughly 0.1M input and 10-50k output tokens per run. Thinking tokens are the unknown.
- **Cost at current list prices:**
  - Claude Opus 5.5 (the game's default): about $0.60-1.40 a run.
  - Sonnet 5.5: about half that.
  - Haiku 5.5: 2-4 cents.

Whether the smaller models narrate well enough is a question for the in-game model check (F12 -> Models).

## 3. Recommendation and phased plan

| Phase | What | Effort | Gets you |
| --- | --- | --- | --- |
| 0 | Nothing to build | - | Rough play from your phone today |
| 1 | Desktop hardening | 1-2 days | A tested game on all three desktop OSes, installed with one command |
| 2 | Phone-ready served build | 1.5-2 weeks | Good phone and tablet play for you, with LM Studio, sound and your profile |
| 3 | Hosting for friends | About a week | Friends playing from their phones, each with their own profile |
| 4 | Python on the phone: a spike, then the full build | 2-3 day spike; then 2-4+ weeks | Offline, server-free play, and the base for on-device narration |
| 5 (future) | Phone app with an on-device narrator (section 4) | 3-5 days per platform, on top of Phase 4 and an app shell | Free, offline, private narration on recent phones |

**Phase 0: today, no code (you only).** There are two ways.

- **SSH:** connect to the Mac from a phone terminal app over Tailscale and run `uv run ptg`.
- **textual-serve:** run it on the Mac and open the page on the phone. Set `public_url` to an address the phone
  can reach, because the page builds its websocket address from it and the default `localhost` fails. This
  listens on every interface with no login, so only do it on a network you trust:

  ```bash
  uv run --with textual-serve python -c "from textual_serve.server import Server; Server('uv run ptg --continue', host='0.0.0.0', port=8000, public_url='http://YOUR-MAC.local:8000').serve()"
  ```

  Until Phase 2's page fix, phones show a zoomed-out desktop page, so landscape or a tablet works best.

**Phase 1: desktop hardening (1-2 days).**
- Make the fingerprints ignore line endings (`integrity.py:34`) and add a `.gitattributes` for `src/ptg/data`.
- Add a GitHub Actions test matrix on macOS, Windows and Ubuntu, and fix whatever the first Windows run finds.
- Write player install docs: uv, `uv tool install git+https://github.com/uncSoft/procedural_terminal_game@v2`,
  Windows Terminal, and `libportaudio2` on Linux.
- Small extras: UTF-8 stdout for `--plain`, and a typed `sound` command.
- Later, only if non-developers need it: signed PyInstaller or Briefcase builds from CI.

**Phase 2: phones and tablets through the browser (1.5-2 weeks).**
- **`ptg serve`** in `cli.py`, as an optional extra (`ptg[web]`) wrapping textual-serve. It takes the host, port,
  public URL and `--continue`, and has its own page template with:
  - the viewport tag;
  - a font size picked from the screen width;
  - a web app manifest and icons for Add to Home Screen;
  - a dark theme colour.
- **A narrow layout** using Textual's breakpoints:
  - the story full width, with the scene and map behind a tap;
  - the dice box at `max-width: 100%`, with a smaller d20 or stacked dice (`dice_art.SIZE` is 31 today; two dice
    need 68 columns);
  - one-column campfire and inventory;
  - small sprites on cards and tiles;
  - panel shortcuts as a tappable bar;
  - tap-for-hint instead of hover.
- **The sound bridge** described above.
- **Real-device testing** on an iPhone (Safari) and an Android phone (Chrome): keyboard, rotation, safe areas and
  audio unlock.
- **Hosting:** run it on the Mac and reach it over Tailscale, which keeps it private and gives HTTPS through
  Tailscale Serve. Tablets work as soon as the page fix is in, because their grids are desktop-sized.

**Phase 3: friends (about a week).** *Started 23 Oct 2026:* `ptg serve` (README, "Play it in a browser") has a
page that asks who's playing with a folder for each name, an optional password, the hosted mode and a cap, on
Render.
- **Who's who:** Tailscale sharing, Cloudflare Access or a per-player link, mapped to a `PTG_HOME` per player.
  textual-serve starts every session with the same command and environment, so this needs a small subclass.
- **A hosted mode:**
  - no narrator URL or API key in Settings;
  - no F12 debug screen and no folder opener;
  - a cap on sessions.
- **A narrator choice:**
  - your LM Studio over the tailnet (free, but the Mac must be on);
  - Claude with a spend limit;
  - offline.
- **Optionally a small VPS** instead of the Mac. At about 80 MB a session, 1 GB serves roughly 8 players at once.

**Phase 4: Python on the phone.** Optional on its own, but it's the base the on-device narrator needs
(section 4).
- **When:** only after Phase 2 proves the phone layout.
- **Spike first:** 2-3 days on a real iPhone, measuring boot time, memory and animation, using textual-wasm or a
  small driver of your own modelled on it.
- **If it holds up, build:**
  - a Web Audio player;
  - IndexedDB saves, with export;
  - a fetch-based narrator (bring-your-own Claude key, or offline);
  - publication as a PWA next to the maker, for example at `docs/play/`.
- **Later:** a Capacitor wrapper for the app stores.

### Not recommended

- **A native GUI rewrite.** The engine would survive: about 7,400 lines of rules, world, story and narrator. But
  the 4,300 lines of UI and the half-block pixel art would be redone for every platform, for no player-visible gain
  over B.
- **textual-web.** Its relay is gone (see F).

An earlier draft listed on-device models here. That draft was thinking of models a web page downloads itself; the
OS-provided models in section 4 need no download and fit the game, so they're now the plan.

## 4. Future direction: on-device models on phones

Added 23 Oct 2026; not scheduled yet. The phone version should narrate with the phone's own model: Apple's
Foundation Models on iPhone, Gemini Nano on Android.

**What the platforms offer (checked Oct 2026):**

| | iPhone | Android |
| --- | --- | --- |
| API | Foundation Models framework (Swift), iOS 26+ | ML Kit GenAI Prompt API (Kotlin/Java) through AICore; beta |
| Devices | Apple Intelligence iPhones (15 Pro and later), with Apple Intelligence turned on | Gemini Nano phones, e.g. Pixel 9-11, Galaxy S26, Z Fold7/8; model versions nano-v2 to nano-v4 |
| Context | 4,096 tokens per session, input and output together | Not documented |
| Structured output | Guided generation, including schemas built at runtime (`DynamicGenerationSchema`) | Alpha |
| Streaming | Yes | Yes |
| Limits | Device and setting must support Apple Intelligence | Per-app inference and battery quotas (`BUSY`, `PER_APP_BATTERY_USE_QUOTA_EXCEEDED`); Google warns that Nano versions answer the same prompt differently |

**Why the game fits:**
- **Small prompts by design.** Each turn sends a fresh snapshot, not a growing chat log. Measured from `llm.log`:
  a narration request is about 0.75k tokens (90th percentile about 0.9k) with up to 500 tokens out, and an
  interpreter request about 0.5k, at most about 1.6k with its schema. Both fit in 4,096 with room to spare.
- **A small interface.** A backend is two calls, `complete_json` and `stream_text` (`llm/base.py:19-29`). An
  on-device backend is one more implementation, next to the OpenAI-compatible, Claude and offline ones
  (`llm/__init__.py`, `config.py:13`).
- **Built for small models.** The sentence guard (`llm/guard.py`) exists because small local models slip. The
  model check (`llm/check.py`, F12 -> Models) can score each phone model, which is worth doing for each Nano
  version.
- **JSON either way.** Apple's runtime schemas can mirror the interpreter's JSON Schema. Failing that, the game
  already falls back to asking for JSON and parsing it (`openai_compat.py:79-84`, `extract_json` in
  `llm/base.py`).
- **A fallback already exists.** When the model isn't there (an older phone, Apple Intelligence off, an Android
  quota hit), the game plays on with the keyword matcher and narration stitched from the facts.

**What it changes in the plan:**
- **The phone version becomes an app.** These models are only reachable from native code; Safari doesn't
  expose them to web pages. The app is a native shell (a Swift app and a Kotlin app with a web view, or
  Capacitor) that shows the same terminal page and bridges the two calls to the platform model.
- **The game should run on the phone.** If it ran on the Mac instead, every prompt would make a round trip to the
  phone and back. That makes Phase 4 (Python on the phone) the main road instead of an option. There are two
  ways to do it inside the app:
  - Pyodide in the web view, reusing textual-wasm or a small driver of your own.
  - Embedded CPython, which officially supports iOS and Android (PEPs 730 and 738). It's faster and has
    threads, but needs more native plumbing.
- **Phase 2 still comes first.** The narrow layout, the page and the Web Audio sound carry over unchanged, and
  the served build covers phones without an on-device model.
- **Stores get easier.** An app with on-device AI is no longer a thin web wrapper, which helps with App Store
  review. Store accounts cost $99 a year (Apple) and $25 once (Google).

**Rough effort (future):** the device backend and its bridge, 3-5 days per platform, on top of the app shell and
Phase 4.

### Testing on Android without Android Studio

The test device is a Galaxy Z Fold 8. It's on Google's Gemini Nano (nano-v4) device list, and its cover screen,
inner screen and live folding make it the multi-resolution test.

- **Signing:** an APK only needs a self-made key, and the build tools create a debug key on their own. No Android
  Studio, paid certificate or Play account is needed. Google's developer verification for sideloaded apps
  reaches the US in 2027, and installs over `adb` are exempt.
- **On the Mac:** Java and Android's command-line tools from Homebrew. Bubblewrap and Briefcase can download
  these themselves. `adb` comes from `brew install android-platform-tools`; or copy the APK to the phone and open
  it.
- **On the phone:**
  - Developer options with USB or wireless debugging (for `adb`), or "Install unknown apps" allowed for My Files.
  - Samsung's Auto Blocker (Settings -> Security and privacy) blocks sideloaded apps and USB commands; turn it
    off while testing.
- **Spikes, smallest first:**
  1. **No APK:** the served game in Chrome on the Fold over Tailscale. This tests folding and resizing directly.
  2. **A thin web-view APK** (Capacitor or Bubblewrap) around the served page. The page needs HTTPS, which
     Tailscale Serve provides.
  3. **The game on the phone:** a Pyodide build bundled in the web-view app, or Briefcase (embedded Python). The
     risk is the compiled dependencies; Pyodide has pydantic-core and Pillow, and embedded Android Python may not
     have pydantic-core yet.
- **Folding:**
  - Android restarts an app when the screen size changes. The APK must declare `android:configChanges` (screen
    size, smallest screen size, screen layout, orientation) so the web view and the game session survive a fold.
  - The stock textual-serve page sets the text size once at load; resizing text on unfold needs our own page
    script.
  - Test folding mid-dice-roll, with the keyboard up, in Flex mode and in split screen.
  - Check typing with the Samsung Keyboard early, because predictive text can garble input in xterm.js.

## Screenshots (`portability-screens/`)

1. [`1-browser-desktop-fight.jpg`](portability-screens/1-browser-desktop-fight.jpg): served, desktop size,
   unchanged. A fight with sprites and a chest card.
2. [`2-phone-before-viewport-fix.jpg`](portability-screens/2-phone-before-viewport-fix.jpg): phone portrait,
   textual-serve's stock page. A cropped 980-px layout.
3. [`3-phone-game-screen.jpg`](portability-screens/3-phone-game-screen.jpg): phone portrait with the viewport
   fix, about 52 columns. The 17-column story column.
4. [`4-phone-d20.jpg`](portability-screens/4-phone-d20.jpg): the d20 at phone width. It renders well, but the
   76-column box overflows.
5. [`5-phone-campfire.jpg`](portability-screens/5-phone-campfire.jpg): the campfire at phone width. Truncated
   names, clipped buttons.
6. [`6-phone-landscape.jpg`](portability-screens/6-phone-landscape.jpg): phone landscape, about 112x25. Fits
   across, but only about 5 lines of story.
