import XCTest
@testable import ReconCompanion

final class ScoutControllerTests: XCTestCase {
    func testPlanIsForwardScanBack() {
        let steps = Scout.plan(forwardCm: 150, scanSeconds: 2.0)
        XCTAssertEqual(steps.count, 3)
        XCTAssertEqual(steps[0].command, "forward 150")
        XCTAssertNil(steps[1].command)              // scan-hold
        XCTAssertEqual(steps[1].waitSeconds, 2.0)
        XCTAssertEqual(steps[2].command, "back 150") // mirror return
    }

    func testForwardAndBackDistancesMatch() {
        let steps = Scout.plan(forwardCm: 120, scanSeconds: 1.0)
        XCTAssertEqual(steps[0].command, "forward 120")
        XCTAssertEqual(steps[2].command, "back 120")
    }

    func testDistanceClampedToSafeBounds() {
        // Over the cap -> clamped to maxCm.
        let hi = Scout.plan(forwardCm: 9999, scanSeconds: 0)
        XCTAssertEqual(hi[0].command, "forward \(Scout.maxCm)")
        // Under the SDK minimum -> clamped to minCm.
        let lo = Scout.plan(forwardCm: 1, scanSeconds: 0)
        XCTAssertEqual(lo[0].command, "forward \(Scout.minCm)")
    }

    func testWaitsArePositiveAndBounded() {
        let steps = Scout.plan(forwardCm: 200, scanSeconds: 2.0)
        for s in steps { XCTAssertGreaterThanOrEqual(s.waitSeconds, 0) }
        // Leg wait = 200/40 + 2 = 7s; total well under a sane ceiling.
        let total = steps.reduce(0) { $0 + $1.waitSeconds }
        XCTAssertLessThan(total, 30.0)
    }

    func testNegativeScanClampedToZero() {
        let steps = Scout.plan(forwardCm: 150, scanSeconds: -5)
        XCTAssertEqual(steps[1].waitSeconds, 0.0)
    }
}
