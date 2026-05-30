import Foundation
import Network

/// The single owner of the Tello control channel (UDP → 192.168.10.1:8889).
/// Everything that commands the drone funnels through here: the video layer asks it
/// to `command`/`streamon`, and the voice/function layer sends flight commands. One
/// shared channel means the Tello is never driven by two sockets at once.
///
/// Direct mode (no laptop): the phone is the sole controller while on the Tello AP.
final class TelloCommander: ObservableObject {
    static let shared = TelloCommander()

    enum Link: Equatable { case down, connecting, up, error(String) }
    @Published private(set) var link: Link = .down
    @Published private(set) var lastSent: String = ""

    // Telemetry from the Tello's state broadcast (UDP 8890). -1 = unknown.
    @Published private(set) var battery: Int = -1     // percent
    @Published private(set) var heightCm: Int = 0     // height above takeoff
    @Published private(set) var tofCm: Int = 0        // distance to ground (time-of-flight)
    @Published private(set) var flightTimeS: Int = 0  // motor-on seconds
    @Published private(set) var tempC: Int = 0        // board temperature

    private let host = "192.168.10.1"
    private let port: UInt16 = 8889
    private let statePort: UInt16 = 8890
    private let q = DispatchQueue(label: "tello.cmd")
    private var conn: NWConnection?
    private var stateListener: NWListener?
    private var keepalive: DispatchSourceTimer?

    private init() {}

    var isUp: Bool { link == .up }

    /// Open the control channel and enter SDK mode. Idempotent.
    func connect() {
        q.async {
            guard self.conn == nil else { return }
            self.setLink(.connecting)
            let c = NWConnection(host: .init(self.host), port: .init(rawValue: self.port)!, using: .udp)
            self.conn = c
            c.stateUpdateHandler = { [weak self] s in
                guard let self else { return }
                switch s {
                case .ready:
                    self.rawSend("command")        // enter SDK mode
                    self.startKeepalive()
                    self.openState()               // listen for battery/height/etc.
                    self.setLink(.up)
                case .failed(let e):
                    self.setLink(.error(e.localizedDescription))
                case .cancelled:
                    self.setLink(.down)
                default: break
                }
            }
            c.start(queue: self.q)
        }
    }

    /// Ask the Tello to start its H.264 stream (called by the video layer).
    func startVideo() {
        connect()
        q.asyncAfter(deadline: .now() + 0.6) { self.rawSend("streamon") }
    }

    /// Send a raw Tello SDK string, connecting first if needed.
    func send(_ raw: String) {
        connect()
        q.async { self.rawSend(raw) }
        DispatchQueue.main.async { self.lastSent = raw }
    }

    /// Execute a resolved flight action. Returns false for mission intents (which
    /// are not Tello SDK commands and route to the laptop instead).
    @discardableResult
    func execute(_ action: DroneAction) -> Bool {
        guard let cmd = action.telloCommand else { return false }
        send(cmd)
        return true
    }

    /// High-rate stick control (the follow loop's channel). Unlike `send`, `rc` gets
    /// no ack and is meant to be streamed continuously; we fire-and-forget on q.
    func rc(_ c: RCCommand) {
        connect()
        q.async { self.rawSend(c.sdk) }
    }

    func disconnect() {
        q.async {
            self.keepalive?.cancel(); self.keepalive = nil
            self.conn?.cancel(); self.conn = nil
            self.stateListener?.cancel(); self.stateListener = nil
            self.setLink(.down)
        }
    }

    // MARK: telemetry (Tello state broadcast → UDP 8890)

    private func openState() {
        guard stateListener == nil else { return }
        let params = NWParameters.udp
        params.allowLocalEndpointReuse = true
        guard let listener = try? NWListener(using: params, on: .init(rawValue: statePort)!) else { return }
        stateListener = listener
        listener.newConnectionHandler = { [weak self] conn in
            guard let self else { return }
            conn.start(queue: self.q)
            self.receiveState(on: conn)
        }
        listener.start(queue: q)
    }

    private func receiveState(on conn: NWConnection) {
        conn.receiveMessage { [weak self] data, _, _, err in
            guard let self else { return }
            if let data, let s = String(data: data, encoding: .utf8) { self.parseState(s) }
            if err == nil { self.receiveState(on: conn) }
        }
    }

    /// State string looks like: "...;bat:85;h:0;tof:10;time:0;templ:60;..."
    private func parseState(_ s: String) {
        var bat = battery, h = heightCm, tof = tofCm, time = flightTimeS, temp = tempC
        for field in s.split(separator: ";") {
            let kv = field.split(separator: ":")
            guard kv.count == 2, let v = Int(kv[1]) else { continue }
            switch kv[0] {
            case "bat": bat = v
            case "h": h = v
            case "tof": tof = v
            case "time": time = v
            case "templ": temp = v
            default: break
            }
        }
        DispatchQueue.main.async {
            self.battery = bat; self.heightCm = h; self.tofCm = tof
            self.flightTimeS = time; self.tempC = temp
        }
    }

    // MARK: internals (all on q)

    private func rawSend(_ s: String) {
        conn?.send(content: Data(s.utf8), completion: .contentProcessed { _ in })
    }

    private func startKeepalive() {
        keepalive?.cancel()
        let t = DispatchSource.makeTimerSource(queue: q)
        t.schedule(deadline: .now() + 5, repeating: 5)
        t.setEventHandler { [weak self] in self?.rawSend("command") }  // keep SDK mode alive
        keepalive = t
        t.resume()
    }

    private func setLink(_ l: Link) {
        DispatchQueue.main.async { if self.link != l { self.link = l } }
    }
}
