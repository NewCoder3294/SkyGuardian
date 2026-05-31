import AVFoundation
import Foundation
import Network
import VideoToolbox

/// Direct phone↔Tello video — no laptop. The phone joins the Tello's WiFi, sends
/// the SDK `command`/`streamon` over UDP, receives the raw H.264 stream on UDP
/// 11111, reassembles NAL units, and feeds them to an AVSampleBufferDisplayLayer
/// (which decodes + renders). Offline, single Tello client. The soldier's mobile kit.
///
/// Threading: networking + H.264 parsing run on a serial background queue; @Published
/// state and the CALayer enqueue hop to main.
final class TelloDirectStream: ObservableObject {
    enum State: Equatable { case idle, connecting, streaming, error(String) }
    @Published private(set) var state: State = .idle

    let displayLayer = AVSampleBufferDisplayLayer()

    /// Optional tap: decoded frames as CVPixelBuffers (Y-plane = grayscale) for the
    /// follow loop's AprilTag detection. Called on a VideoToolbox thread — hop off it.
    var onPixelBuffer: ((CVPixelBuffer) -> Void)?

    /// Secondary tap on the same decoded frames (e.g. the on-device object detector
    /// drawing bounding boxes), independent of the follow loop's `onPixelBuffer`.
    /// Called on a VideoToolbox thread — hop off it.
    var onPixelBufferSecondary: ((CVPixelBuffer) -> Void)?

    private let videoPort: UInt16 = 11111

    private let q = DispatchQueue(label: "tello.video")
    private var video: NWListener?
    private var formatDesc: CMVideoFormatDescription?
    private var decoder: VTDecompressionSession?
    private var sps: Data?
    private var pps: Data?
    private var assembly = Data()
    private var started = false

    func start() {
        DispatchQueue.main.async { self.displayLayer.videoGravity = .resizeAspect }   // CALayer → main
        setState(.connecting)
        // Confine all stream state (started/video/decoder/sps/pps/...) to q.
        q.async {
            guard !self.started else { return }   // FEED view or follow loop may both start it
            self.started = true
            // The shared commander owns the control channel (command/streamon/keepalive),
            // so voice flight control and the video stream share one socket to the Tello.
            TelloCommander.shared.startVideo()
            self.openVideo()
        }
    }

    func stop() {
        // Leave the command channel up — voice may still control the drone after the
        // video tab is dismissed. Only the video listener is torn down here.
        q.async {
            self.started = false
            self.video?.cancel(); self.video = nil
            if let d = self.decoder {
                // Drain in-flight async decode callbacks before invalidating, so the
                // unretained back-pointer in the callback can't fire post-teardown.
                VTDecompressionSessionWaitForAsynchronousFrames(d)
                VTDecompressionSessionInvalidate(d)
                self.decoder = nil
            }
        }
        setState(.idle)
    }

    private func setState(_ s: State) {
        DispatchQueue.main.async { if self.state != s { self.state = s } }
    }

    // MARK: video channel (UDP :11111 <- Tello)

    private func openVideo() {
        do {
            let params = NWParameters.udp
            params.allowLocalEndpointReuse = true
            let listener = try NWListener(using: params, on: .init(rawValue: videoPort)!)
            video = listener
            listener.newConnectionHandler = { [weak self] conn in
                guard let self else { return }
                conn.start(queue: self.q)
                self.receive(on: conn)
            }
            listener.start(queue: q)
        } catch {
            setState(.error("UDP \(videoPort) busy"))
        }
    }

    private func receive(on conn: NWConnection) {
        conn.receiveMessage { [weak self] data, _, _, err in
            guard let self else { return }
            if let data, !data.isEmpty { self.ingest(packet: data) }
            if err == nil { self.receive(on: conn) }
        }
    }

    /// The Tello splits each frame across ≤1460-byte UDP packets; a packet shorter
    /// than 1460 bytes ends the current frame buffer.
    private func ingest(packet: Data) {
        assembly.append(packet)
        if packet.count < 1460 {
            let frame = assembly
            assembly = Data()
            handleFrame(frame)
        }
    }

    private func handleFrame(_ annexB: Data) {
        for nal in nalUnits(annexB) {
            guard let first = nal.first else { continue }
            switch first & 0x1F {
            case 7: sps = nal; rebuildFormat()
            case 8: pps = nal; rebuildFormat()
            case 1, 5: enqueue(picture: nal)
            default: break
            }
        }
    }

    /// Split an Annex-B buffer (00 00 00 01 / 00 00 01 start codes) into NAL units.
    private func nalUnits(_ data: Data) -> [Data] {
        var units: [Data] = []
        let b = [UInt8](data)
        var i = 0, start = -1
        while i + 3 < b.count {
            let sc4 = b[i] == 0 && b[i+1] == 0 && b[i+2] == 0 && b[i+3] == 1
            let sc3 = b[i] == 0 && b[i+1] == 0 && b[i+2] == 1
            if sc4 || sc3 {
                if start >= 0 { units.append(Data(b[start..<i])) }
                i += sc4 ? 4 : 3
                start = i
            } else { i += 1 }
        }
        if start >= 0 && start < b.count { units.append(Data(b[start...])) }
        return units
    }

    private func rebuildFormat() {
        guard let sps, let pps else { return }
        var desc: CMVideoFormatDescription?
        let r = sps.withUnsafeBytes { s in
            pps.withUnsafeBytes { p -> OSStatus in
                let params = [s.bindMemory(to: UInt8.self).baseAddress!,
                              p.bindMemory(to: UInt8.self).baseAddress!]
                let sizes = [sps.count, pps.count]
                return CMVideoFormatDescriptionCreateFromH264ParameterSets(
                    allocator: kCFAllocatorDefault, parameterSetCount: 2,
                    parameterSetPointers: params, parameterSetSizes: sizes,
                    nalUnitHeaderLength: 4, formatDescriptionOut: &desc)
            }
        }
        if r == noErr, let desc {
            formatDesc = desc
            makeDecoder(desc)
        }
    }

    /// VideoToolbox session that decodes to a 420 pixel buffer (Y = grayscale) for
    /// AprilTag detection. Recreated whenever the H.264 parameter sets change.
    private func makeDecoder(_ fmt: CMVideoFormatDescription) {
        if let d = decoder { VTDecompressionSessionInvalidate(d); decoder = nil }
        let attrs: [CFString: Any] = [
            kCVPixelBufferPixelFormatTypeKey: kCVPixelFormatType_420YpCbCr8BiPlanarFullRange
        ]
        var callback = VTDecompressionOutputCallbackRecord(
            decompressionOutputCallback: { refcon, _, status, _, imageBuffer, _, _ in
                guard status == noErr, let imageBuffer, let refcon else { return }
                let me = Unmanaged<TelloDirectStream>.fromOpaque(refcon).takeUnretainedValue()
                me.onPixelBuffer?(imageBuffer)
                me.onPixelBufferSecondary?(imageBuffer)
            },
            decompressionOutputRefCon: Unmanaged.passUnretained(self).toOpaque())
        var session: VTDecompressionSession?
        VTDecompressionSessionCreate(allocator: kCFAllocatorDefault, formatDescription: fmt,
                                     decoderSpecification: nil, imageBufferAttributes: attrs as CFDictionary,
                                     outputCallback: &callback, decompressionSessionOut: &session)
        decoder = session
    }

    private func enqueue(picture nal: Data) {
        guard let formatDesc else { return }
        var avcc = Data()
        var len = UInt32(nal.count).bigEndian
        withUnsafeBytes(of: &len) { avcc.append(contentsOf: $0) }
        avcc.append(nal)

        let raw = UnsafeMutableRawPointer.allocate(byteCount: avcc.count, alignment: 1)
        avcc.copyBytes(to: raw.assumingMemoryBound(to: UInt8.self), count: avcc.count)
        var block: CMBlockBuffer?
        guard CMBlockBufferCreateWithMemoryBlock(
            allocator: kCFAllocatorDefault, memoryBlock: raw, blockLength: avcc.count,
            blockAllocator: kCFAllocatorDefault, customBlockSource: nil, offsetToData: 0,
            dataLength: avcc.count, flags: 0, blockBufferOut: &block) == noErr, let block else {
            raw.deallocate(); return
        }
        var sample: CMSampleBuffer?
        var sizes = [avcc.count]
        guard CMSampleBufferCreateReady(
            allocator: kCFAllocatorDefault, dataBuffer: block, formatDescription: formatDesc,
            sampleCount: 1, sampleTimingEntryCount: 0, sampleTimingArray: nil,
            sampleSizeEntryCount: 1, sampleSizeArray: &sizes, sampleBufferOut: &sample) == noErr,
            let sample else { return }
        if let atts = CMSampleBufferGetSampleAttachmentsArray(sample, createIfNecessary: true),
           CFArrayGetCount(atts) > 0 {
            let d = unsafeBitCast(CFArrayGetValueAtIndex(atts, 0), to: CFMutableDictionary.self)
            CFDictionarySetValue(d,
                Unmanaged.passUnretained(kCMSampleAttachmentKey_DisplayImmediately).toOpaque(),
                Unmanaged.passUnretained(kCFBooleanTrue).toOpaque())
        }
        DispatchQueue.main.async {
            self.displayLayer.enqueue(sample)
            if self.state != .streaming { self.state = .streaming }
        }

        // Tee the same frame to the decoder for follow-loop detection and/or the
        // object detector (only when something is tapping).
        if (onPixelBuffer != nil || onPixelBufferSecondary != nil), let dec = decoder {
            VTDecompressionSessionDecodeFrame(dec, sampleBuffer: sample,
                                              flags: [._EnableAsynchronousDecompression],
                                              frameRefcon: nil, infoFlagsOut: nil)
        }
    }
}
