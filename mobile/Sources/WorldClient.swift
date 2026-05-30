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

    /// Publish the Tello's relative follow geometry (range/bearing from the soldier)
    /// so the laptop can rebroadcast it to the dashboard's follow inset. Best-effort,
    /// fire-and-forget — drops silently if the socket isn't up.
    func sendFollowState(active: Bool, phase: String, distanceM: Double, bearingDeg: Double) {
        guard let task else { return }
        let msg = FollowStateMessage(active: active, phase: phase, distance_m: distanceM,
                                     bearing_deg: bearingDeg, source: "phone",
                                     t: Date().timeIntervalSince1970)
        guard let data = try? encoder.encode(msg), let json = String(data: data, encoding: .utf8) else {
            return
        }
        task.send(.string(json)) { _ in }
    }

    /// Publish phone-localized entities (operator + drone) in the shared world
    /// frame so the laptop upserts them into the world model and both maps render
    /// them. Best-effort, fire-and-forget — drops silently if the socket isn't up.
    func sendEntityReport(_ entities: [Entity]) {
        guard let task, !entities.isEmpty else { return }
        let msg = EntityReportMessage(entities: entities, source: "phone",
                                      t: Date().timeIntervalSince1970)
        guard let data = try? encoder.encode(msg), let json = String(data: data, encoding: .utf8) else {
            return
        }
        task.send(.string(json)) { _ in }
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

}
