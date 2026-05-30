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
    nonisolated private static var zipURL: URL {
        URL(string: "https://huggingface.co/\(modelId)/resolve/main/weights/\(weightsKey)-int4-apple.zip")!
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
            let zip = try await download(Self.zipURL)
            state = .unzipping
            try unzip(zip, to: Self.modelDir)
            try? FileManager.default.removeItem(at: zip)
            state = Self.isPresent ? .ready : .failed("unzip produced no files")
        } catch {
            state = .failed(error.localizedDescription)
        }
    }

    private func download(_ url: URL) async throws -> URL {
        let (bytes, response) = try await URLSession.shared.bytes(from: url)
        let total = max(response.expectedContentLength, 1)
        let tmp = FileManager.default.temporaryDirectory.appendingPathComponent("model.zip")
        try? FileManager.default.removeItem(at: tmp)
        FileManager.default.createFile(atPath: tmp.path, contents: nil)
        let handle = try FileHandle(forWritingTo: tmp)
        defer { try? handle.close() }
        var buf = Data(); var written: Int64 = 0; var lastReport = 0.0
        for try await byte in bytes {
            buf.append(byte)
            if buf.count >= 1 << 20 {
                handle.write(buf); written += Int64(buf.count); buf.removeAll(keepingCapacity: true)
                let p = Double(written) / Double(total)
                if p - lastReport > 0.01 { lastReport = p; state = .downloading(p) }
            }
        }
        if !buf.isEmpty { handle.write(buf) }
        return tmp
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
