import AVFoundation
import SwiftUI
import UIKit

/// Hosts the AVSampleBufferDisplayLayer that renders the direct Tello H.264 stream.
final class SampleLayerHostView: UIView {
    private weak var sampleLayer: AVSampleBufferDisplayLayer?
    func attach(_ layer: AVSampleBufferDisplayLayer) {
        sampleLayer?.removeFromSuperlayer()
        layer.frame = bounds
        self.layer.addSublayer(layer)
        sampleLayer = layer
    }
    override func layoutSubviews() {
        super.layoutSubviews()
        sampleLayer?.frame = bounds
    }
}

struct SampleLayerView: UIViewRepresentable {
    let layer: AVSampleBufferDisplayLayer
    func makeUIView(context: Context) -> SampleLayerHostView {
        let v = SampleLayerHostView()
        v.backgroundColor = .black
        v.attach(layer)
        return v
    }
    func updateUIView(_ uiView: SampleLayerHostView, context: Context) {}
}

/// FEED — direct phone↔Tello video (no laptop). Join the Tello WiFi and this shows
/// the live camera. Honest status: never fakes a frame.
struct TelloDirectView: View {
    @StateObject private var stream = TelloDirectStream()

    var body: some View {
        ZStack {
            Color.black
            SampleLayerView(layer: stream.displayLayer)
            if stream.state != .streaming { overlay }
            VStack {
                HStack {
                    Text(badge).font(Theme.mono(10, weight: .semibold))
                        .foregroundColor(stream.state == .streaming ? Color(red: 0.4, green: 0.9, blue: 0.5) : Theme.faint)
                        .padding(6).background(Color.black.opacity(0.5))
                    Spacer()
                }
                Spacer()
            }
            .padding(8)
        }
        .onAppear { stream.start() }
        .onDisappear { stream.stop() }
    }

    private var badge: String {
        switch stream.state {
        case .streaming: return "● TELLO LIVE"
        case .connecting: return "○ CONNECTING…"
        case .error(let e): return "FAULT: \(e)"
        case .idle: return "○ TELLO"
        }
    }

    private var overlay: some View {
        VStack(spacing: 8) {
            Text(badge).font(Theme.mono(13, weight: .semibold)).foregroundColor(Theme.faint)
            Text("join the Tello WiFi (TELLO-XXXXXX)").font(Theme.mono(9)).foregroundColor(Theme.faint)
        }
    }
}
