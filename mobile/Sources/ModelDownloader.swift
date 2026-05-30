import CryptoKit
import Foundation
import ZIPFoundation

/// Fetches the on-device Gemma 3n model (Cactus int4-apple weights) once, on first
/// launch, and unzips it into the app's Documents so Cactus can load it locally.
/// The download is online (one-time setup); inference afterward is fully offline.
///
/// Built on URLSessionDownloadTask for an efficient chunked transfer of a multi-GB
/// file, with progress and resume-on-drop. Integrity is enforced: the URL is pinned
/// to an immutable commit and the finished file's SHA-256 must match a constant
/// compiled into the app before it is unzipped.
final class ModelDownloader: NSObject, ObservableObject, URLSessionDownloadDelegate {
    enum State: Equatable { case absent, downloading(Double), verifying, unzipping, ready, failed(String) }
    @Published private(set) var state: State = .absent

    // Cactus hub (HuggingFace), int4 Apple build of Gemma 3n (E2B: audio + vision + text).
    static let modelId = "Cactus-Compute/gemma-4-E2B-it"
    static let weightsKey = "gemma-4-e2b-it"

    // Supply-chain hardening: pin to an IMMUTABLE commit (not mutable `main`) and verify
    // a SHA-256 baked into the app before unzipping. HuggingFace's LFS oid is the file's
    // SHA-256, so a mismatch means the artifact changed — refuse and delete.
    static let pinnedRevision = "7a1d39f97bbd1f87ba1d00f641f04991d6eb9fbb"
    static let expectedSHA256 = "3a6e33eb5a1b1d9cb9046ca2687d3dedbb564066d9925ebc51e142a788af8a22"
    static let expectedBytes: Int64 = 4_679_429_616
    private static var zipURL: URL {
        URL(string: "https://huggingface.co/\(modelId)/resolve/\(pinnedRevision)/weights/\(weightsKey)-int4-apple.zip")!
    }

    /// Final on-device model directory (what cactus_init is pointed at).
    static var modelDir: URL {
        let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        return docs.appendingPathComponent("models/\(weightsKey)")
    }

    static var isPresent: Bool {
        FileManager.default.fileExists(atPath: modelDir.path) &&
            ((try? FileManager.default.contentsOfDirectory(atPath: modelDir.path))?.isEmpty == false)
    }

    // The big download + its resume token live in Caches (not backed up to iCloud).
    private static var cachesDir: URL { FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0] }
    private static var partURL: URL { cachesDir.appendingPathComponent("\(weightsKey).zip") }
    private static var resumeURL: URL { cachesDir.appendingPathComponent("\(weightsKey).resume") }

    private lazy var session: URLSession = {
        let cfg = URLSessionConfiguration.default
        cfg.waitsForConnectivity = true            // wait out brief connectivity gaps
        cfg.timeoutIntervalForResource = 24 * 60 * 60
        return URLSession(configuration: cfg, delegate: self, delegateQueue: nil)
    }()
    private var task: URLSessionDownloadTask?
    private var continuation: CheckedContinuation<URL, Error>?

    /// Idempotent: download (resuming if a partial exists), verify, unzip. Safe to call
    /// again after a failure to retry.
    func ensureModel() async {
        if Self.isPresent { setState(.ready); return }
        do {
            setState(.downloading(0))
            let zip = try await runDownload()

            setState(.verifying)
            let digest = try Self.sha256(ofFileAt: zip)
            guard digest == Self.expectedSHA256 else {
                try? FileManager.default.removeItem(at: zip)
                setState(.failed("integrity check failed (hash mismatch)"))
                return
            }

            setState(.unzipping)
            try unzip(zip, to: Self.modelDir)
            try? FileManager.default.removeItem(at: zip)
            try? FileManager.default.removeItem(at: Self.resumeURL)
            setState(Self.isPresent ? .ready : .failed("unzip produced no files"))
        } catch {
            setState(.failed(error.localizedDescription))
        }
    }

    func cancel() { task?.cancel() }

    // MARK: download (URLSession delegate-driven)

    private func runDownload() async throws -> URL {
        try await withCheckedThrowingContinuation { cont in
            self.continuation = cont
            let t: URLSessionDownloadTask
            if let resume = try? Data(contentsOf: Self.resumeURL), !resume.isEmpty {
                t = session.downloadTask(withResumeData: resume)   // pick up where we left off
            } else {
                t = session.downloadTask(with: Self.zipURL)
            }
            self.task = t
            t.resume()
        }
    }

    func urlSession(_ session: URLSession, downloadTask: URLSessionDownloadTask,
                    didWriteData bytesWritten: Int64, totalBytesWritten: Int64,
                    totalBytesExpectedToWrite: Int64) {
        let total = totalBytesExpectedToWrite > 0 ? totalBytesExpectedToWrite : Self.expectedBytes
        setState(.downloading(min(max(Double(totalBytesWritten) / Double(total), 0), 1)))
    }

    func urlSession(_ session: URLSession, downloadTask: URLSessionDownloadTask,
                    didFinishDownloadingTo location: URL) {
        // Must move the file out synchronously — `location` is deleted when this returns.
        let dest = Self.partURL
        do {
            try? FileManager.default.removeItem(at: dest)
            try FileManager.default.moveItem(at: location, to: dest)
            try? FileManager.default.removeItem(at: Self.resumeURL)
            resume(returning: dest)
        } catch {
            resume(throwing: error)
        }
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        guard let error else { return }   // success is handled in didFinishDownloadingTo
        // Persist the resume token so a retry (even after relaunch) continues the transfer.
        if let resumeData = (error as NSError).userInfo[NSURLSessionDownloadTaskResumeData] as? Data {
            try? resumeData.write(to: Self.resumeURL)
        }
        resume(throwing: error)
    }

    private func resume(returning url: URL) {
        let c = continuation; continuation = nil
        c?.resume(returning: url)
    }
    private func resume(throwing error: Error) {
        let c = continuation; continuation = nil
        c?.resume(throwing: error)
    }

    // MARK: integrity + unzip

    /// Streaming SHA-256 over the downloaded file (chunked, constant memory).
    private static func sha256(ofFileAt url: URL) throws -> String {
        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }
        var hasher = SHA256()
        while case let chunk = handle.readData(ofLength: 1 << 20), !chunk.isEmpty {
            hasher.update(data: chunk)
        }
        return hasher.finalize().map { String(format: "%02x", $0) }.joined()
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

    private func setState(_ s: State) {
        DispatchQueue.main.async { if self.state != s { self.state = s } }
    }
}
