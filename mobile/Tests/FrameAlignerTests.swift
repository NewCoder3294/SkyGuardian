import XCTest
@testable import ReconCompanion

@MainActor
final class FrameAlignerTests: XCTestCase {
    func testUnalignedReturnsNil() {
        let aligner = FrameAligner()
        XCTAssertNil(aligner.toWorld(Vec3(x: 1, y: 2, z: 0)))
    }

    func testTagDueNorthPlacesOperatorDueSouth() {
        // Heading 0 (facing north), tag straight ahead (bearing 0) at 5 m.
        // Tag is 5 m north of operator → operator is at (0, -5) in world frame.
        let aligner = FrameAligner()
        aligner.observe(distance: 5, bearingRad: 0, headingDeg: 0)
        let op = try! XCTUnwrap(aligner.toWorld(Vec3(x: 0, y: 0, z: 0)))
        XCTAssertEqual(op.x, 0, accuracy: 1e-6)
        XCTAssertEqual(op.y, -5, accuracy: 1e-6)
    }

    func testDronePointTranslatesByOperatorOffset() {
        // Same anchor; a drone 3 m north of the operator (0,3) → world (0, -2).
        let aligner = FrameAligner()
        aligner.observe(distance: 5, bearingRad: 0, headingDeg: 0)
        let drone = try! XCTUnwrap(aligner.toWorld(Vec3(x: 0, y: 3, z: 0)))
        XCTAssertEqual(drone.x, 0, accuracy: 1e-6)
        XCTAssertEqual(drone.y, -2, accuracy: 1e-6)
    }

    func testReobservationUpdatesTransform() {
        let aligner = FrameAligner()
        aligner.observe(distance: 5, bearingRad: 0, headingDeg: 0)
        aligner.observe(distance: 10, bearingRad: 0, headingDeg: 0) // tag now 10 m north
        let op = try! XCTUnwrap(aligner.toWorld(Vec3(x: 0, y: 0, z: 0)))
        XCTAssertEqual(op.y, -10, accuracy: 1e-6)
    }

    func testIgnoresInvalidObservation() {
        let aligner = FrameAligner()
        aligner.observe(distance: 0, bearingRad: 0, headingDeg: 0)   // distance 0 → ignored
        XCTAssertNil(aligner.operatorWorld)
        aligner.observe(distance: .nan, bearingRad: 0, headingDeg: 0) // NaN → ignored
        XCTAssertNil(aligner.operatorWorld)
    }
}
