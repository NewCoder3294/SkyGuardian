import SwiftUI

struct ContentView: View {
    @StateObject private var client = WorldClient()
    @State private var showConnect = true

    var body: some View {
        VStack(spacing: 0) {
            StatusBar(
                connection: client.connection,
                stage: client.stage,
                lastError: client.lastError,
                health: client.health
            )

            ZStack(alignment: .topLeading) {
                LocalMapView(entities: client.entities, trails: client.trails,
                             projection: MapProjection(spanMeters: 24))
                legend.padding(10)
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
