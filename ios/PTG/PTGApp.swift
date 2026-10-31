import AVFoundation
import SwiftUI

/// The game in its own window on an iPhone: the page `ptg serve` serves (the terminal in xterm.js, the art layer's
/// pictures, the sound) full screen in a web view, the phone's touch layout and all. For now the game runs wherever
/// that server does (the Mac while you develop, Render for testers); in the app to come it runs inside the phone,
/// behind this same window (docs/plans/mobile-view.md §4).
@main
struct PTGApp: App {
    init() {
        // The game's sound plays with the ring/silent switch on, alongside any music already playing.
        let session = AVAudioSession.sharedInstance()
        try? session.setCategory(.playback, mode: .default, options: [.mixWithOthers])
        try? session.setActive(true)
    }

    var body: some Scene {
        WindowGroup {
            ContentView()
        }
    }
}
