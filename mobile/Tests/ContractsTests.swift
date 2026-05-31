import XCTest
@testable import ReconCompanion

final class ContractsTests: XCTestCase {

    // Exact frame the backend emits (backend/app/server.py -> WorldSnapshot).
    func testDecodeWorldSnapshot() throws {
        let json = """
        {"type":"world_snapshot","t":12.5,"entities":[
          {"id":"soldier_1","type":"soldier","position":{"x":3.0,"y":-1.0,"z":0.0},
           "confidence":1.0,"timestamp":12.5,"source":"manual","label":"operator","ttl_s":5.0,"status":"active"},
          {"id":"hazard_1","type":"hazard","position":{"x":1.5,"y":-3.5,"z":0.0},
           "confidence":0.66,"timestamp":12.5,"source":"yolo","label":"debris","ttl_s":5.0,"status":"stale"}
        ]}
        """
        let message = try JSONDecoder().decode(ServerMessage.self, from: Data(json.utf8))
        guard case .worldSnapshot(let snap) = message else { return XCTFail("wrong variant") }
        XCTAssertEqual(snap.entities.count, 2)
        XCTAssertEqual(snap.entities[0].type, .soldier)
        XCTAssertEqual(snap.entities[0].position.x, 3.0)
        XCTAssertEqual(snap.entities[0].ttlS, 5.0)
        XCTAssertEqual(snap.entities[1].status, .stale)
        XCTAssertEqual(snap.entities[1].source, .yolo)
    }

    func testDecodeMissionStateWithNullError() throws {
        let json = #"{"type":"mission_state","stage":"following","last_error":null,"t":1.0}"#
        let message = try JSONDecoder().decode(ServerMessage.self, from: Data(json.utf8))
        guard case .missionState(let state) = message else { return XCTFail("wrong variant") }
        XCTAssertEqual(state.stage, "following")
        XCTAssertNil(state.lastError)
    }

    func testDecodeHealth() throws {
        let json = #"{"type":"health","tello":"connected","mavic":"streaming","perception":"running","t":2.0}"#
        let message = try JSONDecoder().decode(ServerMessage.self, from: Data(json.utf8))
        guard case .health(let h) = message else { return XCTFail("wrong variant") }
        XCTAssertEqual(h.tello, "connected")
    }

    func testUnknownTypeIsTolerated() throws {
        let json = #"{"type":"future_thing","x":1}"#
        let message = try JSONDecoder().decode(ServerMessage.self, from: Data(json.utf8))
        guard case .unknown(let t) = message else { return XCTFail("should be unknown") }
        XCTAssertEqual(t, "future_thing")
    }

    // Intent must serialize to exactly the shape the backend validates (Contract B).
    func testEncodeIntentMatchesWireFormat() throws {
        let intent = IntentMessage(command: .stop, source: "phone", t: 7.0)
        let data = try JSONEncoder().encode(intent)
        let obj = try XCTUnwrap(try JSONSerialization.jsonObject(with: data) as? [String: Any])
        XCTAssertEqual(obj["type"] as? String, "intent")
        XCTAssertEqual(obj["command"] as? String, "stop")
        XCTAssertEqual(obj["source"] as? String, "phone")
    }

    func testCommandRawValues() {
        XCTAssertEqual(Command.followMe.rawValue, "follow_me")
        XCTAssertEqual(Command.approach.rawValue, "approach")
        XCTAssertEqual(Command.allCases.count, 5)
    }

    func testBuildingsUpdatedDecodesAsUnknown() throws {
        let json = #"{"type":"buildings_updated","origin":{"lat":32.0,"lng":-117.0},"radius_m":400,"count":12,"t":3.5}"#
        let message = try JSONDecoder().decode(ServerMessage.self, from: Data(json.utf8))
        guard case .unknown(let t) = message else { return XCTFail("should be unknown (mobile does not consume buildings)") }
        XCTAssertEqual(t, "buildings_updated")
    }
}
