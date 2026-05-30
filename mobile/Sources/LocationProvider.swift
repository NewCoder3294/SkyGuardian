import CoreLocation
import Foundation

/// The operator's own device location — the spec's "device location for follow-me
/// context." Here it also anchors the geographic map: it centers the basemap and is
/// the origin for converting local-frame entity positions (meters) to coordinates.
final class LocationProvider: NSObject, ObservableObject, CLLocationManagerDelegate {
    @Published private(set) var coordinate: CLLocationCoordinate2D?
    @Published private(set) var headingDeg: Double = 0   // true heading, for placing the drone relative to the operator
    @Published private(set) var authorized = false

    private let manager = CLLocationManager()

    override init() {
        super.init()
        manager.delegate = self
        // A map anchor doesn't need best-accuracy GPS; coarser + a distance filter
        // avoids re-anchoring the map (and its rebuild) on every tiny fix, saving battery.
        manager.desiredAccuracy = kCLLocationAccuracyNearestTenMeters
        manager.distanceFilter = 4
    }

    func start() {
        manager.requestWhenInUseAuthorization()
        manager.startUpdatingLocation()
        if CLLocationManager.headingAvailable() { manager.startUpdatingHeading() }
    }

    func locationManager(_ m: CLLocationManager, didUpdateHeading newHeading: CLHeading) {
        let h = newHeading.trueHeading >= 0 ? newHeading.trueHeading : newHeading.magneticHeading
        if h >= 0 { headingDeg = h }
    }

    func locationManagerDidChangeAuthorization(_ m: CLLocationManager) {
        let s = m.authorizationStatus
        authorized = (s == .authorizedWhenInUse || s == .authorizedAlways)
        if authorized { m.startUpdatingLocation() }
    }

    func locationManager(_ m: CLLocationManager, didUpdateLocations locs: [CLLocation]) {
        if let c = locs.last?.coordinate { coordinate = c }
    }

    func locationManager(_ m: CLLocationManager, didFailWithError error: Error) {}
}
