import Foundation

/// Phone-side localization for the map — fully OFFLINE and GPS-FREE (mirrors the
/// laptop dashboard's approach). The operator is the fixed launch origin (0,0); the
/// drone is placed RELATIVE to the operator via the AprilTag's distance + bearing,
/// rotated by the operator's compass heading (magnetometer — a local sensor, not
/// GPS). The drone accumulates a movement trail in the launch frame. No GPS, no
/// network, no laptop in the loop.
@MainActor
final class Localizer: ObservableObject {
    @Published private(set) var entities: [Entity] = []
    @Published private(set) var trails: [String: [Vec3]] = [:]

    private var droneTrail: [Vec3] = []
    private let maxTrail = 240

    /// Feed a fresh follow fix. `active` = a live tag (drone position is valid).
    /// `headingDeg` is the operator's compass heading (magnetometer).
    func update(distance: Double, bearingRad: Double, headingDeg: Double, active: Bool) {
        var ents: [Entity] = [
            Entity(id: "operator", type: .soldier, position: Vec3(x: 0, y: 0, z: 0),
                   confidence: 1, timestamp: 0, source: .manual, label: "operator",
                   ttlS: 9999, status: .active),
        ]

        if active, distance > 0 {
            // Rotate the tag's camera-relative bearing into the launch frame by the
            // operator's heading to place the drone around them.
            let world = headingDeg * .pi / 180 + bearingRad
            let drone = Vec3(x: distance * sin(world), y: distance * cos(world), z: 0)
            append(&droneTrail, drone)
            ents.append(Entity(id: "drone", type: .drone, position: drone, confidence: 1,
                               timestamp: 0, source: .follow, label: "tello",
                               ttlS: 9999, status: .active))
        }

        entities = ents
        trails = ["drone": droneTrail]
    }

    func reset() {
        droneTrail = []
        entities = []
        trails = [:]
    }

    private func append(_ trail: inout [Vec3], _ p: Vec3) {
        if let last = trail.last {
            let dx = last.x - p.x, dy = last.y - p.y
            if dx * dx + dy * dy < 0.25 { return }   // ≥ 0.5 m movement to log a point
        }
        trail.append(p)
        if trail.count > maxTrail { trail.removeFirst(trail.count - maxTrail) }
    }
}
