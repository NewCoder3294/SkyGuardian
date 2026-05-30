import SwiftUI

enum CenterView { case map, feed }

struct ContentView: View {
    @StateObject private var client = WorldClient()
    @State private var showConnect = true
    @State private var center: CenterView = .map

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
                    MJPEGView(serverURL: client.serverURL, path: "/video/tello")
                }
                if center == .map { legend.padding(10) }
                viewToggle.frame(maxWidth: .infinity, alignment: .top).padding(.top, 8)
                if showConnect { connectPanel.padding(12).frame(maxWidth: .infinity, alignment: .topTrailing) }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)

            ControlBar(onCommand: { client.send($0) }, enabled: isConnected)
        }
        .background(Theme.paper)
        .preferredColorScheme(.light)   // forced light mode
        .onAppear(perform: maybeLoadDemo)
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
