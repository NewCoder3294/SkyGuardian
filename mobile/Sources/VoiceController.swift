import AVFoundation
import Foundation

/// Push-to-talk voice control. Captures mic audio, resamples to 16 kHz mono PCM,
/// runs on-device transcription (Gemma 3n via Cactus), maps the transcript to the
/// closed Command vocabulary, and emits the intent. Honest about availability:
/// with no model/framework the state goes to .error (never a fake command).
@MainActor
final class VoiceController: ObservableObject {
    enum State: Equatable { case idle, listening, thinking, error(String) }

    @Published private(set) var state: State = .idle
    @Published private(set) var lastTranscript: String = ""
    @Published private(set) var lastAction: DroneAction?

    private var service: CactusService = CactusFactory.make()

    /// Rebuild the backend (e.g. after the model finishes downloading).
    func reloadService() { service = CactusFactory.make() }
    private let engine = AVAudioEngine()
    private var converter: AVAudioConverter?
    private var pcm = Data()
    private let pcmLock = NSLock()   // pcm is written on the audio render thread, read on main

    private let targetFormat = AVAudioFormat(
        commonFormat: .pcmFormatInt16, sampleRate: 16_000, channels: 1, interleaved: true)

    var sourceLabel: String { service.sourceLabel }
    var available: Bool { service.isAvailable }

    func toggle(onAction: @escaping (DroneAction) -> Void) {
        switch state {
        case .listening: stopAndProcess(onAction: onAction)
        default: startListening()
        }
    }

    private func startListening() {
        Task {
            guard await requestPermission() else { state = .error("MIC DENIED"); return }
            do {
                try configureSession()
                pcmLock.lock(); pcm.removeAll(keepingCapacity: true); pcmLock.unlock()
                let input = engine.inputNode
                let inFormat = input.outputFormat(forBus: 0)
                guard let target = targetFormat else { state = .error("FORMAT"); return }
                converter = AVAudioConverter(from: inFormat, to: target)
                input.installTap(onBus: 0, bufferSize: 2048, format: inFormat) { [weak self] buffer, _ in
                    self?.capture(buffer)
                }
                try engine.start()
                state = .listening
            } catch {
                state = .error("AUDIO")
            }
        }
    }

    private func stopAndProcess(onAction: @escaping (DroneAction) -> Void) {
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
        try? AVAudioSession.sharedInstance().setActive(false)
        pcmLock.lock(); let captured = pcm; pcmLock.unlock()
        state = .thinking
        let pilot = DronePilot(service: service)
        Task {
            do {
                let transcript = try await service.transcribe(pcm16k: captured)
                lastTranscript = transcript
                if let action = await pilot.resolve(transcript) {
                    lastAction = action
                    onAction(action)
                    state = .idle
                } else {
                    state = .error("NO INTENT")
                }
            } catch {
                state = .error(sourceLabel == "UNAVAILABLE" ? "NO MODEL" : "STT FAIL")
            }
        }
    }

    private func capture(_ buffer: AVAudioPCMBuffer) {
        guard let converter, let target = targetFormat else { return }
        let ratio = target.sampleRate / buffer.format.sampleRate
        let capacity = AVAudioFrameCount(Double(buffer.frameLength) * ratio) + 16
        guard let out = AVAudioPCMBuffer(pcmFormat: target, frameCapacity: capacity) else { return }
        var consumed = false
        var err: NSError?
        let status = converter.convert(to: out, error: &err) { _, status in
            if consumed { status.pointee = .noDataNow; return nil }
            consumed = true
            status.pointee = .haveData
            return buffer
        }
        // Only append real converted audio — drop error/empty results rather than
        // feeding garbage/stale samples to the recognizer.
        guard status == .haveData, err == nil, out.frameLength > 0, let ch = out.int16ChannelData else { return }
        let bytes = Int(out.frameLength) * MemoryLayout<Int16>.size
        let chunk = Data(bytes: ch[0], count: bytes)
        pcmLock.lock(); pcm.append(chunk); pcmLock.unlock()
    }

    private func configureSession() throws {
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.record, mode: .measurement, options: [.duckOthers])
        try session.setActive(true, options: .notifyOthersOnDeactivation)
    }

    private func requestPermission() async -> Bool {
        await withCheckedContinuation { cont in
            AVAudioApplication.requestRecordPermission { granted in cont.resume(returning: granted) }
        }
    }
}
