import CryptoKit
import Foundation
import ZIPFoundation

/// Downloads the on-device Gemma 3n model (Cactus int4-apple weights) on first run
/// and unzips it into the app's Documents, so Cactus can load it locally. The
/// download is online (one-time, setup); inference afterward is fully offline.
@MainActor
final class ModelDownloader: ObservableObject {
    enum State: Equatable { case absent, downloading(Double), unzipping, ready, failed(String) }
    @Published private(set) var state: State = .absent

    // Cactus hub (HuggingFace), int4 Apple build of Gemma 3n (E2B: audio + vision + text).
    nonisolated static let modelId = "Cactus-Compute/gemma-4-E2B-it"
    nonisolated static let weightsKey = "gemma-4-e2b-it"

    // Supply-chain hardening: pin to an IMMUTABLE commit (not mutable `main`) and verify
    // a SHA-256 baked into the app before unzipping. HuggingFace's LFS oid is the file's
    // SHA-256, so a mismatch means the artifact changed — refuse and delete.
    nonisolated static let pinnedRevision = "7a1d39f97bbd1f87ba1d00f641f04991d6eb9fbb"
    nonisolated static let expectedSHA256 = "3a6e33eb5a1b1d9cb9046ca2687d3dedbb564066d9925ebc51e142a788af8a22"
    nonisolated static let expectedBytes: Int64 = 4_679_429_616
    nonisolated private static var zipURL: URL {
        URL(string: "https://huggingface.co/\(modelId)/resolve/\(pinnedRevision)/weights/\(weightsKey)-int4-apple.zip")!
    }

    /// Final on-device model directory (what cactus_init is pointed at).
    nonisolated static var modelDir: URL {
        let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        return docs.appendingPathComponent("models/\(weightsKey)")
    }

    nonisolated static var isPresent: Bool {
        FileManager.default.fileExists(atPath: modelDir.path) &&
            ((try? FileManager.default.contentsOfDirectory(atPath: modelDir.path))?.isEmpty == false)
    }

    func ensureModel() async {
        if Self.isPresent { state = .ready; return }
        do {
            state = .downloading(0)
            let (zip, digestHex) = try await download(Self.zipURL)
            // Integrity gate: refuse anything whose SHA-256 doesn't match the pinned hash.
            guard digestHex == Self.expectedSHA256 else {
                try? FileManager.default.removeItem(at: zip)
                state = .failed("integrity check failed (hash mismatch)")
                return
            }
            state = .unzipping
            try unzip(zip, to: Self.modelDir)
            try? FileManager.default.removeItem(at: zip)
            state = Self.isPresent ? .ready : .failed("unzip produced no files")
        } catch {
            state = .failed(error.localizedDescription)
        }
    }

    /// Streams the download to disk while computing its SHA-256 incrementally
    /// (no second pass over a multi-GB file). Returns the temp path and hex digest.
    private func download(_ url: URL) async throws -> (URL, String) {
        let (bytes, response) = try await URLSession.shared.bytes(from: url)
        // Reject up front if the server advertises a different size than we pinned.
        let advertised = response.expectedContentLength
        if advertised > 0, advertised != Self.expectedBytes {
            throw CactusError.failed("unexpected model size \(advertised)")
        }
        let total = Self.expectedBytes
        let tmp = FileManager.default.temporaryDirectory.appendingPathComponent("model.zip")
        try? FileManager.default.removeItem(at: tmp)
        FileManager.default.createFile(atPath: tmp.path, contents: nil)
        let handle = try FileHandle(forWritingTo: tmp)
        defer { try? handle.close() }
        var hasher = SHA256()
        var buf = Data(); var written: Int64 = 0; var lastReport = 0.0
        for try await byte in bytes {
            buf.append(byte)
            if buf.count >= 1 << 20 {
                hasher.update(data: buf)
                handle.write(buf); written += Int64(buf.count); buf.removeAll(keepingCapacity: true)
                let p = Double(written) / Double(total)
                if p - lastReport > 0.01 { lastReport = p; state = .downloading(p) }
            }
        }
        if !buf.isEmpty { hasher.update(data: buf); handle.write(buf) }
        let hex = hasher.finalize().map { String(format: "%02x", $0) }.joined()
        return (tmp, hex)
    }

    private func unzip(_ zip: URL, to dir: URL) throws {
        try? FileManager.default.removeItem(at: dir)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        try FileManager.default.unzipItem(at: zip, to: dir)
        // Flatten if the zip wrapped everything in a single top folder.
        let items = (try? FileManager.default.contentsOfDirectory(atPath: dir.path)) ?? []
        if items.count == 1 {
            let inner = dir.appendingPathComponent(items[0])
            var isDir: ObjCBool = false
            if FileManager.default.fileExists(atPath: inner.path, isDirectory: &isDir), isDir.boolValue {
                for f in (try? FileManager.default.contentsOfDirectory(atPath: inner.path)) ?? [] {
                    try? FileManager.default.moveItem(at: inner.appendingPathComponent(f),
                                                      to: dir.appendingPathComponent(f))
                }
            }
        }
    }
}
