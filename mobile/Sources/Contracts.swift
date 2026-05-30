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
