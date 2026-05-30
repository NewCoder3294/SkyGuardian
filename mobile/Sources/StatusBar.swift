import SwiftUI

/// Top status strip: link state, mission stage, and per-channel health. Pure view.
struct StatusBar: View {
    let connection: ConnectionState
    let stage: String
    let lastError: String?
    let health: Health?

    var body: some View {
        VStack(spacing: 6) {
            HStack {
                channel("LINK", value: linkText, ok: isConnected)
                Spacer()
                channel("STAGE", value: stage.uppercased(), ok: stage != "stopped" && stage != "—")
            }
            HStack(spacing: 14) {
                channel("TELLO", value: health?.tello.uppercased() ?? "—", ok: health?.tello == "connected")
                channel("MAVIC", value: health?.mavic.uppercased() ?? "—", ok: health?.mavic == "streaming")
                channel("PERC", value: health?.perception.uppercased() ?? "—", ok: health?.perception == "ok")
                Spacer()
            }
            if let lastError, !lastError.isEmpty {
                HStack {
                    Text("FAULT: \(lastError.uppercased())").font(Theme.mono(10, weight: .semibold))
                        .foregroundColor(Theme.danger)
                    Spacer()
                }
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
        .background(Theme.panel)
        .overlay(Rectangle().frame(height: 1).foregroundColor(Theme.hairline), alignment: .bottom)
    }

    private var isConnected: Bool { if case .connected = connection { return true }; return false }

    private var linkText: String {
        switch connection {
        case .disconnected: return "OFFLINE"
        case .connecting: return "LINKING"
        case .connected: return "ONLINE"
        case .failed: return "FAULT"
        }
    }

    private func channel(_ label: String, value: String, ok: Bool) -> some View {
        HStack(spacing: 6) {
            Text(label).font(Theme.mono(9)).foregroundColor(Theme.inkSecondary)
            Text(value).font(Theme.mono(11, weight: .semibold))
                .foregroundColor(ok ? Theme.olive : Theme.ink)
        }
    }
}
