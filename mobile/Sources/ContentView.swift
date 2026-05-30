import SwiftUI

enum CenterView { case map, feed }
enum MapMode: String, CaseIterable { case twoD = "2D", threeD = "3D", tac = "TAC" }

struct ContentView: View {
    @StateObject private var client = WorldClient()
    @StateObject private var voice = VoiceController()
    @StateObject private var model = ModelDownloader()
    @StateObject private var location = LocationProvider()
    @StateObject private var stream = TelloDirectStream()
    @StateObject private var follow = FollowCoordinator()
    @State private var showConnect = true
    @State private var center: CenterView = .map
    @State private var mapMode: MapMode = .twoD
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
                    mapBody
                } else {
                    TelloDirectView(stream: stream, follow: follow)   // direct phone↔Tello, no laptop
                }
                if center == .map {
                    legend.padding(10)
                    VStack { Spacer(); HStack { Spacer(); mapModePicker; Spacer() } }.padding(.bottom, 8)
                }
                viewToggle.frame(maxWidth: .infinity, alignment: .top).padding(.top, 8)
                if showConnect { connectPanel.padding(12).frame(maxWidth: .infinity, alignment: .topTrailing) }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)

            voiceBar
            ControlBar(onCommand: { client.send($0) }, enabled: isConnected)
        }
        .background(Theme.paper)
        .preferredColorScheme(.light)   // forced light mode
        .onAppear { maybeLoadDemo(); location.start() }
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

    /// Route a resolved voice action through the single drone arbiter:
    ///  - "follow me"        → start following (takeoff) or resume after a takeover,
    ///  - land / stop / emerg → land and disarm (always wins),
    ///  - any other flight    → take over (pause follow), then execute and hover,
    ///  - hold / recall       → mission intents to the laptop when connected.
    private func handle(_ action: DroneAction) {
        let fn = action.function

        if fn == .followMe {
            if follow.phase == .disarmed { startFollow() } else { follow.resumeFollow() }
            return
        }

        if fn == .emergency {                               // failsafe: cut motors, no land
            if follow.isArmed { follow.emergencyCut() } else { TelloCommander.shared.send("emergency") }
            return
        }

        if fn == .land {
            if follow.isArmed { follow.disarmAndLand() } else { TelloCommander.shared.send("land") }
            return
        }

        if fn == .stop {                                    // halt: stop the loop / neutralize sticks
            if follow.isArmed { follow.disarmAndLand() } else { TelloCommander.shared.rc(.hover) }
            if isConnected { client.send(.stop) }
            return
        }

        if fn.isFlight {
            if follow.isArmed { follow.pauseToManual() }   // voice takeover → pause-and-hold
            TelloCommander.shared.execute(action)
        } else if let command = fn.missionCommand {
            client.send(command)                            // hold / recall → laptop
        }
    }

    /// Voice/UI entry point to begin following: ensure video is flowing, then arm
    /// (takeoff + follow). The Tello must be on its WiFi and able to see the hat tag.
    private func startFollow() {
        stream.start()
        follow.arm(stream: stream)
    }

    /// Hard safety control — not voice-only (per spec): land the drone now and signal
    /// a mission stop to the laptop if connected.
    private func hardStop() {
        // Route through the arbiter so the follow rc loop is actually stopped — not
        // left fighting the landing.
        if follow.isArmed { follow.disarmAndLand() } else { TelloCommander.shared.send("land") }
        if isConnected { client.send(.stop) }
    }

    // MARK: map

    /// 2D/3D ride on the OpenStreetMap basemap (free/open); TAC is the offline
    /// GPS-less tactical map. All render only real world-model entities — no mock.
    @ViewBuilder private var mapBody: some View {
        switch mapMode {
        case .twoD, .threeD:
            ZStack(alignment: .bottomTrailing) {
                if location.coordinate != nil {
                    OSMMapView(entities: client.entities, trails: client.trails,
                               origin: location.coordinate,
                               dimension: mapMode == .threeD ? .tilted : .flat)
                } else {
                    locationWait
                }
                Text("© OpenStreetMap").font(Theme.mono(8)).foregroundColor(Theme.ink)
                    .padding(.horizontal, 4).padding(.vertical, 2)
                    .background(Theme.panel.opacity(0.85)).padding(6)
            }
        case .tac:
            LocalMapView(entities: client.entities, trails: client.trails,
                         projection: MapProjection(spanMeters: 24))
        }
    }

    private var locationWait: some View {
        VStack(spacing: 6) {
            Text("ACQUIRING LOCATION…").font(Theme.mono(11, weight: .semibold)).foregroundColor(Theme.ink)
            Text("enable location to anchor the map").font(Theme.mono(9)).foregroundColor(Theme.inkSecondary)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Theme.paper)
    }

    private var mapModePicker: some View {
        HStack(spacing: 0) {
            ForEach(MapMode.allCases, id: \.self) { mode in
                Button { mapMode = mode } label: {
                    Text(mode.rawValue).font(Theme.mono(11, weight: .semibold))
                        .foregroundColor(mapMode == mode ? Theme.panel : Theme.ink)
                        .padding(.horizontal, 16).padding(.vertical, 7)
                        .background(mapMode == mode ? Theme.olive : Color.clear)
                }
            }
        }
        .background(Theme.panel.opacity(0.95))
        .overlay(Rectangle().stroke(Theme.hairline, lineWidth: 1))
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
