import XCTest
@testable import ReconCompanion

/// The mobile map and the web dashboard map are both read-only subscribers to
/// the same laptop "brain" over a `/ws` WebSocket — neither talks to the other.
/// For them to render the same world model they must default to the same brain
/// address. The backend binds :8000 (backend/run.sh) and the dashboard defaults
/// to :8000 (frontend/src/lib/wsConfig.ts); these tests pin the mobile client to
/// the same port and endpoint so a drift on this side fails loudly.
final class WorldClientConfigTests: XCTestCase {

    @MainActor
    func testDefaultServerURLParses() {
        let url = URL(string: WorldClient().serverURL)
        XCTAssertNotNil(url, "default serverURL must be a valid URL")
    }

    @MainActor
    func testDefaultServerURLTargetsPort8000() {
        let comps = URLComponents(string: WorldClient().serverURL)
        XCTAssertEqual(comps?.port, 8000)
    }

    @MainActor
    func testDefaultServerURLUsesWsScheme() {
        let comps = URLComponents(string: WorldClient().serverURL)
        XCTAssertEqual(comps?.scheme, "ws")
    }

    @MainActor
    func testDefaultServerURLSubscribesToWsEndpoint() {
        let comps = URLComponents(string: WorldClient().serverURL)
        XCTAssertEqual(comps?.path, "/ws")
    }
}
