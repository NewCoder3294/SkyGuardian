import Foundation

/// Maps a free-text voice transcript onto the CLOSED command vocabulary. The
/// on-device model (Gemma 3n via Cactus) turns speech → text; this turns text →
/// one of exactly four intents, or nil. Unknown phrases are rejected, never
/// guessed — same rule the backend enforces on the wire. Pure + unit-tested.
enum IntentParser {
    static func parse(_ transcript: String) -> Command? {
        let t = transcript.lowercased()

        // Priority intents first — these must win even inside a longer phrase.
        if contains(t, ["stop", "halt", "freeze", "abort"]) { return .stop }
        if contains(t, ["recall", "come back", "return", "rtb"]) { return .recall }
        if contains(t, ["hold", "stay", "wait", "hold position", "stand by"]) { return .hold }
        if contains(t, ["follow", "follow me", "come with", "on me"]) { return .followMe }
        return nil
    }

    private static func contains(_ text: String, _ needles: [String]) -> Bool {
        for n in needles where text.contains(n) { return true }
        return false
    }
}
