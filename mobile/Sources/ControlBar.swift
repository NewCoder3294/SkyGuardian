import SwiftUI

/// Intent controls. The hard STOP is a first-class, always-visible button — not
/// voice-only — and is visually dominant. Pure view: taps call back out.
struct ControlBar: View {
    let onCommand: (Command) -> Void
    let enabled: Bool

    var body: some View {
        VStack(spacing: 10) {
            HStack(spacing: 10) {
                button("FOLLOW", command: .followMe)
                button("HOLD", command: .hold)
                button("RECALL", command: .recall)
            }
            stopButton
        }
        .padding(14)
        .background(Theme.panel)
        .overlay(Rectangle().frame(height: 1).foregroundColor(Theme.hairline), alignment: .top)
    }

    private func button(_ title: String, command: Command) -> some View {
        Button { onCommand(command) } label: {
            Text(title).font(Theme.mono(13, weight: .semibold))
                .frame(maxWidth: .infinity, minHeight: 46)
                .foregroundColor(enabled ? Theme.ink : Theme.faint)
                .overlay(Rectangle().stroke(enabled ? Theme.ink : Theme.faint, lineWidth: 1.4))
        }
        .disabled(!enabled)
    }

    private var stopButton: some View {
        Button { onCommand(.stop) } label: {
            Text("◼  S T O P").font(Theme.mono(18, weight: .bold))
                .frame(maxWidth: .infinity, minHeight: 60)
                .foregroundColor(Theme.panel)
                .background(enabled ? Theme.danger : Theme.faint)
        }
        .disabled(!enabled)
    }
}
