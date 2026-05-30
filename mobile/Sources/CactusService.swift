import Foundation

/// On-device multimodal backend (Gemma 3n via Cactus). Voice = native audio
/// transcription; vision = analyze a Tello frame. Offline at inference time.
protocol CactusService: AnyObject {
    var sourceLabel: String { get }   // short status-pill text
    var isAvailable: Bool { get }
    func transcribe(pcm16k: Data) async throws -> String
    func analyze(imageJPEG: Data, prompt: String) async throws -> String
    /// Text completion with a system + user message — used for function-calling
    /// (map a command transcript onto the closed drone-function vocabulary).
    func complete(system: String, user: String) async throws -> String
}

enum CactusError: Error, LocalizedError {
    case unavailable(String)
    case modelMissing(String)
    case failed(String)
    var errorDescription: String? {
        switch self {
        case .unavailable(let m): return "On-device AI unavailable: \(m)"
        case .modelMissing(let p): return "Gemma 3n model not found at \(p)"
        case .failed(let m): return "Inference failed: \(m)"
        }
    }
}

/// Honest fallback when the Cactus framework or model is absent. Throws from every
/// call — it is NOT a mock and never returns canned data, so the UI shows the truth.
final class UnavailableCactusService: CactusService {
    private let reason: String
    init(reason: String) { self.reason = reason }
    var sourceLabel: String { "UNAVAILABLE" }
    var isAvailable: Bool { false }
    func transcribe(pcm16k: Data) async throws -> String { throw CactusError.unavailable(reason) }
    func analyze(imageJPEG: Data, prompt: String) async throws -> String { throw CactusError.unavailable(reason) }
    func complete(system: String, user: String) async throws -> String { throw CactusError.unavailable(reason) }
}

/// Where the on-device model lives. The Gemma 3n file is downloaded once (online,
/// during setup) via Cactus's hub, then runs fully offline.
enum CactusConfig {
    /// The on-device model directory (downloaded by ModelDownloader on first run).
    static var modelPath: String { ModelDownloader.modelDir.path }
}

/// Builds the right backend: the real on-device service when the framework + model
/// are present, otherwise the honest Unavailable fallback.
enum CactusFactory {
    static func make() -> CactusService {
        #if canImport(cactus)
        let path = CactusConfig.modelPath
        guard FileManager.default.fileExists(atPath: path) else {
            return UnavailableCactusService(reason: "model not downloaded")
        }
        do { return try RealCactusService(modelPath: path) }
        catch { return UnavailableCactusService(reason: error.localizedDescription) }
        #else
        return UnavailableCactusService(reason: "Cactus framework not bundled")
        #endif
    }
}

#if canImport(cactus)
/// Real Cactus-backed inference. Serialized: cactus_complete is not thread-safe on
/// one model pointer, so every call funnels through one queue.
final class RealCactusService: CactusService {
    private let model: CactusModelT
    private let queue = DispatchQueue(label: "cactus.inference")

    init(modelPath: String) throws { self.model = try cactusInit(modelPath) }
    deinit { cactusDestroy(model) }

    var sourceLabel: String { "GEMMA 3N" }
    var isAvailable: Bool { true }

    func transcribe(pcm16k: Data) async throws -> String {
        try await run { try cactusTranscribe(self.model, pcm16k) }
    }

    func analyze(imageJPEG: Data, prompt: String) async throws -> String {
        // Multimodal completion: image as a base64 data URL in the message content.
        // NOTE: confirm the exact image-content shape against the Cactus iOS SDK.
        let b64 = imageJPEG.base64EncodedString()
        let messages = """
        [{"role":"user","content":[{"type":"text","text":\(jsonString(prompt))},\
        {"type":"image_url","image_url":{"url":"data:image/jpeg;base64,\(b64)"}}]}]
        """
        return try await run { try cactusComplete(self.model, messages) }
    }

    func complete(system: String, user: String) async throws -> String {
        let messages = """
        [{"role":"system","content":\(jsonString(system))},\
        {"role":"user","content":\(jsonString(user))}]
        """
        return try await run { try cactusComplete(self.model, messages) }
    }

    private func run(_ work: @escaping () throws -> String) async throws -> String {
        try await withCheckedThrowingContinuation { cont in
            queue.async {
                do { cont.resume(returning: try work()) }
                catch { cont.resume(throwing: error) }
            }
        }
    }

    private func jsonString(_ s: String) -> String {
        let data = (try? JSONEncoder().encode(s)) ?? Data("\"\"".utf8)
        return String(data: data, encoding: .utf8) ?? "\"\""
    }
}
#endif
