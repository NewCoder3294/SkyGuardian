import XCTest
@testable import ReconCompanion

/// Scriptable CactusService double for driving DronePilot.resolve down each path.
/// Not a canned-data mock of the real backend: it only returns what a test scripts,
/// and throws (like the real serial path can) when no output is set.
private final class FakeCactus: CactusService {
    var available: Bool
    var output: String?

    init(available: Bool, output: String?) {
        self.available = available
        self.output = output
    }

    var sourceLabel: String { "FAKE" }
    var isAvailable: Bool { available }

    func transcribe(pcm16k: Data) async throws -> String {
        throw CactusError.failed("not used")
    }

    func analyze(imageJPEG: Data, prompt: String) async throws -> String {
        throw CactusError.failed("not used")
    }

    func complete(system: String, user: String) async throws -> String {
        guard let output else { throw CactusError.failed("no scripted output") }
        return output
    }
}

final class VoicePilotTests: XCTestCase {

    // MARK: - approach intent (keyword path)

    func testApproachPhraseResolvesToApproachViaKeyword() {
        XCTAssertEqual(DroneIntent.match("go investigate"), DroneAction(.approach))
        XCTAssertEqual(DroneIntent.match("approach the target"), DroneAction(.approach))
        XCTAssertEqual(DroneIntent.match("move in on that"), DroneAction(.approach))
    }

    func testApproachMapsToMissionCommand() {
        XCTAssertEqual(DroneFunction.approach.missionCommand, .approach)
    }

    // MARK: - DronePilot resolution paths

    func testResolveUsesKeywordOnlyRegardlessOfModelOutput() async {
        // LLM path is removed — resolve() is keyword-only.
        // "nudge up a bit" contains "up" → keyword fires → DroneAction(.up, nil).
        // Model JSON (even if parseable) is never consulted.
        let cactus = FakeCactus(available: true, output: "{\"function\":\"up\",\"value\":80}")
        let pilot = DronePilot(service: cactus)
        let action = await pilot.resolve("nudge up a bit")
        XCTAssertEqual(action, DroneAction(.up, nil))
    }

    func testResolveFallsBackToKeywordWhenUnavailable() async {
        let cactus = FakeCactus(available: false, output: "{\"function\":\"land\",\"value\":null}")
        let pilot = DronePilot(service: cactus)
        // Model output is ignored because the service is unavailable; keyword wins.
        let action = await pilot.resolve("hold position")
        XCTAssertEqual(action, DroneAction(.hold))
    }

    func testResolveFallsBackToKeywordWhenModelOutputDoesNotParse() async {
        let cactus = FakeCactus(available: true, output: "I think you should hold, soldier.")
        let pilot = DronePilot(service: cactus)
        let action = await pilot.resolve("hold position")
        XCTAssertEqual(action, DroneAction(.hold))
    }

    func testResolveReturnsNilForUnknownSpeech() async {
        let cactus = FakeCactus(available: true, output: "{\"function\":\"none\",\"value\":null}")
        let pilot = DronePilot(service: cactus)
        let action = await pilot.resolve("what's the weather like today")
        XCTAssertNil(action)
    }

    // MARK: - voice never breaks (unavailable backend)

    func testUnavailableServiceStillResolvesViaKeyword() async {
        let pilot = DronePilot(service: UnavailableCactusService(reason: "test"))
        let action = await pilot.resolve("stop")
        XCTAssertEqual(action, DroneAction(.stop))
    }

    // MARK: - VoiceController test seam

    @MainActor
    func testVoiceControllerFinalizeForTestingDeliversAction() async {
        let cactus = FakeCactus(available: false, output: nil)
        let controller = VoiceController(pilot: DronePilot(service: cactus))
        var delivered: DroneAction?
        await controller.finalizeForTesting("hold position") { delivered = $0 }
        XCTAssertEqual(delivered, DroneAction(.hold))
        XCTAssertEqual(controller.state, .idle)
        XCTAssertEqual(controller.lastAction, DroneAction(.hold))
    }
}
