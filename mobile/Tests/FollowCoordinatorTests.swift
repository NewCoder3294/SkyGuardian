import XCTest
@testable import ReconCompanion

/// Records every command the follow loop emits, so we can assert on rc/send
/// without a real Tello. Conforms to the production DroneCommandSink protocol.
final class RecordingCommandSink: DroneCommandSink {
    private(set) var sent: [String] = []
    private(set) var rcs: [RCCommand] = []
    var lastRC: RCCommand? { rcs.last }
    func send(_ command: String) { sent.append(command) }
    func rc(_ command: RCCommand) { rcs.append(command) }
}

final class FollowCoordinatorTests: XCTestCase {
    private var sink: RecordingCommandSink!
    private var clock: CFTimeInterval!
    private var coord: FollowCoordinator!

    override func setUp() {
        super.setUp()
        sink = RecordingCommandSink()
        clock = 1000
        coord = FollowCoordinator(commands: sink, now: { [weak self] in self?.clock ?? 0 })
    }

    private func tag(distance: Double = 2.0, bearingDeg: Double = 0, margin: Float = 50) -> TagDetection {
        TagDetection(id: 0, center: .zero, corners: [], distance: distance,
                     bearingRad: bearingDeg * .pi / 180, elevationRad: 0,
                     decisionMargin: margin, imageSize: CGSize(width: 960, height: 720))
    }

    func testDisarmedTickEmitsNothing() {
        coord.tickForTest()
        XCTAssertNil(sink.lastRC)
    }

    func testRequestLockFromAirborneEntersSearchingNotFollowing() {
        coord.enterAirborneForTest(mode: .visualMe)
        coord.requestLock(.visualMe)
        coord.drainForTest()   // settle rcQueue work + stop the real timer
        XCTAssertEqual(coord.currentPhase, .searching)
    }
    func testRequestLockClearsConfirmationSoTickHovers() {
        coord.enterAirborneForTest(mode: .visualMe)
        coord.requestLock(.tag)
        coord.drainForTest()   // apply confirmed=false/latest=nil before injecting
        coord.injectDetectionForTest(tag(), age: 0)
        coord.tickForTest()
        XCTAssertEqual(sink.lastRC, .hover)
    }
    func testRequestLockThenConfirmThenTickFollows() {
        coord.enterAirborneForTest(mode: .visualMe)
        coord.requestLock(.visualMe)
        coord.drainForTest()   // apply confirmed=false/latest=nil before injecting
        coord.injectDetectionForTest(tag(bearingDeg: 20), age: 0)
        coord.confirmTarget()
        coord.drainForTest()   // apply confirmed=true from confirmTarget()'s rcQueue body
        coord.tickForTest()
        XCTAssertGreaterThan(sink.lastRC?.yaw ?? 0, 0)
    }
}
