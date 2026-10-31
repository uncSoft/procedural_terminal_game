import SwiftUI
import UIKit
import WebKit

/// The served page in a web view, made to feel like an app's own screen: black behind it, no bouncing or pinching,
/// no link previews, sound allowed to start without a tap first, the page's process brought back if iOS ends it,
/// and the game's blows felt as well as heard (the page passes on each sound it plays: `haptics`).
struct GameView: UIViewRepresentable {
    let url: URL
    @Binding var trouble: String?
    let settings: () -> Void

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.allowsInlineMediaPlayback = true
        config.mediaTypesRequiringUserActionForPlayback = []
        config.userContentController.add(context.coordinator, name: "ptg")
        let view = WKWebView(frame: .zero, configuration: config)
        view.isOpaque = false
        view.backgroundColor = .black
        view.scrollView.backgroundColor = .black
        view.scrollView.bounces = false
        view.scrollView.delegate = context.coordinator  // (no pinching: viewForZooming)
        view.allowsLinkPreview = false
        view.navigationDelegate = context.coordinator
        let held = UILongPressGestureRecognizer(target: context.coordinator, action: #selector(Coordinator.held(_:)))
        held.numberOfTouchesRequired = 3
        held.minimumPressDuration = 0.8
        view.addGestureRecognizer(held)
        context.coordinator.load(url, in: view)
        return view
    }

    func updateUIView(_ view: WKWebView, context: Context) {
        context.coordinator.parent = self
        if context.coordinator.loaded != url {
            context.coordinator.load(url, in: view)
        }
    }

    final class Coordinator: NSObject, WKNavigationDelegate, WKScriptMessageHandler, UIScrollViewDelegate {
        var parent: GameView
        var loaded: URL?

        init(_ parent: GameView) {
            self.parent = parent
        }

        func load(_ url: URL, in view: WKWebView) {
            loaded = url
            view.load(URLRequest(url: url))
        }

        func viewForZooming(in scrollView: UIScrollView) -> UIView? { nil }

        func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!,
                     withError error: Error) {
            parent.trouble = error.localizedDescription
        }

        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
            parent.trouble = error.localizedDescription
        }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            parent.trouble = nil
        }

        func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
            webView.reload()  // (iOS ends a web view's process to free memory: the game picks up where it was)
        }

        @objc func held(_ gesture: UILongPressGestureRecognizer) {
            if gesture.state == .began {
                parent.settings()
            }
        }

        func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
            guard let body = message.body as? [String: Any], let sound = body["sound"] as? String else { return }
            Haptics.feel(sound)
        }
    }
}

/// A sound the game plays, felt too: the page names each one it plays (its file, "hurt.wav", "kill_2.wav"), and a
/// few are blows worth feeling.
enum Haptics {
    private static let feels: [(String, UIImpactFeedbackGenerator.FeedbackStyle, CGFloat)] = [
        ("hurt", .heavy, 1.0), ("awful", .heavy, 1.0), ("bomb", .heavy, 1.0), ("boss_encounter", .heavy, 1.0),
        ("boss_title", .heavy, 0.8), ("screech", .heavy, 0.8), ("crit_hit", .rigid, 1.0), ("kill", .rigid, 0.8),
        ("shatter", .rigid, 0.6), ("hit", .medium, 0.7), ("dice_land", .soft, 0.6), ("great", .rigid, 1.0),
    ]
    private static var generators: [UIImpactFeedbackGenerator.FeedbackStyle: UIImpactFeedbackGenerator] = [:]

    static func feel(_ sound: String) {
        let name = (sound as NSString).lastPathComponent
        guard let (_, style, strength) = feels.first(where: { name.hasPrefix($0.0) }) else { return }
        let generator = generators[style] ?? UIImpactFeedbackGenerator(style: style)
        generators[style] = generator
        generator.impactOccurred(intensity: strength)
    }
}
