import XCTest
@testable import ReconCompanion

final class IntentParserTests: XCTestCase {
    func testStopWinsAndIsRecognized() {
        XCTAssertEqual(IntentParser.parse("stop now"), .stop)
        XCTAssertEqual(IntentParser.parse("abort the mission"), .stop)
        // priority: stop beats follow if both appear
        XCTAssertEqual(IntentParser.parse("follow me, no stop"), .stop)
    }

    func testRecall() {
        XCTAssertEqual(IntentParser.parse("recall the drone"), .recall)
        XCTAssertEqual(IntentParser.parse("come back here"), .recall)
    }

    func testHold() {
        XCTAssertEqual(IntentParser.parse("hold position"), .hold)
        XCTAssertEqual(IntentParser.parse("stay there"), .hold)
    }

    func testFollow() {
        XCTAssertEqual(IntentParser.parse("drone follow me"), .followMe)
        XCTAssertEqual(IntentParser.parse("on me"), .followMe)
    }

    func testUnknownRejectedNotGuessed() {
        XCTAssertNil(IntentParser.parse("what's the weather"))
        XCTAssertNil(IntentParser.parse(""))
    }
}
