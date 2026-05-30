import XCTest
import CoreGraphics
@testable import ReconCompanion

final class MapProjectionTests: XCTestCase {
    let size = CGSize(width: 200, height: 200)

    func testOriginMapsToCentre() {
        let proj = MapProjection(spanMeters: 20)
        let p = proj.point(for: Vec3(x: 0, y: 0, z: 0), in: size)
        XCTAssertEqual(p.x, 100, accuracy: 0.001)
        XCTAssertEqual(p.y, 100, accuracy: 0.001)
    }

    func testScaleFitsSpanAcrossShorterDimension() {
        let proj = MapProjection(spanMeters: 20)
        // 200 px / 20 m = 10 px per metre.
        XCTAssertEqual(proj.scale(in: size), 10, accuracy: 0.001)
    }

    func testWorldYIsUpScreenYIsDown() {
        let proj = MapProjection(spanMeters: 20)   // 10 px/m
        let p = proj.point(for: Vec3(x: 2, y: 3, z: 0), in: size)
        XCTAssertEqual(p.x, 120, accuracy: 0.001)  // +x right
        XCTAssertEqual(p.y, 70, accuracy: 0.001)   // +y up -> smaller screen y
    }

    func testSpanIsClampedPositive() {
        let proj = MapProjection(spanMeters: 0)
        XCTAssertGreaterThan(proj.scale(in: size), 0)
    }
}
