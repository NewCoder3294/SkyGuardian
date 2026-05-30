import XCTest
@testable import ReconCompanion

final class FollowControllerTests: XCTestCase {
    private let fc = FollowController()

    private func tag(distance: Double = 2.0, bearingDeg: Double = 0,
                     elevDeg: Double = 0, margin: Float = 50) -> TagDetection {
        TagDetection(id: 0, center: .zero, corners: [], distance: distance,
                     bearingRad: bearingDeg * .pi / 180, elevationRad: elevDeg * .pi / 180,
                     decisionMargin: margin, imageSize: CGSize(width: 960, height: 720))
    }

    func testNoTagHovers() {
        XCTAssertEqual(fc.command(for: nil), .hover)
    }

    func testWeakDetectionHovers() {
        XCTAssertEqual(fc.command(for: tag(margin: 5)), .hover)
    }

    func testCenteredAtTargetDistanceHovers() {
        XCTAssertEqual(fc.command(for: tag()), .hover)
    }

    func testTagRightYawsRight() {
        XCTAssertGreaterThan(fc.command(for: tag(bearingDeg: 20)).yaw, 0)
    }

    func testTagLeftYawsLeft() {
        XCTAssertLessThan(fc.command(for: tag(bearingDeg: -20)).yaw, 0)
    }

    func testTooFarMovesForward() {
        XCTAssertGreaterThan(fc.command(for: tag(distance: 4)).fb, 0)
    }

    func testTooNearMovesBack() {
        XCTAssertLessThan(fc.command(for: tag(distance: 0.5)).fb, 0)
    }

    func testTagBelowCenterDescends() {
        XCTAssertLessThan(fc.command(for: tag(elevDeg: 25)).ud, 0)
    }

    func testTagAboveCenterClimbs() {
        XCTAssertGreaterThan(fc.command(for: tag(elevDeg: -25)).ud, 0)
    }

    func testYawClampsToMax() {
        XCTAssertEqual(fc.command(for: tag(bearingDeg: 90)).yaw, 45)
    }

    func testForwardClampsToMax() {
        XCTAssertEqual(fc.command(for: tag(distance: 50)).fb, 28)
    }

    func testSmallBearingInDeadbandYawsZero() {
        XCTAssertEqual(fc.command(for: tag(bearingDeg: 2)).yaw, 0)
    }
}
