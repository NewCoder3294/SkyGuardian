import AVFoundation
import Foundation
import Speech

/// Push-to-talk voice control. Speech→text runs on Apple's ON-DEVICE recognizer
/// (`SFSpeechRecognizer`, fully offline) — NOT Cactus, because Gemma 3n's
/// `cactus_transcribe` path null-derefs (it has no STT backend). The transcript is
/// mapped to the closed drone-command vocabulary by `DroneIntent`. Gemma is still
/// used for vision elsewhere; this path is deterministic and can't crash the C lib.
/// Honest about availability: with speech denied/unavailable the state goes to .error.
@MainActor
final class VoiceController: ObservableObject {
    enum State: Equatable { case idle, listening, thinking, error(String) }

    @Published private(set) var state: State = .idle
    @Published private(set) var lastTranscript: String = ""
    @Published private(set) var lastAction: DroneAction?

    private let engine = AVAudioEngine()
    private let recognizer = SFSpeechRecognizer(locale: Locale(identifier: "en-US"))
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?
    private var onAction: ((DroneAction) -> Void)?
    private var authorized = false

    /// Resolves a transcript to a drone action: on-device LLM (Gemma via Cactus)
    /// first, deterministic keyword matcher as a fallback so voice never breaks.
    private let pilot: DronePilot

    init(pilot: DronePilot? = nil) {
        self.pilot = pilot ?? DronePilot(service: CactusFactory.make())
    }

    var sourceLabel: String { available ? "ON-DEVICE STT" : "VOICE" }
    /// Available only when on-device recognition is supported. SkyGuardian is
    /// offline-only (no cloud calls at runtime), so cloud-backed STT does not
    /// count as available — the operator must have the on-device dictation
    /// model installed (iOS Settings → General → Keyboard → Dictation).
    var available: Bool {
        authorized
            && (recognizer?.isAvailable ?? false)
            && (recognizer?.supportsOnDeviceRecognition ?? false)
    }

    /// Kept for API parity with the old Cactus-backed path; just re-checks auth.
    func reloadService() { Task { _ = await ensureAuth() } }

    func toggle(onAction: @escaping (DroneAction) -> Void) {
        switch state {
        case .listening: stopAndProcess()
        default: start(onAction: onAction)
        }
    }

    // MARK: listen

    private func start(onAction: @escaping (DroneAction) -> Void) {
        self.onAction = onAction
        lastTranscript = ""
        Task {
            guard await ensureAuth() else { state = .error("MIC/STT DENIED"); return }
            guard let recognizer, recognizer.isAvailable else { state = .error("STT UNAVAILABLE"); return }
            // Hard offline gate: refuse to listen unless the device can transcribe
            // on-device. Without this, SFSpeech silently streams audio to Apple's
            // servers — a cloud call this system is not allowed to make.
            guard recognizer.supportsOnDeviceRecognition else {
                state = .error("STT NEEDS ON-DEVICE MODEL")
                return
            }
            do {
                try configureSession()
                let req = SFSpeechAudioBufferRecognitionRequest()
                req.shouldReportPartialResults = true
                req.requiresOnDeviceRecognition = true // offline-only: never use cloud STT
                request = req

                let input = engine.inputNode
                let format = input.outputFormat(forBus: 0)
                input.installTap(onBus: 0, bufferSize: 2048, format: format) { [weak self] buffer, _ in
                    self?.request?.append(buffer)
                }
                engine.prepare()
                try engine.start()

                task = recognizer.recognitionTask(with: req) { [weak self] result, error in
                    Task { @MainActor in self?.handle(result: result, error: error) }
                }
                state = .listening
            } catch {
                cleanup()
                state = .error("AUDIO")
            }
        }
    }

    /// Stop capture and let the recognizer deliver its final transcript (→ handle()).
    private func stopAndProcess() {
        guard state == .listening else { return }
        state = .thinking
        engine.inputNode.removeTap(onBus: 0)
        engine.stop()
        request?.endAudio()
    }

    private var silenceTimer: Timer?

    private func handle(result: SFSpeechRecognitionResult?, error: Error?) {
        if let result {
            lastTranscript = result.bestTranscription.formattedString
            if result.isFinal { finalize(lastTranscript); return }
            // Heard something → auto-finish after a short pause (no second tap needed).
            if state == .listening, !lastTranscript.isEmpty { restartSilenceTimer() }
            return
        }
        // No result + error/end. If we were processing, decide on whatever we heard.
        if state == .thinking { finalize(lastTranscript) }
        else if state == .listening, error != nil { cleanup(); state = .error("STT FAIL") }
    }

    private func restartSilenceTimer() {
        silenceTimer?.invalidate()
        silenceTimer = Timer.scheduledTimer(withTimeInterval: 1.2, repeats: false) { [weak self] _ in
            Task { @MainActor in self?.stopAndProcess() }
        }
    }

    private func finalize(_ transcript: String) {
        cleanup()
        let cleaned = transcript.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !cleaned.isEmpty else { state = .error("NO SPEECH"); return }
        // Route through the on-device LLM first (keyword matcher backs it up inside
        // DronePilot.resolve). resolve is async, so hop onto a MainActor task.
        state = .thinking
        Task { @MainActor in
            if let action = await pilot.resolve(cleaned) {
                lastAction = action
                onAction?(action)
                state = .idle
            } else {
                state = .error("NO INTENT")
            }
        }
    }

    /// Test seam: runs the same transcript → resolve → onAction path as `finalize`,
    /// without any audio/STT setup. Awaits the pilot directly so tests are
    /// deterministic and don't race a detached Task.
    func finalizeForTesting(_ transcript: String, onAction: @escaping (DroneAction) -> Void) async {
        let cleaned = transcript.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !cleaned.isEmpty else { state = .error("NO SPEECH"); return }
        state = .thinking
        if let action = await pilot.resolve(cleaned) {
            lastAction = action
            onAction(action)
            state = .idle
        } else {
            state = .error("NO INTENT")
        }
    }

    private func cleanup() {
        silenceTimer?.invalidate(); silenceTimer = nil
        task?.cancel(); task = nil
        request = nil
        if engine.isRunning { engine.inputNode.removeTap(onBus: 0); engine.stop() }
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }

    // MARK: session + auth

    private func configureSession() throws {
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.record, mode: .measurement, options: [.duckOthers])
        try session.setActive(true, options: .notifyOthersOnDeactivation)
    }

    private func ensureAuth() async -> Bool {
        let speech = await withCheckedContinuation { (c: CheckedContinuation<Bool, Never>) in
            SFSpeechRecognizer.requestAuthorization { c.resume(returning: $0 == .authorized) }
        }
        let mic = await withCheckedContinuation { (c: CheckedContinuation<Bool, Never>) in
            AVAudioApplication.requestRecordPermission { c.resume(returning: $0) }
        }
        authorized = speech && mic
        return authorized
    }
}
