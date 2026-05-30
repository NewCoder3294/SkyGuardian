import CoreLocation
import Foundation

/// Phone-side localization for the map, driven by the AprilTag follow. The operator is
/// anchored by GPS; the drone is placed relative to the operator using the tag's
/// distance + bearing (rotated by the operator's compass heading). Both accumulate
/// movement trails in a fixed launch frame — so the map shows the drone, the operator,
/// and how they've moved, with no laptop in the loop.
@MainActor
final class Localizer: ObservableObject {
    @Published private(set) var entities: [Entity] = []
    @Published private(set) var trails: [String: [Vec3]] = [:]
    @Published private(set) var origin: CLLocationCoordinate2D?

    private var droneTrail: [Vec3] = []
    private var operatorTrail: [Vec3] = []
    private let maxTrail = 240

    /// Feed a fresh follow fix. `active` = a live tag (drone position is valid).
    func update(operatorCoord: CLLocationCoordinate2D, distance: Double,
                bearingRad: Double, headingDeg: Double, active: Bool) {
        if origin == nil { origin = operatorCoord }   // launch point = first fix
        guard let origin else { return }

        let op = Self.toLocal(origin, operatorCoord)
        append(&operatorTrail, op)
        var ents: [Entity] = [
            Entity(id: "operator", type: .soldier, position: op, confidence: 1, timestamp: 0,
                   source: .manual, label: "operator", ttlS: 9999, status: .active),
        ]

        if active, distance > 0 {
            // Bearing is the tag's angle in the camera; rotate into the world by the
            // operator's heading to place the drone around them.
            let world = headingDeg * .pi / 180 + bearingRad
            let drone = Vec3(x: op.x + distance * sin(world), y: op.y + distance * cos(world), z: 0)
            append(&droneTrail, drone)
            ents.append(Entity(id: "drone", type: .drone, position: drone, confidence: 1, timestamp: 0,
                               source: .follow, label: "tello", ttlS: 9999, status: .active))
        }

        entities = ents
        trails = ["operator": operatorTrail, "drone": droneTrail]
    }

    func reset() {
        droneTrail = []; operatorTrail = []
        entities = []; trails = [:]; origin = nil
    }

    private func append(_ trail: inout [Vec3], _ p: Vec3) {
        if let last = trail.last {
            let dx = last.x - p.x, dy = last.y - p.y
            if dx * dx + dy * dy < 0.25 { return }   // ≥ 0.5 m movement to log a point
        }
        trail.append(p)
        if trail.count > maxTrail { trail.removeFirst(trail.count - maxTrail) }
    }

    /// Equirectangular meters (east, north) of `c` relative to launch origin `o`.
    private static func toLocal(_ o: CLLocationCoordinate2D, _ c: CLLocationCoordinate2D) -> Vec3 {
        let north = (c.latitude - o.latitude) * 111_111.0
        let east = (c.longitude - o.longitude) * 111_111.0 * cos(o.latitude * .pi / 180)
        return Vec3(x: east, y: north, z: 0)
    }
}
