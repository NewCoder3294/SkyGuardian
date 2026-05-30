import CoreVideo
import Foundation
import QuartzCore

/// Runs the autonomous follow loop on the phone: decode tap → AprilTag detection →
/// FollowController → `rc` stick commands to the Tello, at a fixed cadence decoupled
/// from the (slower, variable) detection rate. Safety first: explicit arm/takeoff,
/// hover when the tag is lost, and an automatic land if it stays lost.
final class FollowCoordinator: ObservableObject {
    enum Phase: Equatable { case disarmed, searching, following, lost, manual }

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
    private var lastDetect: CFTimeInterval = 0       // cadence cap (in addition to busy gate)
    private let detectInterval: CFTimeInterval = 0.08  // ~12 Hz cap — leaves thermal headroom

    // Control state — only touched on rcQueue.
    private var latest: TagDetection?
    private var latestTime: CFTimeInterval = 0
    private var armed = false          // airborne under our control
    private var followActive = false   // running the follow loop (false = manual hover)
    private var tookOff = false        // takeoff climb has settled (gate follow rc)
    private var landing = false        // lost-land in progress (fire once)
    private let takeoffSettle: CFTimeInterval = 4.0   // let the takeoff climb finish before follow rc

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
        stream.start()   // make sure video/detection is flowing (idempotent)
        controller.config = config
        let size = tagSizeMeters
        detectQueue.async { self.detector.tagSizeMeters = size }   // mutate detector only on its queue
        stream.onPixelBuffer = { [weak self] pb in self?.ingest(pb) }

        TelloCommander.shared.send("takeoff")
        rcQueue.async {
            self.armed = true
            self.followActive = true
            self.tookOff = false
            self.landing = false
            self.latest = nil
            self.latestTime = CACurrentMediaTime()   // grace period before lost-land
            // Hold off follow rc until the multi-second takeoff climb settles, so
            // autonomous sticks never fight the takeoff.
            self.rcQueue.asyncAfter(deadline: .now() + self.takeoffSettle) {
                self.tookOff = true
                self.latestTime = CACurrentMediaTime()
            }
        }
        setPhase(.searching)
        startRCLoop()
    }

    /// Operator took manual control by voice — pause the follow loop and hover. The
    /// drone stays airborne; "follow me" resumes. (Pause-and-hold model.)
    func pauseToManual() {
        guard isArmed else { return }
        TelloCommander.shared.rc(.hover)            // neutralize follow motion
        rcQueue.async { self.followActive = false }
        setPhase(.manual)
    }

    /// Resume autonomous following after a manual takeover.
    func resumeFollow() {
        guard isArmed else { return }
        rcQueue.async {
            self.followActive = true
            self.landing = false
            self.tookOff = true            // already airborne — no settle delay needed
            self.latest = nil
            self.latestTime = CACurrentMediaTime()  // fresh grace before lost-land
        }
        setPhase(.searching)
    }

    /// Stop following and land. Safe to call any time.
    func disarmAndLand() {
        stream?.onPixelBuffer = nil
        rcQueue.async {                    // rcTimer + control state are rcQueue-owned
            self.rcTimer?.cancel(); self.rcTimer = nil
            self.armed = false; self.followActive = false
        }
        TelloCommander.shared.rc(.hover)
        TelloCommander.shared.send("land")
        setPhase(.disarmed)
        DispatchQueue.main.async { self.normalizedCorners = [] }
    }

    /// Emergency motor cut — stop the loop and cut motors immediately, with NO
    /// graceful land. Use for a real failsafe, not a normal stop.
    func emergencyCut() {
        stream?.onPixelBuffer = nil
        rcQueue.async {
            self.rcTimer?.cancel(); self.rcTimer = nil
            self.armed = false; self.followActive = false
        }
        TelloCommander.shared.send("emergency")
        setPhase(.disarmed)
        DispatchQueue.main.async { self.normalizedCorners = [] }
    }

    // MARK: detection (backpressured — drop frames while busy)

    private func ingest(_ pixelBuffer: CVPixelBuffer) {
        let now = CACurrentMediaTime()
        detLock.lock()
        if busy || now - lastDetect < detectInterval { detLock.unlock(); return }
        busy = true
        lastDetect = now
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
        guard armed, followActive, !landing else { return }   // manual takeover / landing → no follow rc
        guard tookOff else { return }                         // takeoff climb still settling
        let now = CACurrentMediaTime()
        let age = now - latestTime
        let fresh = age < staleTimeout && latest != nil
        let tag = fresh ? latest : nil

        if fresh {
            TelloCommander.shared.rc(controller.command(for: tag))
            setPhase(.following)
        } else if age > lostLandTimeout {
            // Lost too long — land once for safety (stop the loop on this very tick).
            landing = true
            rcTimer?.cancel(); rcTimer = nil
            DispatchQueue.main.async { self.disarmAndLand() }
        } else {
            TelloCommander.shared.rc(controller.command(for: nil))   // hover while searching
            setPhase(.lost)
        }
    }

    private func setPhase(_ p: Phase) {
        DispatchQueue.main.async { if self.phase != p { self.phase = p } }
    }
}
