import CoreVideo
import Foundation
import QuartzCore

/// Runs the autonomous follow loop on the phone: decode tap → AprilTag detection →
/// FollowController → `rc` stick commands to the Tello, at a fixed cadence decoupled
/// from the (slower, variable) detection rate. Safety first: explicit arm/takeoff,
/// hover when the tag is lost, and an automatic land if it stays lost.
final class FollowCoordinator: ObservableObject {
    enum Phase: Equatable {
        case disarmed, searching, confirming, following, lost, manual

        /// Lowercase wire label shared with the backend FollowState.phase contract.
        var label: String {
            switch self {
            case .disarmed: return "disarmed"
            case .searching: return "searching"
            case .confirming: return "confirming"
            case .following: return "following"
            case .lost: return "lost"
            case .manual: return "manual"
            }
        }
    }

    @Published private(set) var phase: Phase = .disarmed
    @Published private(set) var distance: Double = 0          // meters to the tag
    @Published private(set) var bearingDeg: Double = 0
    @Published private(set) var normalizedCorners: [CGPoint] = []   // 0…1 in image space

    /// Printed hat-tag edge length (meters). Set before arming to match the print.
    var tagSizeMeters: Double = 0.16
    var config = FollowConfig()

    private let detector = AprilTagDetector()
    private let tracker = ObjectTracker()
    enum Mode { case tag, track }
    private var mode: Mode = .tag   // control state — only touched on rcQueue (see ":51")

    private var controller = FollowController()

    private let detectQueue = DispatchQueue(label: "follow.detect", qos: .userInitiated)
    private let rcQueue = DispatchQueue(label: "follow.rc")
    private var rcTimer: DispatchSourceTimer?

    private let detLock = NSLock()
    private var busy = false                         // detection backpressure
    private var lastDetect: CFTimeInterval = 0       // cadence cap (in addition to busy gate)
    private let detectInterval: CFTimeInterval = 0.10  // ~10 Hz cap — frees CPU for smooth video

    // Control state — only touched on rcQueue.
    private var latest: TagDetection?
    private var latestTime: CFTimeInterval = 0
    private var armed = false          // airborne under our control
    private var followActive = false   // running the follow loop (false = manual hover)
    private var tookOff = false        // takeoff climb has settled (gate follow rc)
    private var tookOffAt: CFTimeInterval = 0   // when the climb settled (confirm timeout base)
    private var confirmed = false      // operator approved the locked target (gate follow rc)
    private var landing = false        // lost-land in progress (fire once)
    private var manualHover = false    // manual takeover: stream a steady hover (not dead air)
    private var scripted = false       // a scripted maneuver (e.g. scout) owns the channel; loop yields
    private let takeoffSettle: CFTimeInterval = 4.0   // let the takeoff climb finish before follow rc
    private let confirmTimeout: CFTimeInterval = 30.0 // auto-land if the operator never confirms

    private let rcInterval = 0.066                   // ~15 Hz stick updates
    private let staleTimeout: CFTimeInterval = 1.5   // ride through tag losses for continuity (loose)
    private let lostLandTimeout: CFTimeInterval = 45 // hover (don't land) this long w/o tag — generous

    private weak var stream: TelloDirectStream?

    // Injected for testability; production defaults wire the real singletons/clock.
    private let commands: DroneCommandSink
    private let now: () -> CFTimeInterval

    /// Synchronous mirror of `phase` (the @Published one updates on the main queue
    /// asynchronously). Tests read this immediately after driving the loop.
    private(set) var currentPhase: Phase = .disarmed

    init(commands: DroneCommandSink = TelloCommander.shared,
         now: @escaping () -> CFTimeInterval = { CACurrentMediaTime() }) {
        self.commands = commands
        self.now = now
    }

    /// Optional sink for operator label decisions (data flywheel). Wired by the app
    /// to WorldClient.sendLabelEvent; nil in tests.
    var onLabel: ((_ kind: String, _ label: String?) -> Void)?

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

        commands.send("takeoff")
        rcQueue.async {
            self.mode = .tag         // AprilTag follow; reset so we don't inherit a prior .track arm
            self.armed = true
            self.followActive = true
            self.tookOff = false
            self.confirmed = false   // operator must confirm the locked target before follow rc
            self.landing = false
            self.latest = nil
            self.latestTime = self.now()   // grace period before lost-land
            // Hold off follow rc until the multi-second takeoff climb settles, so
            // autonomous sticks never fight the takeoff.
            self.rcQueue.asyncAfter(deadline: .now() + self.takeoffSettle) {
                self.tookOff = true
                self.tookOffAt = self.now()
                self.latest = nil   // re-acquire fresh at hover; don't confirm on a climb-stale lock
                self.latestTime = self.now()
                if self.mode == .track {
                    // Re-lock the visual tracker on the hover-height view — the
                    // ground-level lock taken at arm time may not survive the climb.
                    self.detectQueue.async { self.tracker.reset() }
                }
            }
        }
        setPhase(.searching)
        startRCLoop()
    }

    /// Take off and visually track whatever the operator has centered ("track that
    /// boat") — no AprilTag. Same loop/arbiter; the on-device tracker replaces the tag
    /// detector as the source of the target.
    func armTrack(stream: TelloDirectStream) {
        guard phase == .disarmed else { return }
        self.stream = stream
        stream.start()
        controller.config = config
        detectQueue.async { self.tracker.reset() }
        stream.onPixelBuffer = { [weak self] pb in self?.ingest(pb) }

        commands.send("takeoff")
        rcQueue.async {
            self.mode = .track       // visual tracker is the target source (set on rcQueue, the owner)
            self.armed = true
            self.followActive = true
            self.tookOff = false
            self.confirmed = false   // operator must confirm the locked target before track rc
            self.landing = false
            self.latest = nil
            self.latestTime = self.now()
            self.rcQueue.asyncAfter(deadline: .now() + self.takeoffSettle) {
                self.tookOff = true
                self.tookOffAt = self.now()
                self.latest = nil   // re-acquire fresh at hover; don't confirm on a climb-stale lock
                self.latestTime = self.now()
                if self.mode == .track {
                    // Re-lock the visual tracker on the hover-height view — the
                    // ground-level lock taken at arm time may not survive the climb.
                    self.detectQueue.async { self.tracker.reset() }
                }
            }
        }
        setPhase(.searching)
        startRCLoop()
    }

    /// Re-acquire the centered object (operator re-frames and says "track" again).
    func relock() { detectQueue.async { self.tracker.reset() } }

    /// Operator took manual control by voice — pause the follow loop and hover. The
    /// drone stays airborne; "follow me" resumes. (Pause-and-hold model.)
    func pauseToManual() {
        guard isArmed else { return }
        // Keep the rc loop ALIVE but switch it to a steady hover stream (manualHover).
        // Previously this cancelled the timer, leaving the Tello with no rc — it then
        // coasted on its last command (drift) and felt unresponsive. A continuous
        // hover is the correct, stable manual hold.
        rcQueue.async { self.followActive = false; self.manualHover = true }
        commands.rc(.hover)            // immediate neutralize; loop sustains it
        setPhase(.manual)
    }

    /// Hand the rc channel to a scripted maneuver (e.g. scout). The follow loop
    /// yields (sends no hover ticks) so the maneuver's discrete moves run
    /// uncontested; the Tello auto-hovers between discrete moves. resumeFollow()
    /// or a land restores normal follow control.
    func beginScript() {
        guard isArmed else { return }
        rcQueue.async { self.followActive = false; self.manualHover = false; self.scripted = true }
        setPhase(.manual)
    }

    /// Resume autonomous following after a manual takeover.
    func resumeFollow() {
        guard isArmed else { return }
        rcQueue.async {
            self.followActive = true
            self.manualHover = false       // leave the steady-hover hold, resume follow ticks
            self.scripted = false          // any scripted maneuver is over
            self.landing = false
            self.tookOff = true            // already airborne — no settle delay needed
            self.confirmed = true          // target was confirmed before the takeover; don't re-confirm
            self.latest = nil
            self.latestTime = self.now()  // fresh grace before lost-land
        }
        setPhase(.searching)
        startRCLoop()                      // idempotent: restart the timer if it isn't running
    }

    /// Stop following and land. Safe to call any time.
    func disarmAndLand() {
        // Neutralize + land immediately on the caller thread — the failsafe must not
        // wait on the rcQueue. The state teardown that follows is serialized on rcQueue.
        commands.rc(.hover)
        commands.send("land")
        let s = stream
        rcQueue.async {                    // rcTimer + control state are rcQueue-owned
            self.rcTimer?.cancel(); self.rcTimer = nil
            s?.onPixelBuffer = nil         // stop feeding ingest before clearing mode/tracker
            self.mode = .tag
            self.armed = false; self.followActive = false; self.confirmed = false
            self.manualHover = false; self.scripted = false
            self.detectQueue.async { self.tracker.reset() }
        }
        setPhase(.disarmed)
        DispatchQueue.main.async { self.normalizedCorners = [] }
    }

    /// Emergency motor cut — stop the loop and cut motors immediately, with NO
    /// graceful land. Use for a real failsafe, not a normal stop.
    func emergencyCut() {
        // Cut motors immediately on the caller thread — the failsafe must not wait on
        // the rcQueue. The state teardown that follows is serialized on rcQueue.
        commands.send("emergency")
        let s = stream
        rcQueue.async {
            self.rcTimer?.cancel(); self.rcTimer = nil
            s?.onPixelBuffer = nil         // stop feeding ingest before clearing mode/tracker
            self.mode = .tag
            self.armed = false; self.followActive = false; self.confirmed = false
            self.detectQueue.async { self.tracker.reset() }
        }
        setPhase(.disarmed)
        DispatchQueue.main.async { self.normalizedCorners = [] }
    }

    // MARK: detection (backpressured — drop frames while busy)

    private func ingest(_ pixelBuffer: CVPixelBuffer) {
        let t = now()
        detLock.lock()
        if busy || t - lastDetect < detectInterval { detLock.unlock(); return }
        busy = true
        lastDetect = t
        detLock.unlock()

        // Snapshot `mode` on its owning queue (rcQueue) before doing detection work, so
        // the detect path never reads the cross-thread control state directly.
        rcQueue.async { [weak self] in
            guard let self else { return }
            let mode = self.mode
            self.detectQueue.async { [weak self] in
                guard let self else { return }
                let synth: TagDetection?
                if mode == .track {
                    synth = self.trackStep(pixelBuffer)         // publishes its own box
                } else {
                    let best = self.pickTarget(self.detector.detect(pixelBuffer))
                    self.publish(best)
                    synth = best
                }
                self.rcQueue.async {
                    if let synth {
                        self.latest = synth
                        self.latestTime = self.now()
                    }
                }
                self.detLock.lock(); self.busy = false; self.detLock.unlock()
            }
        }
    }

    /// Run the visual tracker and synthesize a TagDetection so the existing controller
    /// (gains/deadbands/clamps/lost handling) drives the drone unchanged. Apparent box
    /// size is the standoff proxy — hold the size it had at lock.
    private func trackStep(_ pb: CVPixelBuffer) -> TagDetection? {
        if !tracker.isLocked { tracker.lock(in: pb) }
        guard let (box, conf) = tracker.update(in: pb) else {
            DispatchQueue.main.async { self.normalizedCorners = [] }
            return nil
        }
        // Vision box: bottom-left origin, normalized → top-left corners for the overlay.
        let x0 = box.minX, x1 = box.maxX, yTop = 1 - box.maxY, yBot = 1 - box.minY
        let corners = [CGPoint(x: x0, y: yTop), CGPoint(x: x1, y: yTop),
                       CGPoint(x: x1, y: yBot), CGPoint(x: x0, y: yBot)]
        let bearingDeg = (Double(box.midX) - 0.5) * 72.0     // HFOV ~72°
        let elevationDeg = (0.5 - Double(box.midY)) * 54.0   // +up in Vision → climb
        let h = max(Double(box.height), 0.02)
        let lockedH = max(Double(tracker.lockedHeight), 0.02)
        let distance = min(max(config.targetDistance * (lockedH / h), 0.5), 10.0)
        DispatchQueue.main.async {
            self.normalizedCorners = corners
            self.distance = distance
            self.bearingDeg = bearingDeg
        }
        return TagDetection(id: -1, center: .zero, corners: [], distance: distance,
                            bearingRad: bearingDeg * .pi / 180, elevationRad: elevationDeg * .pi / 180,
                            decisionMargin: Float(conf * 100), imageSize: .zero)
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
        guard armed, !landing else { return }
        // A scripted maneuver (e.g. scout) drives the channel with its own discrete
        // moves — yield so hover ticks don't fight it.
        if scripted { return }
        // Solid control: stream a steady stick command in EVERY armed state. The
        // Tello holds its last rc until the next one, so any gap makes it coast on a
        // stale command (drift) and ignore the operator (unresponsive). During the
        // takeoff climb and during a manual takeover we stream a true hover rather
        // than going silent.
        if !tookOff || manualHover {
            commands.rc(.hover)
            return
        }
        let t = now()
        let age = t - latestTime
        let fresh = age < staleTimeout && latest != nil
        let tag = fresh ? latest : nil

        // Target-confirmation gate: after takeoff the drone HOVERS and shows the lock
        // for the operator to approve. No follow/track rc is sent until confirmTarget().
        if !confirmed {
            commands.rc(.hover)
            if t - tookOffAt > confirmTimeout {
                // Operator never confirmed — land for safety rather than hover forever.
                landing = true
                rcTimer?.cancel(); rcTimer = nil
                DispatchQueue.main.async { self.disarmAndLand() }
            } else {
                setPhase(fresh ? .confirming : .searching)
            }
            return
        }

        if fresh {
            commands.rc(controller.command(for: tag))
            setPhase(.following)
        } else if age > lostLandTimeout {
            // Lost too long — land once for safety (stop the loop on this very tick).
            landing = true
            rcTimer?.cancel(); rcTimer = nil
            DispatchQueue.main.async { self.disarmAndLand() }
        } else {
            commands.rc(controller.command(for: nil))   // hover while searching
            setPhase(.lost)
        }
    }

    /// Operator approved the locked target → release the follow/track loop. Only
    /// meaningful while in the .confirming/.searching pre-confirm hover.
    func confirmTarget() {
        rcQueue.async {
            guard self.armed, !self.confirmed else { return }
            self.confirmed = true
            self.latestTime = self.now()   // fresh grace as following begins
            // Emit the label only on a genuine first confirm (inside the guard),
            // so re-tapping CONFIRM can't record a duplicate true-positive.
            DispatchQueue.main.async { self.onLabel?("confirm", nil) }
        }
        setPhase(.searching)
    }

    private func setPhase(_ p: Phase) {
        currentPhase = p
        DispatchQueue.main.async { if self.phase != p { self.phase = p } }
    }

    // MARK: test seams (internal — used by FollowCoordinatorTests via @testable)

    /// Drive one rc-loop tick synchronously (the production timer calls `tick()`).
    func tickForTest() { tick() }

    /// Inject a detection as if the detector produced it, `age` seconds ago.
    func injectDetectionForTest(_ d: TagDetection?, age: CFTimeInterval = 0) {
        latest = d
        latestTime = now() - age
    }
}
