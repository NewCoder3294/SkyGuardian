import Foundation

/// Soldier-COMMANDED, bounded scout maneuver for the companion Tello.
///
/// On the soldier's command the pet briefly leaves the follow to scout ahead, then
/// returns and resumes following. This is soldier-directed and bounded — NOT
/// autonomous targeting (consistent with the recon/SA mission: no pursuit).
///
/// Mechanics: pause the follow loop (hover), issue a discrete forward SDK move
/// (self-bounded by the Tello), hold to scan, issue the mirror return move, then
/// resume following. Distances use the Tello SDK's `forward/back <cm>` discrete
/// commands (20–500 cm), so each leg is self-limiting even if a timer is late.
///
/// Safety: LAND/STOP (FollowCoordinator.disarmAndLand / emergencyCut) preempt at
/// any time; the controller aborts if the drone is no longer armed, and a single
/// run is fully bounded in distance and time.

/// One step of the maneuver: a raw Tello SDK command to send (nil = just hover and
/// wait, e.g. the scan hold), and how long to wait before the next step.
struct ScoutStep: Equatable {
    let command: String?
    let waitSeconds: Double
}

enum Scout {
    /// Tello SDK discrete-move bounds (cm). Distances are clamped into this range.
    static let minCm = 20
    static let maxCm = 200          // demo-safe cap, well under the SDK's 500

    /// Build the bounded step sequence: forward → scan-hold → back. Pure and
    /// deterministic so it can be unit-tested without hardware.
    /// `legSpeedCmPerSec` is a conservative estimate of the Tello's move speed used
    /// only to size the wait between discrete moves (the move itself is bounded by
    /// the SDK, not the timer).
    static func plan(forwardCm: Int, scanSeconds: Double,
                     legSpeedCmPerSec: Double = 40.0) -> [ScoutStep] {
        let cm = max(minCm, min(maxCm, forwardCm))
        let scan = max(0.0, scanSeconds)
        // Conservative: time to travel the leg + a fixed settle margin.
        let legWait = Double(cm) / max(1.0, legSpeedCmPerSec) + 2.0
        return [
            ScoutStep(command: "forward \(cm)", waitSeconds: legWait),
            ScoutStep(command: nil, waitSeconds: scan),          // scan-hold (hover)
            ScoutStep(command: "back \(cm)", waitSeconds: legWait),
        ]
    }
}

@MainActor
final class ScoutController: ObservableObject {
    enum State: Equatable { case idle, scouting, returning }

    @Published private(set) var state: State = .idle

    /// Default maneuver: scout ~1.5 m ahead, scan 2 s, return. Bounded.
    var forwardCm: Int = 150
    var scanSeconds: Double = 2.0

    private weak var follow: FollowCoordinator?
    private var workItems: [DispatchWorkItem] = []

    var isRunning: Bool { state != .idle }

    /// Begin the maneuver. No-op unless the drone is airborne under follow control
    /// and not already scouting.
    func start(follow: FollowCoordinator) {
        guard !isRunning, follow.isArmed else { return }
        self.follow = follow
        state = .scouting

        follow.pauseToManual()                       // stop follow ticks, hover

        let steps = Scout.plan(forwardCm: forwardCm, scanSeconds: scanSeconds)
        var delay = 0.0
        for (i, step) in steps.enumerated() {
            let isReturnLeg = i == steps.count - 1
            let item = DispatchWorkItem { [weak self] in
                guard let self, self.isRunning, self.follow?.isArmed == true else { return }
                if isReturnLeg { self.state = .returning }
                if let cmd = step.command { TelloCommander.shared.send(cmd) }
            }
            workItems.append(item)
            DispatchQueue.main.asyncAfter(deadline: .now() + delay, execute: item)
            delay += step.waitSeconds
        }

        // After the final leg completes, resume following.
        let finish = DispatchWorkItem { [weak self] in
            guard let self else { return }
            if self.follow?.isArmed == true { self.follow?.resumeFollow() }
            self.state = .idle
        }
        workItems.append(finish)
        DispatchQueue.main.asyncAfter(deadline: .now() + delay, execute: finish)
    }

    /// Cancel the maneuver immediately. The caller (LAND/STOP) handles the drone;
    /// this just stops issuing further scout commands and clears state.
    func abort() {
        workItems.forEach { $0.cancel() }
        workItems.removeAll()
        state = .idle
    }
}
