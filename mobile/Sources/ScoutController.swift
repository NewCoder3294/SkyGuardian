import Foundation

/// Soldier-COMMANDED, bounded scout maneuver for the companion Tello.
///
/// On the soldier's command the pet leaves the follow to explore ahead in a few
/// short legs, rotating to scan the area at each, then **retraces its exact path**
/// (every recorded move reversed and inverted) back to the soldier and resumes
/// following. Soldier-directed and bounded — NOT autonomous pursuit.
///
/// Hardware note: the basic Tello has no forward obstacle sensor (only a downward
/// ToF), so the explore is bounded by leg count, not wall detection. Discrete Tello
/// SDK moves (`forward/back/cw/ccw <n>`) are self-limiting, and any small drift in
/// the retrace is corrected when the follow loop re-acquires the soldier's tag.
///
/// Safety: LAND/STOP (FollowCoordinator.disarmAndLand / emergencyCut) preempt at any
/// time; a run is fully bounded in distance, rotation, and time.

/// One step of the maneuver: a raw Tello SDK command (nil = hover/scan hold), how
/// long to wait before the next step, and whether we're retracing home yet.
struct ScoutStep: Equatable {
    let command: String?
    let waitSeconds: Double
    let isReturn: Bool
}

enum Scout {
    static let minLegCm = 20
    static let maxLegCm = 150          // demo-safe per-leg cap (SDK allows up to 500)
    static let maxLegs = 4
    static let maxTurnDeg = 90
    static let maxScanDeg = 60

    /// Build the bounded explore→scan→retrace step sequence. Pure and deterministic
    /// (unit-testable, no hardware). `moveSpeedCmPerSec`/`rotSpeedDegPerSec` are
    /// conservative estimates used only to size the wait between discrete moves.
    static func plan(legCm: Int, legs: Int, turnDeg: Int, scanDeg: Int,
                     scanSeconds: Double, speedCmPerSec: Int,
                     moveSpeedCmPerSec: Double = 40.0,
                     rotSpeedDegPerSec: Double = 45.0) -> [ScoutStep] {
        let cm = max(minLegCm, min(maxLegCm, legCm))
        let nLegs = max(1, min(maxLegs, legs))
        let turn = max(0, min(maxTurnDeg, turnDeg))
        let scan = max(0, min(maxScanDeg, scanDeg))
        let hold = max(0.0, scanSeconds)
        let spd = max(10, min(100, speedCmPerSec))

        func legWait() -> Double { Double(cm) / moveSpeedCmPerSec + 2.0 }
        func rotWait(_ d: Int) -> Double { Double(d) / rotSpeedDegPerSec + 1.5 }

        var steps: [ScoutStep] = []
        // Net-displacement moves to retrace (outbound forwards + turns); scans net to
        // zero rotation and are NOT recorded.
        var path: [(inverse: String, wait: Double)] = []

        // Set a brisk discrete-move speed first (not part of the path).
        steps.append(ScoutStep(command: "speed \(spd)", waitSeconds: 0.4, isReturn: false))

        for leg in 0..<nLegs {
            if leg > 0 && turn > 0 {
                steps.append(ScoutStep(command: "cw \(turn)", waitSeconds: rotWait(turn), isReturn: false))
                path.append((inverse: "ccw \(turn)", wait: rotWait(turn)))
            }
            steps.append(ScoutStep(command: "forward \(cm)", waitSeconds: legWait(), isReturn: false))
            path.append((inverse: "back \(cm)", wait: legWait()))

            // Scan the area: look right, sweep left, recenter — net zero rotation so
            // heading (and thus the retrace) is preserved.
            if scan > 0 {
                steps.append(ScoutStep(command: "cw \(scan)", waitSeconds: rotWait(scan), isReturn: false))
                steps.append(ScoutStep(command: "ccw \(2 * scan)", waitSeconds: rotWait(2 * scan), isReturn: false))
                steps.append(ScoutStep(command: "cw \(scan)", waitSeconds: rotWait(scan), isReturn: false))
            }
            steps.append(ScoutStep(command: nil, waitSeconds: hold, isReturn: false))   // scan hold (hover)
        }

        // Retrace: replay the path in reverse, each move inverted → returns to origin
        // and original heading.
        for move in path.reversed() {
            steps.append(ScoutStep(command: move.inverse, waitSeconds: move.wait, isReturn: true))
        }
        return steps
    }
}

@MainActor
final class ScoutController: ObservableObject {
    enum State: Equatable { case idle, scouting, returning }

    @Published private(set) var state: State = .idle

    // Bounded defaults: 2 legs × ~1.2 m with a 30° turn between, scanning ±30° at
    // each, ~2 s hold. Explores ~2.4 m then retraces home.
    var legCm: Int = 120
    var legs: Int = 2
    var turnDeg: Int = 30
    var scanDeg: Int = 30
    var scanSeconds: Double = 2.0
    var speedCmPerSec: Int = 60

    /// Rough total outbound distance (m) for UI copy.
    var approxReachM: Int { (legCm * legs) / 100 }

    private weak var follow: FollowCoordinator?
    private var workItems: [DispatchWorkItem] = []

    var isRunning: Bool { state != .idle }

    /// Begin the maneuver. No-op unless airborne under follow control and not already scouting.
    func start(follow: FollowCoordinator) {
        guard !isRunning, follow.isArmed else { return }
        self.follow = follow
        state = .scouting
        follow.beginScript()                         // hand the channel to the maneuver

        let steps = Scout.plan(legCm: legCm, legs: legs, turnDeg: turnDeg, scanDeg: scanDeg,
                               scanSeconds: scanSeconds, speedCmPerSec: speedCmPerSec)
        var delay = 0.0
        for step in steps {
            let item = DispatchWorkItem { [weak self] in
                guard let self, self.isRunning, self.follow?.isArmed == true else { return }
                if step.isReturn && self.state != .returning { self.state = .returning }
                if let cmd = step.command { TelloCommander.shared.send(cmd) }
            }
            workItems.append(item)
            DispatchQueue.main.asyncAfter(deadline: .now() + delay, execute: item)
            delay += step.waitSeconds
        }

        let finish = DispatchWorkItem { [weak self] in
            guard let self else { return }
            if self.follow?.isArmed == true { self.follow?.resumeFollow() }
            self.state = .idle
        }
        workItems.append(finish)
        DispatchQueue.main.asyncAfter(deadline: .now() + delay, execute: finish)
    }

    /// Cancel immediately and hand control back to the follow loop (steady hover).
    /// LAND/STOP callers run disarmAndLand right after, which supersedes this.
    func abort() {
        workItems.forEach { $0.cancel() }
        workItems.removeAll()
        state = .idle
        follow?.resumeFollow()
    }
}
