import CoreGraphics

/// Pure value type that maps local-frame metres → screen points for the top-down
/// map. No GPS, no MapKit: the launch point is the origin, +x right, +y up (so
/// screen-y is inverted). Square-fit so `spanMeters` across the shorter side.
struct MapProjection: Equatable {
    /// How many metres the shorter screen dimension spans.
    var spanMeters: Double

    init(spanMeters: Double = 20.0) {
        self.spanMeters = max(spanMeters, 0.001)
    }

    func scale(in size: CGSize) -> CGFloat {
        let minDim = min(size.width, size.height)
        return minDim / CGFloat(spanMeters)
    }

    /// Project a local-frame position into a screen point, origin at view centre.
    func point(for position: Vec3, in size: CGSize) -> CGPoint {
        let s = scale(in: size)
        let cx = size.width / 2.0
        let cy = size.height / 2.0
        return CGPoint(
            x: cx + CGFloat(position.x) * s,
            y: cy - CGFloat(position.y) * s   // world +y is up; screen +y is down
        )
    }
}
