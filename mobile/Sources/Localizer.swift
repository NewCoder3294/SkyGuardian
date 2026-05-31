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

    /// Entities re-expressed in the shared world frame (empty until aligned).
    /// These are what get published to the laptop; `entities` stays launch-frame
    /// for the on-device view so the local map still works pre-alignment.
    @Published private(set) var worldEntities: [Entity] = []

    private var droneTrail: [Vec3] = []
    private let maxTrail = 240

    /// Feed a fresh follow fix. `active` = a live tag (drone position is valid).
    /// `headingDeg` is the operator's compass heading (magnetometer).
    func update(distance: Double, bearingRad: Double, headingDeg: Double, active: Bool) {
        // Real timestamps so the laptop's world-model TTL can age these out if the
        // phone link drops (a 0 timestamp would read as "ancient" and never active).
        let now = Date().timeIntervalSince1970
        var ents: [Entity] = [
            // id "soldier" (not "operator") so the world-frame report and the
            // backend's device_location fallback upsert the SAME entity
            // (last-writer-wins) instead of producing two soldier markers.
            Entity(id: "soldier", type: .soldier, position: Vec3(x: 0, y: 0, z: 0),
                   confidence: 1, timestamp: now, source: .manual, label: "operator",
                   ttlS: 4, status: .active),
        ]

        if active, distance > 0 {
            // Rotate the tag's camera-relative bearing into the launch frame by the
            // operator's heading to place the drone around them.
            let world = headingDeg * .pi / 180 + bearingRad
            let drone = Vec3(x: distance * sin(world), y: distance * cos(world), z: 0)
            append(&droneTrail, drone)
            ents.append(Entity(id: "drone", type: .drone, position: drone, confidence: 1,
                               timestamp: now, source: .follow, label: "tello",
                               ttlS: 4, status: .active))
        }

        entities = ents
        trails = ["drone": droneTrail]
    }

    /// Re-express the current launch-frame entities in the shared world frame via
    /// the aligner. Empty until the aligner has observed the launch anchor tag.
    func project(through aligner: FrameAligner) {
        worldEntities = entities.compactMap { e in
            guard let wp = aligner.toWorld(e.position) else { return nil }
            return Entity(id: e.id, type: e.type, position: wp, confidence: e.confidence,
                          timestamp: e.timestamp, source: e.source, label: e.label,
                          ttlS: e.ttlS, status: e.status)
        }
    }

    func reset() {
        droneTrail = []
        entities = []
        trails = [:]
        worldEntities = []
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
