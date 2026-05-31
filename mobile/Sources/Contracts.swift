import Foundation

// Swift mirror of the integration contracts (backend/app/contracts.py ↔ shared/contracts.ts).
// Codable for all wire models, per project Swift rules.

// MARK: - Contract A — Entity

enum EntityType: String, Codable, Sendable {
    case poi, hazard, object, soldier, drone
}

enum EntityStatus: String, Codable, Sendable {
    case active, stale, lost
}

enum EntitySource: String, Codable, Sendable {
    case yolo, slam, follow, manual
}

struct Vec3: Codable, Equatable, Sendable {
    var x: Double
    var y: Double
    var z: Double
}

struct Entity: Codable, Identifiable, Equatable, Sendable {
    let id: String
    let type: EntityType
    let position: Vec3
    let confidence: Double
    let timestamp: Double
    let source: EntitySource
    let label: String?
    let ttlS: Double
    let status: EntityStatus

    enum CodingKeys: String, CodingKey {
        case id, type, position, confidence, timestamp, source, label
        case ttlS = "ttl_s"
        case status
    }
}

// MARK: - Contract B — Server → client messages

struct WorldSnapshot: Codable, Sendable {
    let entities: [Entity]
    let t: Double
}

struct MissionState: Codable, Sendable {
    let stage: String
    let lastError: String?
    let t: Double

    enum CodingKeys: String, CodingKey {
        case stage
        case lastError = "last_error"
        case t
    }
}

struct Health: Codable, Sendable {
    let tello: String
    let mavic: String
    let perception: String
    let t: Double
}

/// Discriminated union over the `type` field, decoded from a single WS frame.
enum ServerMessage: Decodable, Sendable {
    case worldSnapshot(WorldSnapshot)
    case missionState(MissionState)
    case health(Health)
    case unknown(String)

    private enum Keys: String, CodingKey { case type }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: Keys.self)
        let type = try container.decode(String.self, forKey: .type)
        switch type {
        case "world_snapshot": self = .worldSnapshot(try WorldSnapshot(from: decoder))
        case "mission_state": self = .missionState(try MissionState(from: decoder))
        case "health": self = .health(try Health(from: decoder))
        default: self = .unknown(type)
        }
    }
}

// MARK: - Contract B — Client → server messages

/// Closed intent vocabulary. No free text — must match the backend enum exactly.
enum Command: String, Codable, CaseIterable, Sendable {
    case followMe = "follow_me"
    case hold
    case recall
    case stop
    case approach
}

struct IntentMessage: Encodable, Sendable {
    let type = "intent"
    let command: Command
    let source: String
    let t: Double
}

struct DeviceLocation: Encodable, Sendable {
    let type = "device_location"
    let position: Vec3
    let source: String
    let t: Double
}

/// Relative follow geometry — the Tello's range/bearing from the soldier. The
/// phone runs the follow loop, so it is the source of this; the laptop rebroadcasts
/// it for the dashboard's follow inset. Not map coordinates (frames aren't shared).
struct FollowStateMessage: Encodable, Sendable {
    let type = "follow_state"
    let active: Bool
    let phase: String
    let distance_m: Double
    let bearing_deg: Double
    let source: String
    let t: Double
    let target_type: String?   // "visual_me" | "tag" | nil; set explicitly when following
    let target_label: String?  // raw id hint; nil for visual_me

    init(active: Bool, phase: String, distance_m: Double, bearing_deg: Double,
         source: String, t: Double,
         target_type: String? = nil, target_label: String? = nil) {
        self.active = active
        self.phase = phase
        self.distance_m = distance_m
        self.bearing_deg = bearing_deg
        self.source = source
        self.t = t
        self.target_type = target_type
        self.target_label = target_label
    }
}

/// Phone-localized entities (operator + drone) expressed in the shared WORLD
/// frame (north-up metres, launch anchor tag = origin). Mirrors backend
/// EntityReport. The laptop upserts these into the world model so they render on
/// both maps. Not to be confused with FollowStateMessage (relative range/bearing).
struct EntityReportMessage: Encodable, Sendable {
    let type = "entity_report"
    let entities: [Entity]
    let source: String
    let t: Double
}

/// Operator label decision forwarded to the backend data flywheel.
/// kind: "confirm" | "reject" | "correct"
struct LabelEventMessage: Encodable, Sendable {
    let type = "label_event"
    let kind: String
    let source: String
    let label: String?
    let correctedLabel: String?
    let box: [Double]?
    let note: String?
    let t: Double

    enum CodingKeys: String, CodingKey {
        case type, kind, source, label
        case correctedLabel = "corrected_label"
        case box, note, t
    }
}
