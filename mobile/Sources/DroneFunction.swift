import Foundation

/// The CLOSED set of functions the on-device model may call to control the Tello.
/// Two routing classes:
///  - flight: literal Tello SDK commands, executed directly on the drone over UDP
///    (works standalone — no laptop in the loop).
///  - mission: higher-level intents routed to the laptop brain over the WS, since the
///    laptop owns the SLAM/AprilTag autonomy needed to actually execute them.
/// Recon/companion movement only — station-keeping and repositioning, never engagement.
enum DroneFunction: String, CaseIterable {
    // direct flight (executed on the Tello)
    case takeoff, land, up, down, left, right, forward, back
    case rotateCW = "rotate_cw", rotateCCW = "rotate_ccw"
    case emergency
    case flip           // acrobatic forward flip
    case track          // tag-free visual object tracking ("track that boat")
    // mission intents (routed to the laptop when connected)
    case followMe = "follow_me", hold, recall, stop

    var isFlight: Bool { missionCommand == nil }

    /// Mission intents map onto the wire `Command` vocabulary (laptop routing).
    var missionCommand: Command? {
        switch self {
        case .followMe: return .followMe
        case .hold: return .hold
        case .recall: return .recall
        case .stop: return .stop
        default: return nil
        }
    }

    /// Whether this function takes a magnitude (cm for moves, degrees for rotate).
    var takesMagnitude: Bool {
        switch self {
        case .up, .down, .left, .right, .forward, .back: return true
        case .rotateCW, .rotateCCW: return true
        default: return false
        }
    }

    var defaultMagnitude: Int {
        switch self {
        case .rotateCW, .rotateCCW: return 45   // degrees
        default: return 50                        // cm
        }
    }

    /// One-line purpose used in the model's function-list prompt.
    var purpose: String {
        switch self {
        case .takeoff: return "lift off and hover"
        case .land: return "descend and land"
        case .up: return "climb (value=cm)"
        case .down: return "descend (value=cm)"
        case .left: return "strafe left (value=cm)"
        case .right: return "strafe right (value=cm)"
        case .forward: return "move forward (value=cm)"
        case .back: return "move backward (value=cm)"
        case .rotateCW: return "yaw clockwise / right (value=degrees)"
        case .rotateCCW: return "yaw counter-clockwise / left (value=degrees)"
        case .emergency: return "cut motors immediately (failsafe)"
        case .flip: return "perform a forward flip"
        case .track: return "visually track the object the operator has centered"
        case .followMe: return "follow the soldier"
        case .hold: return "hold position"
        case .recall: return "return to the soldier"
        case .stop: return "stop and hold (safe abort)"
        }
    }
}

/// A resolved command: one function plus an optional magnitude. Knows how to render
/// itself as a Tello SDK string (flight) or which mission Command to route (mission).
struct DroneAction: Equatable {
    let function: DroneFunction
    let magnitude: Int?

    init(_ function: DroneFunction, _ magnitude: Int? = nil) {
        self.function = function
        self.magnitude = magnitude
    }

    /// Tello SDK command string for flight actions; nil for mission intents.
    /// Magnitudes are clamped to the Tello's accepted ranges (move 20–500 cm,
    /// rotate 1–360°) so the drone never rejects a malformed command.
    var telloCommand: String? {
        guard function.isFlight else { return nil }
        let m = magnitude ?? function.defaultMagnitude
        switch function {
        case .takeoff: return "takeoff"
        case .land: return "land"
        case .emergency: return "emergency"
        case .flip: return "flip f"
        case .up: return "up \(clampMove(m))"
        case .down: return "down \(clampMove(m))"
        case .left: return "left \(clampMove(m))"
        case .right: return "right \(clampMove(m))"
        case .forward: return "forward \(clampMove(m))"
        case .back: return "back \(clampMove(m))"
        case .rotateCW: return "cw \(clampDeg(m))"
        case .rotateCCW: return "ccw \(clampDeg(m))"
        default: return nil
        }
    }

    /// Short label for the UI status line.
    var label: String {
        let base = function.rawValue.uppercased().replacingOccurrences(of: "_", with: " ")
        if function.takesMagnitude, let m = magnitude { return "\(base) \(m)" }
        return base
    }

    private func clampMove(_ v: Int) -> Int { min(max(v, 20), 500) }
    private func clampDeg(_ v: Int) -> Int { min(max(v, 1), 360) }

    /// Parse the model's function-call output. Accepts a JSON object anywhere in the
    /// text, e.g. {"function":"up","value":50}. Returns nil if no known function.
    static func fromModelOutput(_ text: String) -> DroneAction? {
        guard let obj = firstJSONObject(in: text),
              let name = obj["function"] as? String,
              let fn = DroneFunction(rawValue: name) else { return nil }
        // Distinguish "no value" (fine — use the default magnitude) from "value present
        // but uncoercible" (reject, so we don't silently fly a default distance).
        var mag: Int?
        if let raw = obj["value"], !(raw is NSNull) {
            switch raw {
            case let n as Int: mag = n
            case let d as Double: mag = Int(d)
            case let s as String:
                guard let i = Int(s) else { return nil }
                mag = i
            default: return nil
            }
        }
        return DroneAction(fn, fn.takesMagnitude ? mag : nil)
    }

    private static func firstJSONObject(in text: String) -> [String: Any]? {
        guard let open = text.firstIndex(of: "{"), let close = text.lastIndex(of: "}"),
              open < close else { return nil }
        let slice = String(text[open...close])
        guard let data = slice.data(using: .utf8),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return nil }
        return obj
    }
}

/// Deterministic keyword fallback: transcript → DroneAction without the model.
/// Used when Gemma is unsure or its output doesn't parse, so commands still work.
/// Order matters — compound phrases ("rotate left", "take off") are checked before
/// the bare directional words they contain.
enum DroneIntent {
    static func match(_ transcript: String) -> DroneAction? {
        let t = transcript.lowercased()
        let n = firstNumber(in: t)

        // Failsafe / mission (priority — must win inside longer phrases).
        if has(t, ["emergency", "cut motor", "kill motor"]) { return DroneAction(.emergency) }
        if has(t, ["stop", "halt", "freeze", "abort"]) { return DroneAction(.stop) }
        if has(t, ["take off", "takeoff", "launch", "lift off"]) { return DroneAction(.takeoff) }
        if has(t, ["land", "touch down", "set down"]) { return DroneAction(.land) }
        if has(t, ["recall", "come back", "return", "rtb"]) { return DroneAction(.recall) }
        if has(t, ["hold", "stay", "wait", "stand by"]) { return DroneAction(.hold) }
        // Tracking is deliberate: require an explicit phrase, never the bare word
        // "track" (it shows up in incidental speech). The UI track button is gated
        // by an on-screen confirmation; the voice path should be confirmed too
        // (see ContentView.handle) — this just stops accidental triggers at parse.
        if has(t, ["track that", "track the", "start tracking", "lock on", "lock onto", "follow that", "follow it", "follow him", "follow her"]) { return DroneAction(.track) }
        if has(t, ["follow", "on me", "come with"]) { return DroneAction(.followMe) }

        // Movement.
        if has(t, ["flip", "barrel roll", "do a flip", "backflip", "front flip"]) { return DroneAction(.flip) }
        if has(t, ["rotate left", "turn left", "spin left", "yaw left"]) { return DroneAction(.rotateCCW, n) }
        if has(t, ["rotate right", "turn right", "spin right", "yaw right"]) { return DroneAction(.rotateCW, n) }
        if has(t, ["ascend", "go up", "rise", "higher", "climb"]) { return DroneAction(.up, n) }
        if has(t, ["descend", "go down", "lower", "drop"]) { return DroneAction(.down, n) }
        if has(t, ["forward", "ahead", "advance"]) { return DroneAction(.forward, n) }
        if has(t, ["back", "backward", "back up", "reverse", "retreat", "go back"]) { return DroneAction(.back, n) }
        if has(t, ["strafe left", "slide left", "move left"]) { return DroneAction(.left, n) }
        if has(t, ["strafe right", "slide right", "move right"]) { return DroneAction(.right, n) }
        if has(t, ["up"]) { return DroneAction(.up, n) }
        if has(t, ["down"]) { return DroneAction(.down, n) }
        if has(t, ["left"]) { return DroneAction(.left, n) }
        if has(t, ["right"]) { return DroneAction(.right, n) }
        return nil
    }

    /// Phrase-boundary match: a needle fires only as a whole word or a contiguous
    /// run of whole words, never as a substring inside a larger word ("track" must
    /// not trigger on "racetrack", "land" must not trigger on "island"). Keeps
    /// incidental speech from actuating the drone.
    private static func has(_ text: String, _ needles: [String]) -> Bool {
        let tokens = text.split { !$0.isLetter && !$0.isNumber }.map(String.init)
        for needle in needles {
            let seq = needle.split(separator: " ").map(String.init)
            if containsSequence(tokens, seq) { return true }
        }
        return false
    }

    /// True if `seq` appears as a contiguous run of whole tokens within `tokens`.
    private static func containsSequence(_ tokens: [String], _ seq: [String]) -> Bool {
        guard !seq.isEmpty, tokens.count >= seq.count else { return false }
        for start in 0...(tokens.count - seq.count) {
            if Array(tokens[start..<start + seq.count]) == seq { return true }
        }
        return false
    }

    private static func firstNumber(in text: String) -> Int? {
        var digits = ""
        for ch in text {
            if ch.isNumber { digits.append(ch) }
            else if !digits.isEmpty { break }
        }
        return Int(digits)
    }
}
