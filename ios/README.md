# PTG on iPhone

The game in an iPhone app of its own: a small SwiftUI app that shows the page `ptg serve` serves (the terminal in
xterm.js, the art layer's pictures, the sound) full screen in a web view, with the phone's touch layout. This is step
two of the road to the App Store in `docs/plans/mobile-view.md`: for now the game runs wherever its server does
(your Mac while you work, the testers' server for testers). The App Store app keeps this same window and runs the
game inside the phone instead (embedded Python and Apple's on-device model as the narrator).

What the app adds to the page in Safari:

- **Full screen**: no browser bars, no status bar, black round the notch and the home bar.
- **Sound with the silent switch on**, alongside any music already playing, and it can start without a first tap.
- **Blows you can feel**: the page passes on each sound it plays, and hits, crits, kills, bombs and bosses buzz.
- **The screen stays on** while you think, and no bouncing, pinching or link previews.
- **Its own icon**: the hero's face.
- **Remembers where the game is**: asked the first time, kept on the phone, never in the app (the repo is public).
  Hold three fingers on the screen to change it.

## In the simulator

1. Serve the game on the Mac: `uv run ptg serve --port 8766`
2. Open `ios/PTG.xcodeproj` in Xcode, pick an iPhone simulator, and Run (⌘R).
3. At "Where the game is", type `localhost:8766` and tap Play.

## On your iPhone

1. Serve the game where your phone can reach it, on the same Wi-Fi as the Mac (your Mac's address on it is what
   `ipconfig getifaddr en0` prints):

   ```bash
   uv run ptg serve --host 0.0.0.0 --port 8766 --public-url http://YOUR-MAC-ADDRESS:8766
   ```

   Set `PTG_PASSWORD` first if you don't want everyone on the network to be able to play.
2. Plug the phone in, open `ios/PTG.xcodeproj` in Xcode, choose your iPhone as where to run, and in the PTG target's
   **Signing & Capabilities** pick your team (a free Apple ID works; its builds have to be put on the phone again
   every week). On the phone, trust the developer in Settings → General → VPN & Device Management the first time,
   and allow PTG to find devices on the local network when it asks.
3. At "Where the game is", type `YOUR-MAC-ADDRESS:8766` (or the testers' server) and tap Play.

For testers, a paid developer account ($99 a year) and TestFlight put the app on their phones without a cable. Apple
won't take an app that only shows a website for the App Store, which is why the store app runs the game inside it.

## Changing it

The project is three Swift files in `ios/PTG/`: `PTGApp.swift` (the sound's audio session), `ContentView.swift` (the
game, or where to find it), `GameView.swift` (the web view, haptics). The folder is synced with the project, so new
files join the app on their own. The page's side is in `src/ptg/web/app_index.html` (the sounds it passes on, and
taps on iOS going straight to the terminal: iOS held every tap back as a hover, so each button took two).
