import Foundation

enum ConnectionState: Equatable {
    case disconnected
    case connecting
    case connected
    case failed(String)
}

/// Subscribes to the mission spine over WebSocket and publishes the live world
/// model. Sends intent only — never commands the Tello directly (the laptop
/// arbitrates). The single source of truth stays on the laptop; this only renders.
@MainActor
final class WorldClient: ObservableObject {
    @Published private(set) var entities: [Entity] = []
    @Published private(set) var stage: String = "—"
    @Published private(set) var lastError: String?
    @Published private(set) var health: Health?
    @Published private(set) var connection: ConnectionState = .disconnected

    /// Movement trails (the "path"), keyed by entity id — soldier + drones only.
    @Published private(set) var trails: [String: [Vec3]] = [:]

    /// e.g. "ws://192.168.10.1:8000/ws". Defaults to localhost for simulator dev.
    @Published var serverURL: String = "ws://127.0.0.1:8000/ws"

    private let maxTrail = 80

    private var task: URLSessionWebSocketTask?
    private var session: URLSession = .shared
    private let decoder = JSONDecoder()
    private let encoder = JSONEncoder()

    func connect() {
        guard let url = URL(string: serverURL) else {
            connection = .failed("invalid URL")
            return
        }
        disconnect()
        trails = [:]
        connection = .connecting
        let task = session.webSocketTask(with: url)
        self.task = task
        task.resume()
        connection = .connected
        Task { await receiveLoop() }
    }

    func disconnect() {
        task?.cancel(with: .goingAway, reason: nil)
        task = nil
        if connection != .disconnected { connection = .disconnected }
    }

    /// Send a structured intent. stop/recall are honored from any mission stage by
    /// the laptop's state machine; this just delivers them.
    func send(_ command: Command) {
        guard let task else { return }
        let msg = IntentMessage(command: command, source: "phone", t: Date().timeIntervalSince1970)
        guard let data = try? encoder.encode(msg), let json = String(data: data, encoding: .utf8) else {
            return
        }
        task.send(.string(json)) { [weak self] error in
            guard let error else { return }
            Task { @MainActor in self?.connection = .failed(error.localizedDescription) }
        }
    }

    private func receiveLoop() async {
        guard let task else { return }
        while connection == .connected {
            do {
                let message = try await receiveOne(task)
                if let data = message {
                    apply(data)
                }
            } catch {
                connection = .failed(error.localizedDescription)
                return
            }
        }
    }

    /// Async wrapper over the completion-based receive (stable across SDKs).
    private func receiveOne(_ task: URLSessionWebSocketTask) async throws -> Data? {
        try await withCheckedThrowingContinuation { continuation in
            task.receive { result in
                switch result {
                case .success(let message):
                    switch message {
                    case .string(let text): continuation.resume(returning: Data(text.utf8))
                    case .data(let data): continuation.resume(returning: data)
                    @unknown default: continuation.resume(returning: nil)
                    }
                case .failure(let error):
                    continuation.resume(throwing: error)
                }
            }
        }
    }

    private func apply(_ data: Data) {
        guard let message = try? decoder.decode(ServerMessage.self, from: data) else { return }
        switch message {
        case .worldSnapshot(let snap):
            entities = snap.entities
            appendTrails(snap.entities)
        case .missionState(let state):
            stage = state.stage
            lastError = state.lastError
        case .health(let h):
            health = h
        case .unknown:
            break
        }
    }

    /// Append the moving units' positions to their trails (skip < 0.2 m jitter).
    private func appendTrails(_ list: [Entity]) {
        for e in list where e.type == .soldier || e.type == .drone {
            var pts = trails[e.id] ?? []
            if let last = pts.last {
                let dx = last.x - e.position.x, dy = last.y - e.position.y
                if dx * dx + dy * dy < 0.04 { continue }
            }
            pts.append(e.position)
            if pts.count > maxTrail { pts.removeFirst(pts.count - maxTrail) }
            trails[e.id] = pts
        }
    }

#if DEBUG
    /// Populate a representative scene for screenshots / previews (launch arg -demo).
    func loadSampleData() {
        connection = .connected
        stage = "following"
        health = Health(tello: "connected", mavic: "streaming", perception: "ok", t: 0)
        var soldierTrail: [Vec3] = []
        var droneTrail: [Vec3] = []
        for i in stride(from: 0, through: 28, by: 1) {
            let a = Double(i) * 0.18
            soldierTrail.append(Vec3(x: 3.2 * cos(a) - 1, y: 3.2 * sin(a), z: 0))
            droneTrail.append(Vec3(x: 2.6 * cos(a + 0.5) - 1, y: 2.6 * sin(a + 0.5) + 1.5, z: 1.2))
        }
        let soldier = soldierTrail.last ?? Vec3(x: 0, y: 0, z: 0)
        let drone = droneTrail.last ?? Vec3(x: 0, y: 0, z: 0)
        entities = [
            Entity(id: "soldier_1", type: .soldier, position: soldier, confidence: 1, timestamp: 0,
                   source: .manual, label: "operator", ttlS: 5, status: .active),
            Entity(id: "mavic_cam", type: .drone, position: drone, confidence: 1, timestamp: 0,
                   source: .slam, label: "mavic", ttlS: 3, status: .active),
            Entity(id: "poi_door", type: .poi, position: Vec3(x: -5, y: 2.5, z: 0), confidence: 0.82,
                   timestamp: 0, source: .yolo, label: "doorway", ttlS: 5, status: .active),
            Entity(id: "poi_window", type: .poi, position: Vec3(x: 4.5, y: -4, z: 0), confidence: 0.7,
                   timestamp: 0, source: .yolo, label: "window", ttlS: 5, status: .stale),
            Entity(id: "hazard_1", type: .hazard, position: Vec3(x: 1.5, y: -6, z: 0), confidence: 0.66,
                   timestamp: 0, source: .yolo, label: "debris", ttlS: 5, status: .active),
            Entity(id: "obj_1", type: .object, position: Vec3(x: -3, y: -3, z: 0), confidence: 0.5,
                   timestamp: 0, source: .slam, label: nil, ttlS: 10, status: .active),
        ]
        trails = ["soldier_1": soldierTrail, "mavic_cam": droneTrail]
    }
#endif
}
