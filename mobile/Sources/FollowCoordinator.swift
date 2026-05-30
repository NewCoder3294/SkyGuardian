import CoreVideo
import Foundation
import QuartzCore

/// Runs the autonomous follow loop on the phone: decode tap → AprilTag detection →
/// FollowController → `rc` stick commands to the Tello, at a fixed cadence decoupled
/// from the (slower, variable) detection rate. Safety first: explicit arm/takeoff,
/// hover when the tag is lost, and an automatic land if it stays lost.
final class FollowCoordinator: ObservableObject {
    enum Phase: Equatable { case disarmed, searching, following, lost }

    @Published private(set) var phase: Phase = .disarmed
    @Published private(set) var distance: Double = 0          // meters to the tag
    @Published private(set) var bearingDeg: Double = 0
    @Published private(set) var normalizedCorners: [CGPoint] = []   // 0…1 in image space

    /// Printed hat-tag edge length (meters). Set before arming to match the print.
    var tagSizeMeters: Double = 0.16
    var config = FollowConfig()

    private let detector = AprilTagDetector()
    private var controller = FollowController()

    private let detectQueue = DispatchQueue(label: "follow.detect", qos: .userInitiated)
    private let rcQueue = DispatchQueue(label: "follow.rc")
    private var rcTimer: DispatchSourceTimer?

    private let detLock = NSLock()
    private var busy = false                         // detection backpressure

    // Control state — only touched on rcQueue.
    private var latest: TagDetection?
    private var latestTime: CFTimeInterval = 0
    private var armed = false

    private let rcInterval = 0.066                   // ~15 Hz stick updates
    private let staleTimeout: CFTimeInterval = 0.5   // older detection = no lock
    private let lostLandTimeout: CFTimeInterval = 8  // hover this long w/o tag, then land

    private weak var stream: TelloDirectStream?

    var isArmed: Bool { phase != .disarmed }

    // MARK: arm / disarm

    /// Take off and begin following. The caller is responsible for confirming intent
    /// (this launches a real drone).
    func arm(stream: TelloDirectStream) {
        guard phase == .disarmed else { return }
        self.stream = stream
        detector.tagSizeMeters = tagSizeMeters
        controller.config = config
        stream.onPixelBuffer = { [weak self] pb in self?.ingest(pb) }

        TelloCommander.shared.send("takeoff")
        rcQueue.async {
            self.armed = true
            self.latest = nil
            self.latestTime = CACurrentMediaTime()   // grace period before lost-land
        }
        setPhase(.searching)
        startRCLoop()
    }

    /// Stop following and land. Safe to call any time.
    func disarmAndLand() {
        stream?.onPixelBuffer = nil
        rcTimer?.cancel(); rcTimer = nil
        rcQueue.async { self.armed = false }
        TelloCommander.shared.rc(.hover)
        TelloCommander.shared.send("land")
        setPhase(.disarmed)
        DispatchQueue.main.async { self.normalizedCorners = [] }
    }

    // MARK: detection (backpressured — drop frames while busy)

    private func ingest(_ pixelBuffer: CVPixelBuffer) {
        detLock.lock()
        if busy { detLock.unlock(); return }
        busy = true
        detLock.unlock()

        detectQueue.async { [weak self] in
            guard let self else { return }
            let best = self.pickTarget(self.detector.detect(pixelBuffer))
            self.rcQueue.async {
                if let best {
                    self.latest = best
                    self.latestTime = CACurrentMediaTime()
                }
            }
            self.publish(best)
            self.detLock.lock(); self.busy = false; self.detLock.unlock()
        }
    }

    /// Strongest detection wins (highest decision margin) above the confidence floor.
    private func pickTarget(_ dets: [TagDetection]) -> TagDetection? {
        dets.filter { $0.decisionMargin >= config.minDecisionMargin }
            .max { $0.decisionMargin < $1.decisionMargin }
    }

    private func publish(_ tag: TagDetection?) {
        let corners: [CGPoint]
        if let tag, tag.imageSize.width > 0 {
            corners = tag.corners.map { CGPoint(x: $0.x / tag.imageSize.width,
                                                y: $0.y / tag.imageSize.height) }
        } else {
            corners = []
        }
        DispatchQueue.main.async {
            self.normalizedCorners = corners
            if let tag { self.distance = tag.distance; self.bearingDeg = tag.bearingRad * 180 / .pi }
        }
    }

    // MARK: rc loop (fixed cadence on rcQueue)

    private func startRCLoop() {
        rcTimer?.cancel()
        let t = DispatchSource.makeTimerSource(queue: rcQueue)
        t.schedule(deadline: .now() + rcInterval, repeating: rcInterval)
        t.setEventHandler { [weak self] in self?.tick() }
        rcTimer = t
        t.resume()
    }

    private func tick() {
        guard armed else { return }
        let now = CACurrentMediaTime()
        let age = now - latestTime
        let fresh = age < staleTimeout && latest != nil
        let tag = fresh ? latest : nil

        TelloCommander.shared.rc(controller.command(for: tag))

        if fresh {
            setPhase(.following)
        } else if age > lostLandTimeout {
            // Lost too long — land for safety and disarm.
            DispatchQueue.main.async { self.disarmAndLand() }
        } else {
            setPhase(.lost)
        }
    }

    private func setPhase(_ p: Phase) {
        DispatchQueue.main.async { if self.phase != p { self.phase = p } }
    }
}
