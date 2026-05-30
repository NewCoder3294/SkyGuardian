import Foundation

/// One pre-cached OSM building footprint in the local metre frame (x=east, y=north),
/// matching the backend `/map/buildings` payload (generated offline by
/// `scripts/fetch_buildings.py` BEFORE going offline). Already projected to metres —
/// no GPS, no geometry needed on the phone.
struct Building: Decodable, Sendable {
    let height_m: Double
    let polygon: [[Double]]   // [[east_m, north_m], ...]
}

private struct BuildingsPayload: Decodable {
    let buildings: [Building]
}

/// Loads the laptop's pre-cached buildings once over the LOCAL network (the same AP
/// the phone flies the Tello on) — no internet, no live tiles. This is the phone's
/// equivalent of the dashboard's offline basemap.
@MainActor
final class BuildingsStore: ObservableObject {
    @Published private(set) var buildings: [Building] = []

    /// `httpBase` e.g. "http://192.168.10.2:8000". Idempotent: no-op once loaded.
    func load(from httpBase: String) {
        guard buildings.isEmpty, let url = URL(string: "\(httpBase)/map/buildings") else { return }
        URLSession.shared.dataTask(with: url) { data, _, _ in
            guard let data,
                  let payload = try? JSONDecoder().decode(BuildingsPayload.self, from: data)
            else { return }
            Task { @MainActor in self.buildings = payload.buildings }
        }.resume()
    }

    func clear() { buildings = [] }
}
