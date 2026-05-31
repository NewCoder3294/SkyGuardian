import XCTest
@testable import ReconCompanion

final class DroneIntentTests: XCTestCase {
    func testFollowMeMapsToFollowMe() {
        XCTAssertEqual(DroneIntent.match("drone follow me")?.function, .followMe)
    }
    func testTrackMeMapsToVisualTrack() {
        XCTAssertEqual(DroneIntent.match("track me")?.function, .track)
    }
    func testTrackTheTagMapsToTrackTag() {
        XCTAssertEqual(DroneIntent.match("track the tag")?.function, .trackTag)
    }
    func testDesignateMapsToTrackTag() {
        XCTAssertEqual(DroneIntent.match("designate that")?.function, .trackTag)
    }
    func testConfirmMapsToConfirm() {
        XCTAssertEqual(DroneIntent.match("confirm")?.function, .confirm)
    }
    func testFollowMeDoesNotMatchTrackTag() {
        XCTAssertNotEqual(DroneIntent.match("follow me")?.function, .trackTag)
    }
    func testFollowThatTagMapsToTrackTag() {
        XCTAssertEqual(DroneIntent.match("follow that tag")?.function, .trackTag)
    }
    func testThatTagMapsToTrackTag() {
        XCTAssertEqual(DroneIntent.match("lock onto that tag")?.function, .trackTag)
    }
    func testBackwardsMapsToBack() {
        XCTAssertEqual(DroneIntent.match("go backwards")?.function, .back)
        XCTAssertEqual(DroneIntent.match("backwards")?.function, .back)
    }
    func testGoForwardMapsToForward() {
        XCTAssertEqual(DroneIntent.match("go forward")?.function, .forward)
    }
    func testFlyUpMapsToUp() {
        XCTAssertEqual(DroneIntent.match("fly up")?.function, .up)
    }
    func testComeDownMapsToDown() {
        XCTAssertEqual(DroneIntent.match("come down")?.function, .down)
    }
}
