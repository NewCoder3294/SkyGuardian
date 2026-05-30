// Thin Swift bridge over the Cactus C API (on-device inference). Adapted from the
// BroadcastBrain integration, trimmed to what SkyGuardian needs: init, completion
// (text + native audio PCM), transcription, image embed, destroy.
//
// Guarded by `canImport(cactus)`: the app builds and ships WITHOUT the Cactus
// xcframework (voice/vision report UNAVAILABLE via the service fallback). To
// enable on device, add `cactus.xcframework` (iOS) to the target and a Gemma 3n
// model file — then this compiles in and lights everything up. Nothing here calls
// the network: inference is fully local.
#if canImport(cactus)
import Foundation
import cactus

public typealias CactusModelT = UnsafeMutableRawPointer

private let _frameworkInit: Void = {
    if let bundleId = Bundle.main.bundleIdentifier {
        bundleId.withCString { cactus_set_app_id($0) }
    }
}()

private let _bufferSize = 65536

public func cactusLastError() -> String { String(cString: cactus_get_last_error()) }

private func _err(_ msg: String) -> NSError {
    let e = cactusLastError()
    return NSError(domain: "cactus", code: -1, userInfo: [NSLocalizedDescriptionKey: e.isEmpty ? msg : e])
}

public func cactusInit(_ modelPath: String) throws -> CactusModelT {
    _ = _frameworkInit
    guard let h = cactus_init(modelPath, nil, false) else { throw _err("model init failed") }
    return h
}

public func cactusDestroy(_ model: CactusModelT) { cactus_destroy(model) }

/// Chat completion. `messagesJson` is the OpenAI-style messages array; pass
/// `pcmData` for native audio-in (voice). Returns the model's text.
public func cactusComplete(_ model: CactusModelT, _ messagesJson: String,
                           _ optionsJson: String? = nil, _ pcmData: Data? = nil) throws -> String {
    var buffer = [CChar](repeating: 0, count: _bufferSize)
    let result: Int32 = buffer.withUnsafeMutableBufferPointer { buf in
        if let pcm = pcmData {
            return pcm.withUnsafeBytes { p in
                cactus_complete(model, messagesJson, buf.baseAddress, buf.count, optionsJson, nil, nil, nil,
                                p.baseAddress?.assumingMemoryBound(to: UInt8.self), pcm.count)
            }
        }
        return cactus_complete(model, messagesJson, buf.baseAddress, buf.count, optionsJson, nil, nil, nil, nil, 0)
    }
    if result < 0 { throw _err("completion failed") }
    return String(cString: buffer)
}

/// Speech-to-text from raw PCM (16 kHz mono) — the voice path.
public func cactusTranscribe(_ model: CactusModelT, _ pcmData: Data, _ optionsJson: String? = nil) throws -> String {
    var buffer = [CChar](repeating: 0, count: _bufferSize)
    let result: Int32 = pcmData.withUnsafeBytes { p in
        buffer.withUnsafeMutableBufferPointer { buf in
            cactus_transcribe(model, nil, nil, buf.baseAddress, buf.count, optionsJson, nil, nil,
                              p.baseAddress?.assumingMemoryBound(to: UInt8.self), pcmData.count)
        }
    }
    if result < 0 { throw _err("transcription failed") }
    return String(cString: buffer)
}
#endif
