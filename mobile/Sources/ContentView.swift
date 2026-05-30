import SwiftUI

enum CenterView { case map, feed }

struct ContentView: View {
    @StateObject private var client = WorldClient()
    @StateObject private var voice = VoiceController()
    @StateObject private var model = ModelDownloader()
    @State private var showConnect = true
    @State private var center: CenterView = .map
    @State private var setupStarted = false

    var body: some View {
        VStack(spacing: 0) {
            StatusBar(
                connection: client.connection,
                stage: client.stage,
                lastError: client.lastError,
                health: client.health
            )

            ZStack(alignment: .topLeading) {
                if center == .map {
                    LocalMapView(entities: client.entities, trails: client.trails,
                                 projection: MapProjection(spanMeters: 24))
                } else {
                    TelloDirectView()   // direct phone↔Tello video, no laptop
                }
                if center == .map { legend.padding(10) }
                viewToggle.frame(maxWidth: .infinity, alignment: .top).padding(.top, 8)
                if showConnect { connectPanel.padding(12).frame(maxWidth: .infinity, alignment: .topTrailing) }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)

            voiceBar
            ControlBar(onCommand: { client.send($0) }, enabled: isConnected)
        }
        .background(Theme.paper)
        .preferredColorScheme(.light)   // forced light mode
        .onAppear(perform: maybeLoadDemo)
        .overlay { if needsSetup { setupOverlay } }
        .task { await startModelIfNeeded() }
    }

    // MARK: first-launch model setup

    /// The on-device model is fetched once, automatically, on first launch. Until it's
    /// present the SETUP screen blocks the UI (it's required for voice/vision).
    private var needsSetup: Bool {
        if ModelDownloader.isPresent { return false }
        if case .ready = model.state { return false }
        return true
    }

    private func startModelIfNeeded() async {
        guard !ModelDownloader.isPresent, !setupStarted else { return }
        setupStarted = true
        await model.ensureModel()
        if case .ready = model.state { voice.reloadService() }
    }

    private var setupOverlay: some View {
        VStack(spacing: 18) {
            Text("SYSTEM SETUP").font(Theme.mono(15, weight: .bold)).foregroundColor(Theme.ink)
            Text("Installing the on-device AI model (one-time, ~4.7 GB).\nNeeds WiFi — not the Tello network. Keep the app open.")
                .font(Theme.mono(10)).foregroundColor(Theme.inkSecondary)
                .multilineTextAlignment(.center)

            setupProgress

            if case .failed(let e) = model.state {
                Text(e).font(Theme.mono(9)).foregroundColor(Theme.danger)
                    .multilineTextAlignment(.center).padding(.horizontal, 24)
                Button("RETRY") { setupStarted = false; Task { await startModelIfNeeded() } }
                    .font(Theme.mono(12, weight: .semibold)).foregroundColor(Theme.panel)
                    .padding(.horizontal, 18).padding(.vertical, 9).background(Theme.olive)
            }
        }
        .padding(28)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Theme.paper)
    }

    @ViewBuilder private var setupProgress: some View {
        switch model.state {
        case .downloading(let p):
            VStack(spacing: 6) {
                GeometryReader { geo in
                    ZStack(alignment: .leading) {
                        Rectangle().fill(Theme.panel).overlay(Rectangle().stroke(Theme.hairline, lineWidth: 1))
                        Rectangle().fill(Theme.olive).frame(width: max(geo.size.width * p, 2))
                    }
                }.frame(width: 220, height: 14)
                Text("DOWNLOADING \(Int(p * 100))%").font(Theme.mono(11, weight: .semibold)).foregroundColor(Theme.ink)
            }
        case .verifying:
            Text("VERIFYING INTEGRITY…").font(Theme.mono(11, weight: .semibold)).foregroundColor(Theme.ink)
        case .unzipping:
            Text("INSTALLING MODEL…").font(Theme.mono(11, weight: .semibold)).foregroundColor(Theme.ink)
        case .failed:
            Text("SETUP FAILED").font(Theme.mono(11, weight: .semibold)).foregroundColor(Theme.danger)
        default:
            Text("PREPARING…").font(Theme.mono(11, weight: .semibold)).foregroundColor(Theme.inkSecondary)
        }
    }

    private func maybeLoadDemo() {
        #if DEBUG
        if CommandLine.arguments.contains("-demo") {
            client.loadSampleData()
            showConnect = false
        }
        if CommandLine.arguments.contains("-feed") {
            client.serverURL = "ws://127.0.0.1:8011/ws"   // local backend with the MJPEG relay
            center = .feed
            showConnect = false
        }
        #endif
    }

    private var isConnected: Bool { if case .connected = client.connection { return true }; return false }

    private var connectPanel: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("MISSION LINK").font(Theme.mono(10, weight: .semibold)).foregroundColor(Theme.inkSecondary)
            TextField("ws://host:8000/ws", text: $client.serverURL)
                .font(Theme.mono(12))
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .padding(8)
                .background(Theme.panel)
                .overlay(Rectangle().stroke(Theme.hairline, lineWidth: 1))
            HStack(spacing: 8) {
                Button(isConnected ? "DISCONNECT" : "CONNECT") {
                    if isConnected { client.disconnect() } else { client.connect(); showConnect = false }
                }
                .font(Theme.mono(12, weight: .semibold)).foregroundColor(Theme.panel)
                .padding(.horizontal, 14).padding(.vertical, 8).background(Theme.olive)
                if !showConnect {
                    Button("HIDE") { showConnect = false }
                        .font(Theme.mono(12)).foregroundColor(Theme.inkSecondary)
                }
            }
        }
        .padding(12)
        .background(Theme.panel.opacity(0.96))
        .overlay(Rectangle().stroke(Theme.hairline, lineWidth: 1))
        .frame(maxWidth: 260)
    }

    private var voiceBar: some View {
        HStack(spacing: 10) {
            Button { onMicTap() } label: {
                Text(micGlyph).font(Theme.mono(16, weight: .bold))
                    .frame(width: 46, height: 46)
                    .foregroundColor(isListening ? Theme.panel : Theme.ink)
                    .background(isListening ? Theme.danger : Color.clear)
                    .overlay(Rectangle().stroke(Theme.ink, lineWidth: 1.4))
            }
            .disabled(isDownloadingModel)
            VStack(alignment: .leading, spacing: 2) {
                Text("VOICE · \(voice.sourceLabel)").font(Theme.mono(9))
                    .foregroundColor(voice.available ? Theme.olive : Theme.inkSecondary)
                Text(voiceStatus).font(Theme.mono(11, weight: .semibold)).foregroundColor(Theme.ink)
            }
            Spacer()
            // Hard safety control — always available, not voice-only.
            Button { hardStop() } label: {
                Text("LAND").font(Theme.mono(12, weight: .bold))
                    .foregroundColor(Theme.panel)
                    .padding(.horizontal, 14).padding(.vertical, 12)
                    .background(Theme.danger)
                    .overlay(Rectangle().stroke(Theme.ink, lineWidth: 1.4))
            }
        }
        .padding(.horizontal, 14).padding(.vertical, 8)
        .background(Theme.panel)
        .overlay(Rectangle().frame(height: 1).foregroundColor(Theme.hairline), alignment: .top)
    }

    private var isListening: Bool { voice.state == .listening }
    private var isDownloadingModel: Bool {
        if case .downloading = model.state { return true }
        if case .unzipping = model.state { return true }
        return false
    }
    private var micGlyph: String { isListening ? "■" : "🎙" }

    private func onMicTap() {
        // The SETUP screen guarantees the model is present before the UI is usable.
        guard ModelDownloader.isPresent else { return }
        voice.toggle(onAction: handle)
    }

    /// Route a resolved voice action: flight commands go straight to the Tello over
    /// the shared UDP channel (works standalone); mission intents go to the laptop
    /// brain over the WS when it's connected.
    private func handle(_ action: DroneAction) {
        if action.function.isFlight {
            TelloCommander.shared.execute(action)
        } else if let command = action.function.missionCommand {
            client.send(command)
        }
    }

    /// Hard safety control — not voice-only (per spec): land the drone now and signal
    /// a mission stop to the laptop if connected.
    private func hardStop() {
        TelloCommander.shared.send("land")
        if isConnected { client.send(.stop) }
    }

    private var voiceStatus: String {
        switch model.state {
        case .downloading(let p): return "GET MODEL \(Int(p * 100))%"
        case .unzipping: return "UNPACKING MODEL…"
        case .failed(let e): return "MODEL: \(e)"
        default: break
        }
        switch voice.state {
        case .idle:
            if !ModelDownloader.isPresent { return "TAP TO GET MODEL" }
            return voice.lastAction.map { "→ \($0.label)" } ?? "TAP TO SPEAK"
        case .listening: return "● LISTENING…"
        case .thinking: return "PROCESSING…"
        case .error(let e): return e
        }
    }

    private var viewToggle: some View {
        HStack(spacing: 0) {
            toggleButton("MAP", on: center == .map) { center = .map }
            toggleButton("FEED", on: center == .feed) { center = .feed }
        }
        .overlay(Rectangle().stroke(Theme.hairline, lineWidth: 1))
        .background(Theme.panel.opacity(0.95))
    }

    private func toggleButton(_ title: String, on: Bool, _ action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title).font(Theme.mono(11, weight: .semibold))
                .foregroundColor(on ? Theme.panel : Theme.ink)
                .padding(.horizontal, 18).padding(.vertical, 7)
                .background(on ? Theme.olive : Color.clear)
        }
    }

    private var legend: some View {
        VStack(alignment: .leading, spacing: 3) {
            legendRow("●", "SOLDIER", Theme.olive)
            legendRow("▲", "DRONE", Theme.oliveDark)
            legendRow("◇", "POI", Theme.brown)
            legendRow("✕", "HAZARD", Theme.danger)
        }
        .padding(8)
        .background(Theme.panel.opacity(0.85))
        .overlay(Rectangle().stroke(Theme.hairline, lineWidth: 0.5))
    }

    private func legendRow(_ glyph: String, _ label: String, _ color: Color) -> some View {
        HStack(spacing: 6) {
            Text(glyph).font(Theme.mono(10)).foregroundColor(color)
            Text(label).font(Theme.mono(9)).foregroundColor(Theme.inkSecondary)
        }
    }
}
