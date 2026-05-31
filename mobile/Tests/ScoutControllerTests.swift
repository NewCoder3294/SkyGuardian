import XCTest
@testable import ReconCompanion

final class ScoutControllerTests: XCTestCase {
    // Default-ish plan used by several tests.
    private func plan(legCm: Int = 120, legs: Int = 2, turnDeg: Int = 30,
                      scanDeg: Int = 30, scanSeconds: Double = 2, speed: Int = 60) -> [ScoutStep] {
        Scout.plan(legCm: legCm, legs: legs, turnDeg: turnDeg, scanDeg: scanDeg,
                   scanSeconds: scanSeconds, speedCmPerSec: speed)
    }

    func testStartsBySettingSpeed() {
        XCTAssertEqual(plan(speed: 60).first?.command, "speed 60")
    }

    func testHasOneForwardPerLeg() {
        let fwd = plan(legCm: 120, legs: 2).filter { $0.command == "forward 120" }
        XCTAssertEqual(fwd.count, 2)
    }

    func testIncludesScanSweep() {
        let cmds = plan(scanDeg: 30).compactMap { $0.command }
        XCTAssertTrue(cmds.contains("cw 30"))      // look right
        XCTAssertTrue(cmds.contains("ccw 60"))     // sweep left (2× scan)
    }

    func testRetraceReversesAndInvertsPath() {
        // legs=2, turn=30 → outbound path = [forward120, cw30, forward120];
        // retrace = inverse, reversed = [back120, ccw30, back120].
        let ret = plan(legCm: 120, legs: 2, turnDeg: 30).filter { $0.isReturn }.map { $0.command }
        XCTAssertEqual(ret, ["back 120", "ccw 30", "back 120"])
    }

    func testNoTurnMeansStraightRetrace() {
        let ret = plan(legCm: 100, legs: 2, turnDeg: 0).filter { $0.isReturn }.map { $0.command }
        XCTAssertEqual(ret, ["back 100", "back 100"])
    }

    func testBoundsClamped() {
        let s = plan(legCm: 9999, legs: 99)
        XCTAssertEqual(s.filter { $0.command == "forward \(Scout.maxLegCm)" }.count, Scout.maxLegs)
    }

    func testReturnStepsComeLast() {
        let steps = plan()
        let firstReturn = steps.firstIndex { $0.isReturn } ?? steps.count
        // No outbound (non-return) step appears after the first return step.
        XCTAssertFalse(steps[firstReturn...].contains { !$0.isReturn })
    }

    func testWaitsBoundedAndPositive() {
        let steps = plan()
        for s in steps { XCTAssertGreaterThanOrEqual(s.waitSeconds, 0) }
        XCTAssertLessThan(steps.reduce(0) { $0 + $1.waitSeconds }, 60.0)
    }
}
