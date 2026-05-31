import CoreML
import CoreVideo
import Foundation
import QuartzCore
import Vision

/// One on-device detection from the Tello feed: a class label, confidence, and a
/// normalized rect in **SwiftUI top-left** coordinates (ready to draw over the video).
struct DetectedObject: Identifiable, Equatable {
    let id = UUID()
    let label: String
    let confidence: Float
    let rect: CGRect
}

/// Runs a bundled CoreML YOLO (NMS baked in) over the companion Tello's decoded
/// frames and publishes bounding-box detections for the feed overlay. Fully
/// on-device. Throttled so it never starves the follow loop or the video.
///
/// Not @MainActor — Vision runs on a serial background queue; published updates hop
/// to main. Frames are tapped via TelloDirectStream.onPixelBufferSecondary.
final class TelloObjectDetector: ObservableObject {
    @Published private(set) var detections: [DetectedObject] = []
    @Published private(set) var ready = false

    var minConfidence: Float = 0.35
    var maxObjects = 12

    private let queue = DispatchQueue(label: "tello.detector", qos: .userInitiated)
    private var visionModel: VNCoreMLModel?
    private var lastRun: CFTimeInterval = 0
    private let interval: CFTimeInterval = 0.12   // ~8 Hz cap — leaves headroom for video + follow

    init() {
        queue.async { [weak self] in self?.loadModel() }
    }

    private func loadModel() {
        // Xcode compiles the bundled .mlpackage to .mlmodelc; fall back to the raw
        // package name just in case.
        let url = Bundle.main.url(forResource: "yolov8n", withExtension: "mlmodelc")
            ?? Bundle.main.url(forResource: "yolov8n", withExtension: "mlpackage")
        guard let url else {
            DispatchQueue.main.async { self.ready = false }
            return
        }
        do {
            let cfg = MLModelConfiguration()
            cfg.computeUnits = .all                       // Neural Engine / GPU when available
            let model = try MLModel(contentsOf: url, configuration: cfg)
            visionModel = try VNCoreMLModel(for: model)
            DispatchQueue.main.async { self.ready = true }
        } catch {
            DispatchQueue.main.async { self.ready = false }
        }
    }

    /// Feed a decoded Tello frame. Throttled; cheap when it's not time to run.
    /// Capturing `pixelBuffer` in the async closure retains it (ARC) until done.
    func feed(_ pixelBuffer: CVPixelBuffer) {
        queue.async { [weak self] in
            guard let self, let vm = self.visionModel else { return }
            let t = CACurrentMediaTime()
            guard t - self.lastRun >= self.interval else { return }
            self.lastRun = t

            let request = VNCoreMLRequest(model: vm) { [weak self] req, _ in
                self?.handle(req.results)
            }
            request.imageCropAndScaleOption = .scaleFill
            let handler = VNImageRequestHandler(cvPixelBuffer: pixelBuffer, orientation: .up)
            try? handler.perform([request])
        }
    }

    private func handle(_ results: [Any]?) {
        let objs = (results as? [VNRecognizedObjectObservation]) ?? []
        let dets = objs.compactMap { o -> DetectedObject? in
            guard let top = o.labels.first, top.confidence >= minConfidence else { return nil }
            // Vision boundingBox is normalized with a BOTTOM-left origin; convert to
            // SwiftUI's top-left origin so the overlay maps straight onto the video.
            let b = o.boundingBox
            let rect = CGRect(x: b.minX, y: 1 - b.maxY, width: b.width, height: b.height)
            return DetectedObject(label: top.identifier, confidence: top.confidence, rect: rect)
        }
        .sorted { $0.confidence > $1.confidence }
        let top = Array(dets.prefix(maxObjects))
        DispatchQueue.main.async { self.detections = top }
    }

    func clear() { DispatchQueue.main.async { self.detections = [] } }
}
