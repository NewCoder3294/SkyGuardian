import AVFoundation
import CoreVideo
import Foundation

/// Phone back-camera capture that detects the LAUNCH ANCHOR AprilTag and exposes
/// its latest range + bearing. `FrameAligner` uses this (with the compass heading)
/// to co-register the phone's launch frame with the laptop's world frame.
///
/// Fully offline / on-device: frames feed the local `AprilTagDetector` (tag36h11)
/// on a dedicated capture queue; only the anchor tag's range/bearing is published
/// back on the main actor. The detector is touched exclusively from `videoQueue`.
///
/// Not @MainActor — the AVFoundation delegate runs off-main; published updates hop
/// to the main queue explicitly.
final class AnchorCamera: NSObject, ObservableObject {
    /// Latest detection of the anchor tag (nil until seen). Range (m) + bearing (rad).
    @Published private(set) var latest: AnchorFix?
    @Published private(set) var isRunning = false
    @Published private(set) var permissionDenied = false

    struct AnchorFix: Equatable {
        let distance: Double
        let bearingRad: Double
        let decisionMargin: Float
    }

    /// The AprilTag id printed on the launch anchor marker. Distinct from the
    /// soldier follow tag id. Set to match your printed anchor before `start()`.
    var anchorTagID: Int = 0
    /// Printed anchor tag edge length (black border), metres.
    var anchorTagSizeMeters: Double = 0.16 {
        didSet { videoQueue.async { [detector, anchorTagSizeMeters] in detector.tagSizeMeters = anchorTagSizeMeters } }
    }

    private let session = AVCaptureSession()
    private let videoQueue = DispatchQueue(label: "anchor.camera.video")
    private let output = AVCaptureVideoDataOutput()
    private let detector = AprilTagDetector()

    /// Request camera access (if needed) and start capture. Idempotent.
    func start() {
        switch AVCaptureDevice.authorizationStatus(for: .video) {
        case .authorized:
            configureAndRun()
        case .notDetermined:
            AVCaptureDevice.requestAccess(for: .video) { [weak self] granted in
                guard let self else { return }
                if granted { self.configureAndRun() }
                else { DispatchQueue.main.async { self.permissionDenied = true } }
            }
        default:
            DispatchQueue.main.async { self.permissionDenied = true }
        }
    }

    func stop() {
        videoQueue.async { [session] in
            if session.isRunning { session.stopRunning() }
        }
        DispatchQueue.main.async { self.isRunning = false }
    }

    private func configureAndRun() {
        videoQueue.async { [weak self] in
            guard let self else { return }
            self.detector.tagSizeMeters = self.anchorTagSizeMeters

            if self.session.inputs.isEmpty {
                self.session.beginConfiguration()
                self.session.sessionPreset = .high
                guard
                    let device = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .back),
                    let input = try? AVCaptureDeviceInput(device: device),
                    self.session.canAddInput(input)
                else {
                    self.session.commitConfiguration()
                    DispatchQueue.main.async { self.permissionDenied = true }
                    return
                }
                self.session.addInput(input)

                // 420 biplanar so the detector's Y-plane path applies directly.
                self.output.videoSettings = [
                    kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange,
                ]
                self.output.alwaysDiscardsLateVideoFrames = true
                self.output.setSampleBufferDelegate(self, queue: self.videoQueue)
                if self.session.canAddOutput(self.output) { self.session.addOutput(self.output) }
                self.session.commitConfiguration()
            }

            if !self.session.isRunning { self.session.startRunning() }
            DispatchQueue.main.async { self.isRunning = true }
        }
    }
}

extension AnchorCamera: AVCaptureVideoDataOutputSampleBufferDelegate {
    func captureOutput(_ output: AVCaptureOutput, didOutput sampleBuffer: CMSampleBuffer,
                       from connection: AVCaptureConnection) {
        // Runs on videoQueue — the only queue allowed to touch `detector`.
        guard let pixelBuffer = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
        detector.intrinsics = CameraIntrinsics.phone(
            width: CVPixelBufferGetWidth(pixelBuffer),
            height: CVPixelBufferGetHeight(pixelBuffer),
        )
        let detections = detector.detect(pixelBuffer)
        guard let anchor = detections.first(where: { $0.id == anchorTagID && $0.distance > 0 }) else { return }
        let fix = AnchorFix(distance: anchor.distance, bearingRad: anchor.bearingRad,
                            decisionMargin: anchor.decisionMargin)
        DispatchQueue.main.async { self.latest = fix }
    }
}
