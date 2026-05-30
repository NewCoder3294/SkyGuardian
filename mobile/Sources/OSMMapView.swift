import MapKit
import SwiftUI
import UIKit

/// 2D (flat) vs 3D (tilted/perspective) presentation of the same OpenStreetMap base.
enum MapDimension { case flat, tilted }

/// Look up an entity's type by id (trails are keyed by entity id).
func entityType(forId id: String, in entities: [Entity]) -> EntityType? {
    entities.first(where: { $0.id == id })?.type
}

/// Convert a local-frame entity position (x = east, y = north, meters) into a
/// geographic coordinate around the operator's location. Equirectangular approx —
/// fine at the scales a follow loop operates in.
func localToCoordinate(_ origin: CLLocationCoordinate2D, _ p: Vec3) -> CLLocationCoordinate2D {
    let dLat = p.y / 111_111.0
    let dLon = p.x / (111_111.0 * cos(origin.latitude * .pi / 180.0))
    return CLLocationCoordinate2D(latitude: origin.latitude + dLat, longitude: origin.longitude + dLon)
}

/// Serves OpenStreetMap raster tiles — a free, open basemap (no API key, no Apple
/// Maps). Sends a descriptive User-Agent per OSM's tile usage policy.
final class OSMTileOverlay: MKTileOverlay {
    init() {
        super.init(urlTemplate: "https://tile.openstreetmap.org/{z}/{x}/{y}.png")
        canReplaceMapContent = true
        maximumZ = 19
    }
    override func loadTile(at path: MKTileOverlayPath, result: @escaping (Data?, Error?) -> Void) {
        var req = URLRequest(url: url(forTilePath: path))
        req.setValue("SkyGuardian/1.0 (recon companion; +https://github.com/NewCoder3294/SkyGuardian)",
                     forHTTPHeaderField: "User-Agent")
        URLSession.shared.dataTask(with: req) { data, _, err in result(data, err) }.resume()
    }
}

/// A polyline tagged with how it should be drawn, so drone and operator traces keep
/// distinct colours/weights and a faded-history vs solid-head ("comet tail") look.
final class TracePolyline: MKPolyline {
    var stroke: UIColor = .black
    var width: CGFloat = 3
    var isHead = false

    static func make(_ coords: [CLLocationCoordinate2D], stroke: UIColor, width: CGFloat, isHead: Bool) -> TracePolyline {
        let line = TracePolyline(coordinates: coords, count: coords.count)
        line.stroke = stroke; line.width = width; line.isHead = isHead
        return line
    }
}

/// A map annotation for one world-model entity, placed relative to the operator.
final class EntityAnnotation: NSObject, MKAnnotation {
    let coordinate: CLLocationCoordinate2D
    let title: String?
    let tint: UIColor
    let glyph: String
    init(_ e: Entity, origin: CLLocationCoordinate2D) {
        coordinate = localToCoordinate(origin, e.position)
        title = e.label ?? e.type.rawValue.capitalized
        switch e.type {
        case .soldier: tint = UIColor(red: 0.42, green: 0.46, blue: 0.20, alpha: 1); glyph = "◍"
        case .drone:   tint = UIColor(red: 0.28, green: 0.31, blue: 0.13, alpha: 1); glyph = "▲"
        case .poi:     tint = UIColor(red: 0.45, green: 0.34, blue: 0.20, alpha: 1); glyph = "◇"
        case .hazard:  tint = UIColor(red: 0.62, green: 0.18, blue: 0.13, alpha: 1); glyph = "✕"
        case .object:  tint = UIColor(red: 0.30, green: 0.30, blue: 0.28, alpha: 1); glyph = "•"
        }
    }
}

/// MapKit-backed map on an OpenStreetMap basemap. Plots the real world-model
/// entities + movement trails relative to the operator, and flips between a flat 2D
/// and a tilted 3D camera. No mock data — it renders only what the world model holds.
struct OSMMapView: UIViewRepresentable {
    let entities: [Entity]
    let trails: [String: [Vec3]]
    let origin: CLLocationCoordinate2D?
    var dimension: MapDimension

    func makeCoordinator() -> Coordinator { Coordinator() }

    /// Trace tint per unit, matching the entity marker colours (olive soldier,
    /// dark-olive drone). Unknown ids fall back to neutral ink.
    static func traceColor(forId id: String, in entities: [Entity]) -> UIColor {
        switch entityType(forId: id, in: entities) {
        case .soldier: return UIColor(red: 0.42, green: 0.46, blue: 0.20, alpha: 1)
        case .drone:   return UIColor(red: 0.28, green: 0.31, blue: 0.13, alpha: 1)
        default:       return UIColor(red: 0.30, green: 0.30, blue: 0.28, alpha: 1)
        }
    }

    func makeUIView(context: Context) -> MKMapView {
        let map = MKMapView()
        map.delegate = context.coordinator
        map.addOverlay(OSMTileOverlay(), level: .aboveLabels)
        map.showsUserLocation = true
        map.pointOfInterestFilter = .excludingAll
        map.isPitchEnabled = true
        map.isRotateEnabled = true
        return map
    }

    func updateUIView(_ map: MKMapView, context: Context) {
        guard let origin else { return }
        context.coordinator.sync(map, entities: entities, trails: trails, origin: origin, dimension: dimension)
    }

    final class Coordinator: NSObject, MKMapViewDelegate {
        private var centered = false
        private var lastPitch: CGFloat = -1

        func sync(_ map: MKMapView, entities: [Entity], trails: [String: [Vec3]],
                  origin: CLLocationCoordinate2D, dimension: MapDimension) {
            // Entities — replace the set each update (cheap at these counts).
            map.removeAnnotations(map.annotations.compactMap { $0 as? EntityAnnotation })
            map.addAnnotations(entities.map { EntityAnnotation($0, origin: origin) })

            // Trails — comet-tail polylines for soldier/drone paths. Drone is drawn
            // distinct + heavier; the most recent ~12 points render as a bold "head"
            // over a faded full-history line.
            map.removeOverlays(map.overlays.compactMap { $0 as? TracePolyline })
            for (id, pts) in trails where pts.count > 1 {
                let isDrone = entityType(forId: id, in: entities) == .drone
                let stroke = OSMMapView.traceColor(forId: id, in: entities)
                let width: CGFloat = isDrone ? 4 : 2.5
                let coords = pts.map { localToCoordinate(origin, $0) }

                // Faded full-history line.
                map.addOverlay(TracePolyline.make(coords, stroke: stroke.withAlphaComponent(0.30),
                                                  width: width, isHead: false), level: .aboveLabels)
                // Bold recent head.
                let headCount = min(12, coords.count)
                if headCount > 1 {
                    let head = Array(coords.suffix(headCount))
                    map.addOverlay(TracePolyline.make(head, stroke: stroke.withAlphaComponent(0.95),
                                                      width: width, isHead: true), level: .aboveLabels)
                }
            }

            // Camera: flat (pitch 0) vs tilted 3D, centered on the operator.
            let pitch: CGFloat = dimension == .tilted ? 55 : 0
            let center = map.userLocation.location?.coordinate ?? origin
            if !centered || abs(pitch - lastPitch) > 0.5 {
                let cam = MKMapCamera(lookingAtCenter: center, fromDistance: 500,
                                      pitch: pitch, heading: map.camera.heading)
                map.setCamera(cam, animated: centered)
                centered = true
                lastPitch = pitch
            }
        }

        func mapView(_ map: MKMapView, rendererFor overlay: MKOverlay) -> MKOverlayRenderer {
            if let tile = overlay as? MKTileOverlay { return MKTileOverlayRenderer(tileOverlay: tile) }
            if let trace = overlay as? TracePolyline {
                let r = MKPolylineRenderer(polyline: trace)
                r.strokeColor = trace.stroke
                r.lineWidth = trace.width
                r.lineCap = .round
                r.lineJoin = .round
                return r
            }
            return MKOverlayRenderer(overlay: overlay)
        }

        func mapView(_ map: MKMapView, viewFor annotation: MKAnnotation) -> MKAnnotationView? {
            guard let e = annotation as? EntityAnnotation else { return nil }
            let id = "entity"
            let view = (map.dequeueReusableAnnotationView(withIdentifier: id) as? MKMarkerAnnotationView)
                ?? MKMarkerAnnotationView(annotation: annotation, reuseIdentifier: id)
            view.annotation = annotation
            view.markerTintColor = e.tint
            view.glyphText = e.glyph
            view.displayPriority = .required
            return view
        }
    }
}
