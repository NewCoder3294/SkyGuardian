import CoreVideo
import Foundation

/// Pinhole camera intrinsics (pixels). Defaults are derived from the Tello's field
/// of view at the stream resolution — approximate, but a P-controller tolerates the
/// error. Override after a calibration if you want tighter distance estimates.
struct CameraIntrinsics {
    var fx: Double, fy: Double, cx: Double, cy: Double

    /// Estimate from image size using the Tello front camera's ~82.6° diagonal FOV.
    static func tello(width: Int, height: Int) -> CameraIntrinsics {
        let w = Double(width), h = Double(height)
        // Horizontal FOV ≈ 72° for the 4:3 stream → fx = (w/2)/tan(hfov/2).
        let hfov = 72.0 * .pi / 180.0
        let fx = (w / 2.0) / tan(hfov / 2.0)
        return CameraIntrinsics(fx: fx, fy: fx, cx: w / 2.0, cy: h / 2.0)
    }
}

/// One detected tag, with everything the follow controller needs.
struct TagDetection {
    let id: Int
    let center: CGPoint          // image pixels
    let corners: [CGPoint]       // 4 corners, image pixels
    let distance: Double         // meters along the camera optical axis (pose tz)
    let bearingRad: Double       // horizontal angle to tag center (+ = tag is to the right)
    let elevationRad: Double     // vertical angle (+ = tag is below image center)
    let decisionMargin: Float    // detection confidence
    let imageSize: CGSize
}

/// On-device AprilTag detector (AprilRobotics C lib, tag36h11 — the family the hat
/// tag should be printed in). Detects on the luma (Y) plane of a 420 pixel buffer,
/// so there's no color conversion. Not thread-safe; call from one queue.
final class AprilTagDetector {
    private let family: UnsafeMutablePointer<apriltag_family_t>
    private let detector: UnsafeMutablePointer<apriltag_detector_t>

    /// Printed tag size (black border edge length) in meters. Set to match the hat tag.
    var tagSizeMeters: Double = 0.16
    /// If nil, intrinsics are estimated from the frame size each call.
    var intrinsics: CameraIntrinsics?

    init() {
        family = tag36h11_create()
        detector = apriltag_detector_create()
        apriltag_detector_add_family_bits(detector, family, 2)
        // Tuned for a live control loop on a phone: decimate for speed, light refine.
        detector.pointee.quad_decimate = 2.0
        detector.pointee.quad_sigma = 0.0
        detector.pointee.nthreads = 2
        detector.pointee.refine_edges = true
        detector.pointee.decode_sharpening = 0.25
    }

    deinit {
        apriltag_detector_destroy(detector)
        tag36h11_destroy(family)
    }

    func detect(_ pixelBuffer: CVPixelBuffer) -> [TagDetection] {
        CVPixelBufferLockBaseAddress(pixelBuffer, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(pixelBuffer, .readOnly) }

        // Y plane of a 420 biplanar buffer is the grayscale image we want.
        guard let base = CVPixelBufferGetBaseAddressOfPlane(pixelBuffer, 0) else { return [] }
        let width = CVPixelBufferGetWidthOfPlane(pixelBuffer, 0)
        let height = CVPixelBufferGetHeightOfPlane(pixelBuffer, 0)
        let srcStride = CVPixelBufferGetBytesPerRowOfPlane(pixelBuffer, 0)

        guard let img = image_u8_create(UInt32(width), UInt32(height)) else { return [] }
        defer { image_u8_destroy(img) }
        let dstStride = Int(img.pointee.stride)
        let dst = img.pointee.buf!
        let src = base.assumingMemoryBound(to: UInt8.self)
        let rowBytes = min(width, dstStride)
        for y in 0..<height {
            memcpy(dst.advanced(by: y * dstStride), src.advanced(by: y * srcStride), rowBytes)
        }

        guard let zarr = apriltag_detector_detect(detector, img) else { return [] }
        defer { apriltag_detections_destroy(zarr) }

        let intr = intrinsics ?? CameraIntrinsics.tello(width: width, height: height)
        let n = Int(zarr.pointee.size)
        let elSize = zarr.pointee.el_sz
        guard let dataBase = zarr.pointee.data else { return [] }

        var results: [TagDetection] = []
        for i in 0..<n {
            let det = dataBase.advanced(by: i * elSize)
                .withMemoryRebound(to: UnsafeMutablePointer<apriltag_detection_t>?.self, capacity: 1) { $0.pointee }
            guard let det else { continue }
            results.append(make(det, intr: intr, imageW: width, imageH: height))
        }
        return results
    }

    private func make(_ det: UnsafeMutablePointer<apriltag_detection_t>,
                      intr: CameraIntrinsics, imageW: Int, imageH: Int) -> TagDetection {
        let c = det.pointee.c
        let center = CGPoint(x: c.0, y: c.1)

        var p = det.pointee.p
        let corners: [CGPoint] = withUnsafeBytes(of: &p) { raw in
            let d = raw.bindMemory(to: Double.self)
            return (0..<4).map { CGPoint(x: d[$0 * 2], y: d[$0 * 2 + 1]) }
        }

        // Metric pose for distance (needs tag size + intrinsics).
        var info = apriltag_detection_info_t(det: det, tagsize: tagSizeMeters,
                                             fx: intr.fx, fy: intr.fy, cx: intr.cx, cy: intr.cy)
        var pose = apriltag_pose_t()
        _ = estimate_tag_pose(&info, &pose)
        let tz = matd_get(pose.t, 2, 0)
        let tx = matd_get(pose.t, 0, 0)
        let ty = matd_get(pose.t, 1, 0)
        let distance = tz > 0 ? tz : sqrt(tx * tx + ty * ty + tz * tz)
        matd_destroy(pose.R)
        matd_destroy(pose.t)

        // Bearing/elevation from the center pixel (robust, doesn't depend on tag size).
        let bearing = atan2(Double(center.x) - intr.cx, intr.fx)
        let elevation = atan2(Double(center.y) - intr.cy, intr.fy)

        return TagDetection(id: Int(det.pointee.id), center: center, corners: corners,
                            distance: distance, bearingRad: bearing, elevationRad: elevation,
                            decisionMargin: det.pointee.decision_margin,
                            imageSize: CGSize(width: imageW, height: imageH))
    }
}
