import SwiftUI
import UIKit

/// Reads an MJPEG (multipart/x-mixed-replace) stream from the laptop relay and
/// publishes decoded frames. The phone never touches the Tello directly — it only
/// renders the laptop's relayed feed. Pure transport; no business logic.
@MainActor
final class MJPEGStream: NSObject, ObservableObject {
    @Published private(set) var frame: UIImage?
    @Published private(set) var live = false

    private var task: URLSessionDataTask?
    private lazy var session = URLSession(configuration: .default, delegate: self, delegateQueue: nil)
    private var buffer = Data()

    private let soi = Data([0xFF, 0xD8])  // JPEG start
    private let eoi = Data([0xFF, 0xD9])  // JPEG end

    func start(urlString: String) {
        stop()
        guard let url = URL(string: urlString) else { return }
        buffer.removeAll(keepingCapacity: true)
        let t = session.dataTask(with: url)
        task = t
        t.resume()
    }

    func stop() {
        task?.cancel()
        task = nil
        live = false
    }

    fileprivate nonisolated func ingest(_ data: Data) {
        Task { @MainActor in self.parse(data) }
    }

    private func parse(_ data: Data) {
        buffer.append(data)
        // Extract every complete JPEG currently in the buffer.
        while let start = buffer.range(of: soi),
              let end = buffer.range(of: eoi, in: start.upperBound ..< buffer.endIndex) {
            let jpeg = buffer.subdata(in: start.lowerBound ..< end.upperBound)
            if let img = UIImage(data: jpeg) {
                frame = img
                live = true
            }
            buffer.removeSubrange(buffer.startIndex ..< end.upperBound)
        }
        // Guard against unbounded growth if a boundary never resolves.
        if buffer.count > 2_000_000 { buffer.removeAll(keepingCapacity: true) }
    }
}

extension MJPEGStream: URLSessionDataDelegate {
    nonisolated func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) {
        ingest(data)
    }
}

/// Displays a relayed MJPEG feed. Derives the HTTP feed URL from the ws server URL.
struct MJPEGView: View {
    let serverURL: String       // e.g. ws://host:8000/ws
    let path: String            // e.g. /video/tello
    @StateObject private var stream = MJPEGStream()

    var body: some View {
        ZStack {
            Color.black
            if let frame = stream.frame {
                Image(uiImage: frame)
                    .resizable()
                    .aspectRatio(contentMode: .fit)
            } else {
                VStack(spacing: 8) {
                    Text("◉ NO FEED").font(Theme.mono(13, weight: .semibold)).foregroundColor(Theme.faint)
                    Text(feedURL).font(Theme.mono(9)).foregroundColor(Theme.faint)
                }
            }
            VStack {
                HStack {
                    Text(stream.live ? "● TELLO LIVE" : "○ TELLO").font(Theme.mono(10, weight: .semibold))
                        .foregroundColor(stream.live ? Color(red: 0.4, green: 0.9, blue: 0.5) : Theme.faint)
                        .padding(6).background(Color.black.opacity(0.5))
                    Spacer()
                }
                Spacer()
            }
            .padding(8)
        }
        .onAppear { stream.start(urlString: feedURL) }
        .onDisappear { stream.stop() }
    }

    private var feedURL: String {
        var s = serverURL
        // Strip the "/ws" path suffix first, then swap only the scheme prefix.
        if let r = s.range(of: "/ws") { s = String(s[..<r.lowerBound]) }
        if s.hasPrefix("wss://") { s = "https://" + s.dropFirst("wss://".count) }
        else if s.hasPrefix("ws://") { s = "http://" + s.dropFirst("ws://".count) }
        return s + path
    }
}
