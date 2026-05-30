# DronePilot/Cactus on the Live Voice Path — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route the live voice transcript through the on-device Cactus/Gemma LLM (`DronePilot`) first, falling back to the deterministic `DroneIntent.match` keyword matcher when the model is unavailable or doesn't parse — so voice gains real LLM understanding without ever breaking. Add an "approach/investigate target" voice intent that routes to the backend's new `APPROACH` command.

**Architecture:** `VoiceController.finalize()` currently calls `DroneIntent.match(cleaned)` directly. We inject a `DronePilot` (built from `CactusFactory.make()`) and call its async `resolve()` instead — `DronePilot` already prefers the LLM and falls back to `DroneIntent.match`, so the fallback is guaranteed. A new `DroneFunction.approach` maps to a new mission `Command.approach`, routed to the laptop via `WorldClient.send`. `ContentView.handle` gains an `.approach` branch (gated by the existing confirmation-dialog pattern). The deterministic `IntentParser` used by `IntentParserTests` is untouched.

**Tech Stack:** Swift 5, SwiftUI, Speech (`SFSpeechRecognizer`), the bundled `cactus.xcframework`. Tests are XCTest (`@testable import ReconCompanion`). Build/run is native Xcode only (no CLI build in this environment) — tests are authored to run in the Xcode test target.

---

## File Structure

- Modify `mobile/Sources/VoiceController.swift` — inject `DronePilot`, call `resolve()` in `finalize`.
- Modify `mobile/Sources/DroneFunction.swift` — add `.approach` case (purpose, mission mapping, keyword phrases).
- Modify `mobile/Sources/Contracts.swift` — add `Command.approach`.
- Modify `mobile/Sources/ContentView.swift` — handle `.approach` (confirmation + `client.send`).
- Create `mobile/Tests/VoicePilotTests.swift` — fallback + resolution behavior with a fake `CactusService`.
- Modify `mobile/Tests/IntentParserTests.swift` — unchanged assertions must still pass (regression guard); add approach-phrase coverage to `DroneIntent`.

> **Build note:** All steps below are authored as code edits + XCTest cases. "Run the test" means run the named test in the Xcode test target (⌘U or the test diamond). There is no command-line build in this environment.

---

### Task 1: Add the `approach` drone function + mission command

**Files:**
- Modify: `mobile/Sources/Contracts.swift` (Command enum)
- Modify: `mobile/Sources/DroneFunction.swift` (enum case, purpose, missionCommand, DroneIntent phrase)
- Test: `mobile/Tests/VoicePilotTests.swift`

- [ ] **Step 1: Write the failing test**

```swift
// mobile/Tests/VoicePilotTests.swift
import XCTest
@testable import ReconCompanion

final class VoicePilotTests: XCTestCase {
    func testApproachPhraseMatchesViaKeywordFallback() {
        XCTAssertEqual(DroneIntent.match("investigate that contact")?.function, .approach)
        XCTAssertEqual(DroneIntent.match("approach the target")?.function, .approach)
        XCTAssertEqual(DroneIntent.match("go investigate")?.function, .approach)
    }

    func testApproachIsAMissionCommand() {
        XCTAssertEqual(DroneFunction.approach.missionCommand, .approach)
        XCTAssertFalse(DroneFunction.approach.isFlight)
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run in Xcode: `VoicePilotTests` (⌘U).
Expected: COMPILE FAIL — `.approach` is not a member of `DroneFunction` / `Command`.

- [ ] **Step 3: Implement**

In `mobile/Sources/Contracts.swift`, add to `Command`:

```swift
enum Command: String, Codable, CaseIterable, Sendable {
    case followMe = "follow_me"
    case hold
    case recall
    case stop
    case approach
}
```

In `mobile/Sources/DroneFunction.swift`, add the case to the mission-intents line:

```swift
    // mission intents (routed to the laptop when connected)
    case followMe = "follow_me", hold, recall, stop, approach
```

Add to `missionCommand`:

```swift
    var missionCommand: Command? {
        switch self {
        case .followMe: return .followMe
        case .hold: return .hold
        case .recall: return .recall
        case .stop: return .stop
        case .approach: return .approach
        default: return nil
        }
    }
```

Add to `purpose`:

```swift
        case .approach: return "autonomously approach and hold standoff on the selected target"
```

Add a phrase line in `DroneIntent.match`, immediately after the `track` line (so a deliberate "approach/investigate" phrase resolves before generic movement):

```swift
        if has(t, ["investigate", "approach the target", "approach target", "investigate that", "go investigate", "move in on"]) { return DroneAction(.approach) }
```

- [ ] **Step 4: Run test to verify it passes**

Run in Xcode: `VoicePilotTests`.
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add mobile/Sources/Contracts.swift mobile/Sources/DroneFunction.swift mobile/Tests/VoicePilotTests.swift
git commit -m "feat(mobile): add approach/investigate intent + mission command"
```

---

### Task 2: DronePilot resolves via LLM, falls back to keyword

**Files:**
- Test: `mobile/Tests/VoicePilotTests.swift` (add) — uses a fake `CactusService`.
- No production change in this task: `DronePilot.resolve` already exists. This task **locks its contract** with tests so the next task can rely on it.

- [ ] **Step 1: Write the failing test**

```swift
// append to mobile/Tests/VoicePilotTests.swift

/// Fake Cactus backend whose `complete` output and availability are scripted.
final class FakeCactus: CactusService {
    var sourceLabel: String { "FAKE" }
    var available: Bool
    var completion: String?            // nil => throw (simulate failure)
    init(available: Bool, completion: String?) { self.available = available; self.completion = completion }
    var isAvailable: Bool { available }
    func transcribe(pcm16k: Data) async throws -> String { throw CactusError.unavailable("n/a") }
    func analyze(imageJPEG: Data, prompt: String) async throws -> String { throw CactusError.unavailable("n/a") }
    func complete(system: String, user: String) async throws -> String {
        guard let c = completion else { throw CactusError.failed("no output") }
        return c
    }
}

extension VoicePilotTests {
    func testPilotUsesModelOutputWhenItParses() async {
        let svc = FakeCactus(available: true, completion: #"{"function":"up","value":50}"#)
        let action = await DronePilot(service: svc).resolve("climb fifty")
        XCTAssertEqual(action?.function, .up)
        XCTAssertEqual(action?.magnitude, 50)
    }

    func testPilotFallsBackToKeywordWhenModelUnavailable() async {
        let svc = FakeCactus(available: false, completion: nil)
        let action = await DronePilot(service: svc).resolve("take off")
        XCTAssertEqual(action?.function, .takeoff)   // came from DroneIntent.match
    }

    func testPilotFallsBackWhenModelOutputDoesNotParse() async {
        let svc = FakeCactus(available: true, completion: "I think you want to land")
        let action = await DronePilot(service: svc).resolve("land now")
        XCTAssertEqual(action?.function, .land)       // fell back to keyword
    }

    func testPilotReturnsNilForUnknownSpeech() async {
        let svc = FakeCactus(available: true, completion: #"{"function":"none","value":null}"#)
        let action = await DronePilot(service: svc).resolve("what's the weather")
        XCTAssertNil(action)
    }
}
```

> NOTE: `DronePilot.resolve` reads `service.isAvailable`. Confirm the protocol property is named `isAvailable` (it is, per `CactusService`). The `FakeCactus.available`/`isAvailable` split keeps the initializer readable.

- [ ] **Step 2: Run test to verify it fails (or passes immediately)**

Run in Xcode: `VoicePilotTests`.
Expected: PASS if `DronePilot.resolve` already behaves as specified; if `none`-function isn't rejected, see Step 3.

- [ ] **Step 3: Adjust only if needed**

`DroneAction.fromModelOutput` returns `nil` for unknown function names, and `DroneFunction(rawValue: "none")` is already nil (no `none` case), so `{"function":"none"}` → `fromModelOutput` returns nil → `resolve` falls back to `DroneIntent.match("what's the weather")` → nil. No change expected. If a future `none` case is added, ensure `resolve` treats it as nil.

- [ ] **Step 4: Run test to verify it passes**

Run in Xcode: `VoicePilotTests`.
Expected: PASS (4 added tests).

- [ ] **Step 5: Commit**

```bash
git add mobile/Tests/VoicePilotTests.swift
git commit -m "test(mobile): lock DronePilot resolve + fallback contract"
```

---

### Task 3: Inject DronePilot into VoiceController.finalize

**Files:**
- Modify: `mobile/Sources/VoiceController.swift`
- Test: covered by Task 2's contract tests; add a VoiceController-level test that the resolver is used.

- [ ] **Step 1: Write the failing test**

```swift
// append to mobile/Tests/VoicePilotTests.swift
extension VoicePilotTests {
    @MainActor
    func testVoiceControllerResolvesThroughPilotThenCallsBack() async {
        // A pilot backed by a fake model that returns a parseable "hold".
        let svc = FakeCactus(available: true, completion: #"{"function":"hold","value":null}"#)
        let vc = VoiceController(pilot: DronePilot(service: svc))
        var delivered: DroneAction?
        let exp = expectation(description: "action delivered")
        // finalizeForTesting() exposes the transcript→action path without audio.
        await vc.finalizeForTesting("hold position") { action in
            delivered = action; exp.fulfill()
        }
        await fulfillment(of: [exp], timeout: 2.0)
        XCTAssertEqual(delivered?.function, .hold)
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run in Xcode: `VoicePilotTests`.
Expected: COMPILE FAIL — `VoiceController` has no `init(pilot:)` and no `finalizeForTesting`.

- [ ] **Step 3: Implement — inject the pilot and make finalize use it**

In `mobile/Sources/VoiceController.swift`:

1. Add a stored pilot and an injecting initializer (keep a default so production call sites need no change):

```swift
    private let pilot: DronePilot

    init(pilot: DronePilot? = nil) {
        self.pilot = pilot ?? DronePilot(service: CactusFactory.make())
    }
```

2. Replace the body of `finalize(_:)` so it resolves through the pilot. `resolve` is `async`, so wrap in a `Task`:

```swift
    private func finalize(_ transcript: String) {
        cleanup()
        let cleaned = transcript.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !cleaned.isEmpty else { state = .error("NO SPEECH"); return }
        state = .thinking
        Task { @MainActor in
            if let action = await pilot.resolve(cleaned) {
                lastAction = action
                onAction?(action)
                state = .idle
            } else {
                state = .error("NO INTENT")
            }
        }
    }
```

3. Add a test-only seam that runs the same resolve path without audio:

```swift
    /// Test seam: run the transcript→action path directly (no microphone).
    func finalizeForTesting(_ transcript: String, onAction: @escaping (DroneAction) -> Void) async {
        self.onAction = onAction
        if let action = await pilot.resolve(transcript.trimmingCharacters(in: .whitespacesAndNewlines)) {
            lastAction = action
            onAction(action)
            state = .idle
        } else {
            state = .error("NO INTENT")
        }
    }
```

> The existing `sourceLabel`/`available`/STT gating and the on-device-only guard from the security fix are unchanged — STT still runs on-device; only the post-transcript resolution now goes through the LLM-first pilot.

- [ ] **Step 4: Run test to verify it passes**

Run in Xcode: `VoicePilotTests` and `IntentParserTests` (regression).
Expected: PASS — and `IntentParserTests` still green (untouched parser).

- [ ] **Step 5: Commit**

```bash
git add mobile/Sources/VoiceController.swift mobile/Tests/VoicePilotTests.swift
git commit -m "feat(mobile): resolve voice transcript via DronePilot (LLM-first, keyword fallback)"
```

---

### Task 4: Route `.approach` in ContentView with a confirmation gate

**Files:**
- Modify: `mobile/Sources/ContentView.swift` (`handle(_:)` + the existing confirmation-dialog pattern)
- Test: manual on-device (UI). Logic guard below is exercised by the DroneIntent/missionCommand tests already written.

> NOTE: `ContentView.swift` is actively edited in your working tree. Re-read `handle(_ action: DroneAction)` and the `pendingArm`/`confirmationDialog` block immediately before editing so this slots into the current code.

- [ ] **Step 1: Add the `.approach` branch to `handle`**

In `handle(_ action: DroneAction)`, before the generic `if fn.isFlight` branch:

```swift
    if fn == .approach {
        // Autonomous nav: deliberate + state-changing → confirm like track/arm,
        // then route to the laptop which owns the approach controller.
        guard isConnected else { return }   // approach is laptop-side autonomy
        pendingApproach = true               // drives a confirmationDialog
        return
    }
```

- [ ] **Step 2: Add the confirmation dialog + send**

Add state near the other `pending*` vars:

```swift
    @State private var pendingApproach = false
```

Add a confirmation dialog alongside the existing arm/track dialogs:

```swift
    .confirmationDialog("Begin autonomous approach?", isPresented: $pendingApproach, titleVisibility: .visible) {
        Button("Approach target", role: .destructive) { client.send(.approach) }
        Button("Cancel", role: .cancel) {}
    } message: {
        Text("The companion drone will autonomously fly to the selected target and hold standoff.")
    }
```

- [ ] **Step 3: Verify it compiles and the existing dialogs still work**

Build in Xcode (⌘B). Manually: say/select "investigate that contact" → confirmation appears → confirm → `client.send(.approach)` is dispatched (observe the laptop receiving `Command.approach`).

- [ ] **Step 4: Commit**

```bash
git add mobile/Sources/ContentView.swift
git commit -m "feat(mobile): voice/UI approach intent with confirmation, routed to laptop"
```

---

### Task 5: ModelDownloader/availability sanity for the demo

**Files:**
- Modify: none required if the Gemma 3n model is already downloaded; otherwise verify `ModelDownloader` fetches it.
- Test: `mobile/Tests/VoicePilotTests.swift` (add a guard that the factory degrades honestly).

- [ ] **Step 1: Write the test**

```swift
extension VoicePilotTests {
    func testUnavailableServiceStillYieldsKeywordResolution() async {
        let pilot = DronePilot(service: UnavailableCactusService(reason: "test"))
        let action = await pilot.resolve("stop")
        XCTAssertEqual(action?.function, .stop)   // voice never breaks
    }
}
```

- [ ] **Step 2: Run it**

Run in Xcode: `VoicePilotTests`.
Expected: PASS — proves that with the Cactus model absent, voice still works via keyword fallback (the core "voice never breaks" guarantee).

- [ ] **Step 3: Commit**

```bash
git add mobile/Tests/VoicePilotTests.swift
git commit -m "test(mobile): voice degrades to keyword resolution when Cactus is unavailable"
```

---

## Self-Review

- **Spec coverage (#6):** LLM-first resolution → Task 3 (`finalize` uses `pilot.resolve`). Keyword fallback / voice-never-breaks → Tasks 2 + 5. New approach intent → Task 1 (function + command + phrase) and Task 4 (UI route). Existing voice preserved → Task 3 keeps STT/on-device gating untouched; `IntentParserTests` regression run in Task 3.
- **Type consistency:** `DronePilot(service:).resolve`, `CactusService.isAvailable/complete`, `DroneFunction.approach`, `Command.approach`, `DroneAction.function/magnitude`, `VoiceController(pilot:)`, `finalizeForTesting` used consistently.
- **Flagged:** `ContentView.swift` is mid-edit — re-read before Task 4. Native Xcode build/test only; no CLI build available here.
