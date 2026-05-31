import CoreLocation
import SwiftUI

enum CenterView { case map, feed }

struct ContentView: View {
    @StateObject private var client = WorldClient()
    @StateObject private var voice = VoiceController()
    @StateObject private var model = ModelDownloader()
    @StateObject private var location = LocationProvider()
    @StateObject private var stream = TelloDirectStream()
    @StateObject private var follow = FollowCoordinator()
    @StateObject private var localizer = Localizer()
    @StateObject private var aligner = FrameAligner()
    @StateObject private var anchorCam = AnchorCamera()
    @StateObject private var scout = ScoutController()
    @StateObject private var detector = TelloObjectDetector()
    @StateObject private var buildingsStore = BuildingsStore()
    @State private var showConnect = true
    @State private var center: CenterView = .map
    @State private var setupStarted = false
    @State private var pendingArm: PendingArm?
    @State private var pendingApproach = false
    @State private var pendingScout = false

    enum PendingArm { case visualMe, tag }

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
                    TelloDirectView(stream: stream, follow: follow, detector: detector, onCommand: handle)   // direct phone↔Tello, no laptop
                }
                if center == .map {
                    legend.padding(10)
                }
                viewToggle.frame(maxWidth: .infinity, alignment: .top).padding(.top, 8)
                if showConnect { connectPanel.padding(12).frame(maxWidth: .infinity, alignment: .topTrailing) }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)

            voiceBar
            // Laptop intent bar — only on the Map tab. In Feed the Tello is flown
            // directly from the phone, so these laptop-routed buttons are inert.
            if center == .map {
                ControlBar(onCommand: { client.send($0) }, enabled: isConnected)
            }
        }
        .background(Theme.paper)
        .preferredColorScheme(.light)   // forced light mode
        .onAppear {
            applyDebugLaunchArgs()
            location.start()
            // On-device object detection on the Tello feed (bounding boxes), tapped
            // independently of the follow loop's AprilTag detection.
            stream.onPixelBufferSecondary = { pb in detector.feed(pb) }
            follow.onLabel = { [weak client] kind, label in
                client?.sendLabelEvent(kind: kind, source: "follower", label: label)
            }
        }
        .overlay { if needsSetup { setupOverlay } }
        .task { await startModelIfNeeded() }
        .onReceive(location.$coordinate) { _ in updateLocalizer() }
        .onReceive(follow.$distance) { _ in updateLocalizer() }
        .confirmationDialog("Take off?", isPresented: Binding(get: { pendingArm != nil },
                                                              set: { if !$0 { pendingArm = nil } }),
                            titleVisibility: .visible) {
            Button(pendingArm == .tag ? "TAKE OFF & TRACK TAG" : "TAKE OFF & FOLLOW ME", role: .destructive) {
                if pendingArm == .tag { startTrack() } else { startFollow() }
                pendingArm = nil
            }
            Button("Cancel", role: .cancel) { pendingArm = nil }
        } message: {
            Text("The drone will launch and \(pendingArm == .tag ? "track the AprilTag" : "follow you visually"). Keep clear; STOP lands it.")
        }
        .confirmationDialog("Begin autonomous approach?", isPresented: $pendingApproach, titleVisibility: .visible) {
            Button("Approach target", role: .destructive) { client.send(.approach) }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("The companion drone will autonomously fly to the selected target and hold standoff.")
        }
        .confirmationDialog("Scout ahead?", isPresented: $pendingScout, titleVisibility: .visible) {
            Button("SCOUT & RETURN", role: .destructive) { scout.start(follow: follow) }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("The companion will explore ~\(scout.approxReachM) m ahead in short legs, scan the area, then retrace its path back and resume following. LAND stops it any time.")
        }
        .onReceive(follow.$phase) { _ in publishFollow() }
        .onReceive(client.$connection) { _ in
            if isConnected { buildingsStore.load(from: httpBase) }   // offline basemap from the laptop
        }
        // Each time the phone camera sees the launch anchor tag, refresh the
        // launch→world transform (continuous drift correction while aligning).
        .onReceive(anchorCam.$latest) { fix in
            guard let fix else { return }
            aligner.observe(distance: fix.distance, bearingRad: fix.bearingRad,
                            headingDeg: location.headingDeg)
        }
    }

    /// Drive the map's phone-side localization from the AprilTag follow + GPS/heading.
    private func updateLocalizer() {
        // GPS-free: operator fixed at the launch origin, drone placed relative via the
        // AprilTag + compass heading (magnetometer, a local sensor — not GPS).
        localizer.update(distance: follow.distance,
                         bearingRad: follow.bearingDeg * .pi / 180,
                         headingDeg: location.headingDeg,
                         active: follow.phase == .following)
        publishFollow()   // distance/bearing moved → keep the laptop's follow inset live

        // Co-registered map: once aligned to the launch anchor, re-express the
        // operator + drone in the world frame and publish so the dashboard map
        // shows the same track. Pre-alignment, worldEntities is empty (nothing sent).
        localizer.project(through: aligner)
        if isConnected, !localizer.worldEntities.isEmpty {
            client.sendEntityReport(localizer.worldEntities)
        }
    }

    /// Publish the Tello's relative follow geometry to the laptop so its dashboard
    /// can render the follow inset. Relative range/bearing only — never map coords
    /// (the phone follow frame and the Mavic SLAM frame aren't co-registered).
    private func publishFollow() {
        guard isConnected else { return }
        client.sendFollowState(active: follow.phase != .disarmed,
                               phase: follow.phase.label,
                               distanceM: follow.distance,
                               bearingDeg: follow.bearingDeg)
    }

    private var alignLabel: String {
        if anchorCam.isRunning { return "ALIGNING" }
        return aligner.isAligned ? "RE-ALIGN" : "ALIGN"
    }

    /// Toggle the launch-anchor camera. While running, each anchor-tag sighting
    /// refreshes the launch→world transform (see the onReceive in `body`).
    private func toggleAlign() {
        if anchorCam.isRunning { anchorCam.stop() } else { anchorCam.start() }
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

    private func applyDebugLaunchArgs() {
        #if DEBUG
        if CommandLine.arguments.contains("-feed") {
            client.serverURL = "ws://127.0.0.1:8001/ws"
            center = .feed
            showConnect = false
        }
        #endif
    }

    private var isConnected: Bool { if case .connected = client.connection { return true }; return false }

    /// HTTP base for the laptop, derived from the WS serverURL
    /// (ws://host:8000/ws → http://host:8000). Used to fetch the offline buildings.
    private var httpBase: String {
        var s = client.serverURL
            .replacingOccurrences(of: "ws://", with: "http://")
            .replacingOccurrences(of: "wss://", with: "https://")
        if let r = s.range(of: "/ws") { s = String(s[s.startIndex..<r.lowerBound]) }
        return s
    }

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
            // Map co-registration: point the phone at the launch anchor tag and tap
            // to align the phone's frame with the laptop world frame (toggles the
            // anchor camera; auto-refreshes while it sees the tag).
            Button { toggleAlign() } label: {
                Text(alignLabel).font(Theme.mono(11, weight: .semibold))
                    .foregroundColor(anchorCam.isRunning ? Theme.panel : Theme.ink)
                    .padding(.horizontal, 12).padding(.vertical, 12)
                    .background(anchorCam.isRunning ? Theme.olive : Color.clear)
                    .overlay(Rectangle().stroke(Theme.ink, lineWidth: 1.4))
            }
            // Soldier-commanded scout: only while airborne under follow control.
            Button { pendingScout = true } label: {
                Text(scout.isRunning ? "SCOUTING" : "SCOUT").font(Theme.mono(11, weight: .semibold))
                    .foregroundColor(scout.isRunning ? Theme.panel : Theme.ink)
                    .padding(.horizontal, 12).padding(.vertical, 12)
                    .background(scout.isRunning ? Theme.olive : Color.clear)
                    .overlay(Rectangle().stroke(Theme.ink, lineWidth: 1.4))
            }
            .disabled(!follow.isArmed || scout.isRunning)
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
            // Initial arm (takeoff) must be confirmed; resuming from manual does not.
            if follow.phase == .disarmed { pendingArm = .visualMe } else { follow.resumeFollow() }
            return
        }

        if fn == .track {   // "track that boat" — tag-free visual tracking
            if follow.phase == .disarmed { pendingArm = .visualMe } else { follow.relock() }
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

        if fn == .approach {
            guard isConnected else { return }   // approach is laptop-side autonomy
            pendingApproach = true               // drives a confirmationDialog
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
        follow.arm(stream: stream, mode: .visualMe)
    }

    private func startTrack() {
        stream.start()
        follow.arm(stream: stream, mode: .tag)
    }

    /// Hard safety control — not voice-only (per spec): land the drone now and signal
    /// a mission stop to the laptop if connected.
    private func hardStop() {
        // Cancel any in-flight scout maneuver first so no further scout commands
        // race the landing.
        scout.abort()
        // Route through the arbiter so the follow rc loop is actually stopped — not
        // left fighting the landing.
        if follow.isArmed { follow.disarmAndLand() } else { TelloCommander.shared.send("land") }
        if isConnected { client.send(.stop) }
    }

    // MARK: map

    /// Offline + GPS-free relative map (mirrors the laptop dashboard): the operator is
    /// the launch origin, the drone is placed relative via the on-device AprilTag
    /// follow, and pre-cached buildings (from the laptop's `/map/buildings`) are the
    /// basemap. No GPS, no live tiles — drag to pan, pinch to zoom.
    @ViewBuilder private var mapBody: some View {
        LocalMapView(entities: mapEntities, trails: mapTrails,
                     projection: MapProjection(spanMeters: 40),
                     buildings: buildingsStore.buildings)
    }

    // Map data: phone-side AprilTag localization (operator + drone + trails), plus any
    // laptop world-model entities when connected.
    private var mapEntities: [Entity] { localizer.entities + client.entities }
    private var mapTrails: [String: [Vec3]] { localizer.trails.merging(client.trails) { a, _ in a } }

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
