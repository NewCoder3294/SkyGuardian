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
    @Published private(set) var lastCommand: Command?

    private let service: CactusService = CactusFactory.make()
    private let engine = AVAudioEngine()
    private var converter: AVAudioConverter?
    private var pcm = Data()

    private let targetFormat = AVAudioFormat(
        commonFormat: .pcmFormatInt16, sampleRate: 16_000, channels: 1, interleaved: true)

    var sourceLabel: String { service.sourceLabel }
    var available: Bool { service.isAvailable }

    func toggle(onCommand: @escaping (Command) -> Void) {
        switch state {
        case .listening: stopAndProcess(onCommand: onCommand)
        default: startListening()
        }
    }

    private func startListening() {
        Task {
            guard await requestPermission() else { state = .error("MIC DENIED"); return }
            do {
                try configureSession()
                pcm.removeAll(keepingCapacity: true)
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

    private func stopAndProcess(onCommand: @escaping (Command) -> Void) {
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
        try? AVAudioSession.sharedInstance().setActive(false)
        let captured = pcm
        state = .thinking
        Task {
            do {
                let transcript = try await service.transcribe(pcm16k: captured)
                lastTranscript = transcript
                if let command = IntentParser.parse(transcript) {
                    lastCommand = command
                    onCommand(command)
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
        converter.convert(to: out, error: &err) { _, status in
            if consumed { status.pointee = .noDataNow; return nil }
            consumed = true
            status.pointee = .haveData
            return buffer
        }
        if let ch = out.int16ChannelData {
            let bytes = Int(out.frameLength) * MemoryLayout<Int16>.size
            pcm.append(UnsafeBufferPointer(start: ch[0], count: Int(out.frameLength)).withMemoryRebound(to: UInt8.self) { _ in
                Data(bytes: ch[0], count: bytes)
            })
        }
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
