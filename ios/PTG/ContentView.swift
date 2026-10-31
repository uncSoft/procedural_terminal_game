import SwiftUI

/// The game, or where to find it. The server's address is asked for the first time (and whenever the game can't be
/// reached), then kept on the phone, never in the app: the repo is public. Three fingers held on the screen bring
/// the question back.
struct ContentView: View {
    @AppStorage("server") private var server = ""
    @State private var asking = false
    @State private var trouble: String?

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()  // (round the notch and the home bar: the page keeps to the safe area)
            if let url = URL(string: server), !server.isEmpty {
                GameView(url: url, trouble: $trouble) { asking = true }
            }
        }
        .statusBarHidden()
        .persistentSystemOverlays(.hidden)
        .onAppear {
            UIApplication.shared.isIdleTimerDisabled = true  // (the screen stays on while you think)
            asking = server.isEmpty
        }
        .onChange(of: trouble) { _, now in
            if now != nil { asking = true }
        }
        .sheet(isPresented: $asking) {
            ServerView(server: $server, trouble: trouble) {
                trouble = nil
                asking = false
            }
            .interactiveDismissDisabled(server.isEmpty)
        }
    }
}

/// Where the game is: the address of a `ptg serve` (on the Mac, `http://localhost:8766` reaches it from the
/// simulator; from a phone, the Mac's address on your Wi-Fi), or the testers' server.
struct ServerView: View {
    @Binding var server: String
    let trouble: String?
    let done: () -> Void
    @State private var typed = ""

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("http://localhost:8766", text: $typed)
                        .keyboardType(.URL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .onSubmit(save)
                } header: {
                    Text("Where the game is")
                } footer: {
                    Text("The address of a ptg serve: http://localhost:8766 from the simulator, the Mac's Wi-Fi "
                         + "address from a phone, or the testers' server. Hold three fingers on the game to "
                         + "change it.")
                }
                if let trouble {
                    Section("Couldn't reach it") {
                        Text(trouble).foregroundStyle(.red)
                    }
                }
            }
            .navigationTitle("PTG")
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Play", action: save).disabled(URL(string: cleaned) == nil || cleaned.isEmpty)
                }
            }
        }
        .onAppear { typed = server }
    }

    private var cleaned: String {
        let text = typed.trimmingCharacters(in: .whitespacesAndNewlines)
        return text.isEmpty || text.contains("://") ? text : "http://" + text
    }

    private func save() {
        guard !cleaned.isEmpty, URL(string: cleaned) != nil else { return }
        server = cleaned
        done()
    }
}
