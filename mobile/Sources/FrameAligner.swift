import Foundation

/// Co-registers the phone's launch frame (operator at origin, north-up) with the
/// shared WORLD frame (launch anchor tag = origin, north-up). Because both frames
/// are north-up — the dashboard's LocalMap2D and the phone's Localizer share the
/// (east, north) convention — alignment is a pure translation: the operator's
/// position in the world frame, derived from observing the launch anchor tag.
///
/// Observing the tag at (distance, bearing) with the operator's compass heading
/// places the tag at world-relative offset (d·sin(h+b), d·cos(h+b)) from the
/// operator; the operator therefore sits at the negative of that in the
/// tag-origin world frame. Re-observing the tag refreshes the translation
/// (drift correction).
@MainActor
final class FrameAligner: ObservableObject {
    /// Operator position in the world frame; nil until the first observation.
    @Published private(set) var operatorWorld: Vec3?

    var isAligned: Bool { operatorWorld != nil }

    /// Feed a fresh anchor-tag observation (same units the follow loop uses:
    /// distance in metres, bearing in radians, heading in degrees).
    func observe(distance: Double, bearingRad: Double, headingDeg: Double) {
        guard distance > 0, distance.isFinite, bearingRad.isFinite, headingDeg.isFinite else { return }
        let world = headingDeg * .pi / 180 + bearingRad
        let tagOffsetX = distance * sin(world)
        let tagOffsetY = distance * cos(world)
        operatorWorld = Vec3(x: -tagOffsetX, y: -tagOffsetY, z: 0)
    }

    /// Map a launch-frame (operator-origin) point into the world frame. nil while unaligned.
    func toWorld(_ p: Vec3) -> Vec3? {
        guard let op = operatorWorld else { return nil }
        return Vec3(x: p.x + op.x, y: p.y + op.y, z: p.z)
    }

    func reset() { operatorWorld = nil }
}
