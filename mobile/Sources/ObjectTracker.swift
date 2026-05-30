import CoreVideo
import Foundation
import Vision

/// Tag-free visual tracking: lock onto whatever the operator has centered ("track
/// that boat") and follow it frame-to-frame. Class-agnostic — it tracks an image
/// REGION, so it works for a boat, a car, a person, anything. Fully on-device.
///
/// Lock: pick the salient object nearest frame center (what you aimed at). Then each
/// frame runs VNTrackObjectRequest to follow that region. Not thread-safe; call from
/// one queue (the detect queue).
final class ObjectTracker {
    private let sequence = VNSequenceRequestHandler()
    private var observation: VNDetectedObjectObservation?
    /// Apparent height at lock time — the standoff reference (hold this size).
    private(set) var lockedHeight: CGFloat = 0

    var isLocked: Bool { observation != nil }

    func reset() { observation = nil; lockedHeight = 0 }

    /// Seed tracking with the salient object nearest the frame center. Falls back to a
    /// centered box if saliency finds nothing. Returns true once locked.
    @discardableResult
    func lock(in pixelBuffer: CVPixelBuffer) -> Bool {
        let req = VNGenerateObjectnessBasedSaliencyImageRequest()
        try? VNImageRequestHandler(cvPixelBuffer: pixelBuffer, orientation: .up).perform([req])

        let box: CGRect
        if let sal = req.results?.first as? VNSaliencyImageObservation,
           let objects = sal.salientObjects, !objects.isEmpty {
            box = objects.min(by: { Self.centerDist($0.boundingBox) < Self.centerDist($1.boundingBox) })!.boundingBox
        } else {
            box = CGRect(x: 0.35, y: 0.35, width: 0.30, height: 0.30)  // assume centered target
        }
        observation = VNDetectedObjectObservation(boundingBox: box)
        lockedHeight = box.height
        return true
    }

    /// Update the tracked region. Returns the new box (Vision-normalized, bottom-left
    /// origin) + confidence, or nil if tracking was lost.
    func update(in pixelBuffer: CVPixelBuffer) -> (box: CGRect, confidence: Float)? {
        guard let obs = observation else { return nil }
        let req = VNTrackObjectRequest(detectedObjectObservation: obs)
        req.trackingLevel = .accurate
        do {
            try sequence.perform([req], on: pixelBuffer, orientation: .up)
        } catch {
            observation = nil
            return nil
        }
        guard let updated = req.results?.first as? VNDetectedObjectObservation,
              updated.confidence > 0.3 else {
            observation = nil
            return nil
        }
        observation = updated
        return (updated.boundingBox, updated.confidence)
    }

    private static func centerDist(_ b: CGRect) -> CGFloat {
        let dx = b.midX - 0.5, dy = b.midY - 0.5
        return dx * dx + dy * dy
    }
}
