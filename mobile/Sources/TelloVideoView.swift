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
/// the live camera. Also hosts the autonomous AprilTag follow loop. Honest status:
/// never fakes a frame.
struct TelloDirectView: View {
    @ObservedObject var stream: TelloDirectStream
    @ObservedObject var follow: FollowCoordinator
    @ObservedObject private var tello = TelloCommander.shared
    var onCommand: (DroneAction) -> Void = { _ in }
    @State private var confirmArm = false
    @State private var confirmTrack = false
    @State private var showManual = false

    private let videoAspect: CGFloat = 4.0 / 3.0   // Tello stream is 4:3

    var body: some View {
        ZStack {
            Color.black
            SampleLayerView(layer: stream.displayLayer)
            if stream.state != .streaming { connectOverlay }

            // Tag lock box, mapped into the aspect-fit video rect.
            GeometryReader { geo in
                if !follow.normalizedCorners.isEmpty {
                    TagBoxShape(corners: follow.normalizedCorners, fittedRect: fitRect(in: geo.size))
                        .stroke(follow.phase == .following ? Theme.olive : Theme.danger, lineWidth: 2)
                }
            }

            VStack {
                HStack(alignment: .top) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(badge).font(Theme.mono(10, weight: .semibold))
                            .foregroundColor(stream.state == .streaming ? Theme.olive : Theme.faint)
                            .padding(6).background(Color.black.opacity(0.5))
                        if tello.battery >= 0 { telemetryHUD }
                    }
                    Spacer()
                    if follow.isArmed { followHUD }
                }
                Spacer()
                if showManual { manualPad }
                HStack {
                    Spacer()
                    Button { showManual.toggle() } label: {
                        Text(showManual ? "HIDE MANUAL" : "MANUAL").font(Theme.mono(10, weight: .semibold))
                            .foregroundColor(Theme.ink).padding(.horizontal, 10).padding(.vertical, 6)
                            .background(Theme.panel.opacity(0.9)).overlay(Rectangle().stroke(Theme.hairline, lineWidth: 1))
                    }
                }
                if follow.phase == .confirming {
                    confirmBar
                } else {
                    followControls
                }
            }
            .padding(8)
        }
        .onAppear { stream.start() }
        // Keep streaming while following even if the FEED tab is dismissed (the
        // operator may watch the map while the drone follows). Only stop when idle.
        .onDisappear { if !follow.isArmed { stream.stop() } }
        .confirmationDialog("Take off and follow the AprilTag?", isPresented: $confirmArm, titleVisibility: .visible) {
            Button("TAKE OFF & FOLLOW", role: .destructive) { follow.arm(stream: stream) }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("The Tello will launch and station-keep on the tag. Keep clear; STOP lands it.")
        }
        .confirmationDialog("Take off and track the centered object?", isPresented: $confirmTrack, titleVisibility: .visible) {
            Button("TAKE OFF & TRACK", role: .destructive) { follow.armTrack(stream: stream) }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Center the object first. The Tello will launch and visually track it. Keep clear; STOP lands it.")
        }
    }

    // MARK: follow HUD + controls

    private var followHUD: some View {
        VStack(alignment: .trailing, spacing: 2) {
            Text(phaseLabel).font(Theme.mono(11, weight: .bold)).foregroundColor(phaseColor)
            Text(String(format: "DIST %.1fm", follow.distance)).font(Theme.mono(9)).foregroundColor(Theme.faint)
            Text(String(format: "BRG %+.0f°", follow.bearingDeg)).font(Theme.mono(9)).foregroundColor(Theme.faint)
        }
        .padding(6).background(Color.black.opacity(0.55))
    }

    /// Airborne target confirmation: after takeoff the Tello hovers with the lock box
    /// drawn; the operator approves the right target before any follow/track motion.
    private var confirmBar: some View {
        VStack(spacing: 8) {
            Text("TARGET ACQUIRED — CONFIRM?").font(Theme.mono(12, weight: .bold)).foregroundColor(Theme.olive)
            Text(String(format: "Hovering · DIST %.1fm · BRG %+.0f°", follow.distance, follow.bearingDeg))
                .font(Theme.mono(9)).foregroundColor(Theme.faint)
            HStack(spacing: 10) {
                Button { follow.disarmAndLand() } label: {
                    Text("ABORT · LAND").font(Theme.mono(13, weight: .bold))
                        .foregroundColor(.white).frame(maxWidth: .infinity).padding(.vertical, 14)
                        .background(Theme.danger)
                }
                Button { follow.confirmTarget() } label: {
                    Text("CONFIRM").font(Theme.mono(13, weight: .bold))
                        .foregroundColor(.black).frame(maxWidth: .infinity).padding(.vertical, 14)
                        .background(Theme.olive)
                }
            }
        }
        .padding(10).background(Color.black.opacity(0.6))
    }

    private var followControls: some View {
        HStack(spacing: 10) {
            if follow.isArmed {
                Button { follow.disarmAndLand() } label: {
                    Text("STOP · LAND").font(Theme.mono(13, weight: .bold))
                        .foregroundColor(.white).frame(maxWidth: .infinity).padding(.vertical, 14)
                        .background(Theme.danger)
                }
            } else {
                Button { confirmArm = true } label: {
                    Text("FOLLOW TAG").font(Theme.mono(13, weight: .bold))
                        .foregroundColor(.black).frame(maxWidth: .infinity).padding(.vertical, 14)
                        .background(stream.state == .streaming ? Theme.olive : Theme.faint)
                }
                .disabled(stream.state != .streaming)
                Button { confirmTrack = true } label: {
                    Text("TRACK").font(Theme.mono(13, weight: .bold))
                        .foregroundColor(.white).frame(maxWidth: .infinity).padding(.vertical, 14)
                        .background(stream.state == .streaming ? Theme.brown : Theme.faint)
                }
                .disabled(stream.state != .streaming)
            }
        }
    }

    private var telemetryHUD: some View {
        HStack(spacing: 10) {
            Text("BAT \(tello.battery)%").foregroundColor(tello.battery < 20 ? Theme.danger : Theme.olive)
            Text("ALT \(tello.heightCm)cm").foregroundColor(Theme.faint)
            Text("\(tello.tempC)°C").foregroundColor(Theme.faint)
            Text("\(tello.flightTimeS)s").foregroundColor(Theme.faint)
        }
        .font(Theme.mono(9, weight: .semibold))
        .padding(.horizontal, 6).padding(.vertical, 4).background(Color.black.opacity(0.55))
    }

    // Full manual SDK control — every command routes through the same arbiter as voice
    // (pauses follow if active, then executes). Moves 30 cm, yaw 45°.
    private var manualPad: some View {
        VStack(spacing: 4) {
            HStack(spacing: 4) {
                padButton("TAKEOFF", DroneAction(.takeoff), Theme.olive)
                padButton("LAND", DroneAction(.land), Theme.brown)
                padButton("FLIP", DroneAction(.flip))
            }
            HStack(spacing: 4) {
                padButton("⟲ CCW", DroneAction(.rotateCCW, 45))
                padButton("FWD", DroneAction(.forward, 30))
                padButton("⟳ CW", DroneAction(.rotateCW, 45))
            }
            HStack(spacing: 4) {
                padButton("LEFT", DroneAction(.left, 30))
                padButton("BACK", DroneAction(.back, 30))
                padButton("RIGHT", DroneAction(.right, 30))
            }
            HStack(spacing: 4) {
                padButton("UP", DroneAction(.up, 30))
                padButton("DOWN", DroneAction(.down, 30))
                padButton("EMERGENCY", DroneAction(.emergency), Theme.danger)
            }
        }
        .padding(6).background(Color.black.opacity(0.45))
    }

    private func padButton(_ label: String, _ action: DroneAction, _ bg: Color = Theme.panel) -> some View {
        Button { onCommand(action) } label: {
            Text(label).font(Theme.mono(11, weight: .bold))
                .foregroundColor(bg == Theme.danger || bg == Theme.brown ? .white : Theme.ink)
                .frame(maxWidth: .infinity, minHeight: 40).background(bg.opacity(0.92))
                .overlay(Rectangle().stroke(Theme.hairline, lineWidth: 1))
        }
    }

    private var phaseLabel: String {
        switch follow.phase {
        case .disarmed: return "DISARMED"
        case .searching: return "● SEARCHING"
        case .confirming: return "◆ CONFIRM TARGET?"
        case .following: return "● FOLLOWING"
        case .lost: return "○ TAG LOST"
        case .manual: return "✋ MANUAL · say “follow me”"
        }
    }
    private var phaseColor: Color {
        switch follow.phase {
        case .following: return Theme.olive
        case .lost: return Theme.danger
        case .manual, .confirming: return Theme.brown
        default: return Theme.faint
        }
    }

    /// Aspect-fit rect for the 4:3 video inside the view (matches resizeAspect).
    private func fitRect(in size: CGSize) -> CGRect {
        guard size.width > 0, size.height > 0 else { return .zero }
        let viewAspect = size.width / size.height
        if viewAspect > videoAspect {
            let w = size.height * videoAspect
            return CGRect(x: (size.width - w) / 2, y: 0, width: w, height: size.height)
        } else {
            let h = size.width / videoAspect
            return CGRect(x: 0, y: (size.height - h) / 2, width: size.width, height: h)
        }
    }

    private var badge: String {
        switch stream.state {
        case .streaming: return "● TELLO LIVE"
        case .connecting: return "○ CONNECTING…"
        case .error(let e): return "FAULT: \(e)"
        case .idle: return "○ TELLO"
        }
    }

    private var connectOverlay: some View {
        VStack(spacing: 8) {
            Text(badge).font(Theme.mono(13, weight: .semibold)).foregroundColor(Theme.faint)
            Text("join the Tello WiFi (TELLO-XXXXXX)").font(Theme.mono(9)).foregroundColor(Theme.faint)
        }
    }
}

/// Draws the detected tag's quad from normalized (0…1) corners into the video rect.
struct TagBoxShape: Shape {
    let corners: [CGPoint]
    let fittedRect: CGRect
    func path(in rect: CGRect) -> Path {
        var path = Path()
        guard corners.count == 4, fittedRect.width > 0 else { return path }
        let pts = corners.map { CGPoint(x: fittedRect.minX + $0.x * fittedRect.width,
                                        y: fittedRect.minY + $0.y * fittedRect.height) }
        path.addLines(pts)
        path.closeSubpath()
        return path
    }
}
