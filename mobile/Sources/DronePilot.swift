import Foundation

/// Turns a spoken command into a drone function call. The on-device model (Gemma 3n
/// via Cactus) is asked to pick exactly one function from the closed vocabulary and
/// return it as JSON — that's the "function calling". A deterministic keyword matcher
/// backs it up, so a recognized command still executes if the model is unsure or its
/// output doesn't parse. Never invents a command: unmatched speech returns nil.
struct DronePilot {
    let service: CactusService

    func resolve(_ transcript: String) async -> DroneAction? {
        let cleaned = transcript.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !cleaned.isEmpty else { return nil }

        // Prefer the model's function call; fall back to keyword matching.
        if service.isAvailable,
           let raw = try? await service.complete(system: Self.systemPrompt, user: cleaned),
           let action = DroneAction.fromModelOutput(raw) {
            return action
        }
        return DroneIntent.match(cleaned)
    }

    static let systemPrompt: String = {
        let lines = DroneFunction.allCases
            .map { "- \($0.rawValue): \($0.purpose)" }
            .joined(separator: "\n")
        return """
        You control a small recon companion drone for a dismounted soldier. Map the \
        soldier's spoken command to exactly ONE function below, or "none" if nothing \
        fits. Reply with ONLY compact JSON, no prose:
        {"function":"<name>","value":<integer-or-null>}
        value is the magnitude in cm (moves) or degrees (rotations); use null when the \
        function takes no magnitude.

        Functions:
        \(lines)
        - none: command does not match any function
        """
    }()
}
