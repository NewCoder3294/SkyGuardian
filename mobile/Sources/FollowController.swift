import Foundation

/// A Tello `rc a b c d` stick command. Each channel is -100…100.
///  a = left(-)/right(+)   b = back(-)/forward(+)   c = down(-)/up(+)   d = yaw ccw(-)/cw(+)
struct RCCommand: Equatable {
    var lr: Int = 0
    var fb: Int = 0
    var ud: Int = 0
    var yaw: Int = 0
    static let hover = RCCommand()
    var sdk: String { "rc \(lr) \(fb) \(ud) \(yaw)" }
}

/// Tunable gains and limits for the follow loop. Conservative by default — gentle
/// gains and hard caps so a real drone never lurches.
struct FollowConfig {
    var targetDistance: Double = 2.0       // meters of standoff to hold
    var distanceDeadband: Double = 0.35    // meters (no fwd/back inside this)
    var bearingDeadbandDeg: Double = 4.0   // no yaw inside this
    var elevationDeadbandDeg: Double = 6.0 // no up/down inside this

    var kYawPerDeg: Double = 1.1           // % stick per degree of bearing
    var kFwdPerMeter: Double = 22.0        // % stick per meter of distance error
    var kUpPerDeg: Double = 1.2            // % stick per degree of elevation

    var maxYaw: Int = 45
    var maxFwd: Int = 28
    var maxUp: Int = 22

    var minDecisionMargin: Float = 25.0    // reject weak/false detections
}

/// Maps a tag detection to a station-keeping stick command. Pure and deterministic:
///  - yaw to center the tag horizontally,
///  - forward/back to hold the target distance,
///  - up/down to keep the tag vertically centered.
/// No tag (or a weak one) → hover. Strafe (lr) stays 0; yaw handles heading.
struct FollowController {
    var config = FollowConfig()

    func command(for tag: TagDetection?) -> RCCommand {
        guard let tag, tag.decisionMargin >= config.minDecisionMargin else { return .hover }

        let bearingDeg = tag.bearingRad * 180.0 / .pi
        let elevationDeg = tag.elevationRad * 180.0 / .pi
        let distanceError = tag.distance - config.targetDistance

        let yaw = abs(bearingDeg) < config.bearingDeadbandDeg
            ? 0 : clamp(config.kYawPerDeg * bearingDeg, config.maxYaw)
        // elevation + = tag below center → descend (negative ud).
        let ud = abs(elevationDeg) < config.elevationDeadbandDeg
            ? 0 : clamp(-config.kUpPerDeg * elevationDeg, config.maxUp)
        // distance error + = too far → move forward (positive fb). distance <= 0 means
        // pose estimation failed (unknown range) → don't drive forward/back.
        let fb = (tag.distance <= 0 || abs(distanceError) < config.distanceDeadband)
            ? 0 : clamp(config.kFwdPerMeter * distanceError, config.maxFwd)

        return RCCommand(lr: 0, fb: fb, ud: ud, yaw: yaw)
    }

    private func clamp(_ value: Double, _ limit: Int) -> Int {
        Int(min(max(value.rounded(), Double(-limit)), Double(limit)))
    }
}
