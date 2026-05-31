# Tello Target Lock Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the Tello track *you* (visual lock) or an *AprilTag* (other targets), be flown manually by voice/buttons, and re-lock on command — every lock confirmed before it follows.

**Architecture:** Phone-side extension of `FollowCoordinator` (the on-device 15 Hz follow loop). Introduce a `TargetMode {visualMe, tag}` orthogonal to the existing `Phase`, and a single `requestLock(mode)` entry that always routes a new lock through the `confirming` gate. Manual override (`pauseToManual`) already exists; re-lock = `requestLock(currentMode)`. A `target_type` field is added to the `FollowState` wire so the dashboard shows what's followed. All decisions stay on the phone (the Tello controller); the laptop/dashboard are read-only observers.

**Tech Stack:** Swift / SwiftUI + Vision (iOS, `mobile/`), Python / FastAPI / pydantic (`backend/`), TypeScript / Next.js / vitest (`frontend/`), shared TS contract (`shared/`).

**Spec:** `docs/superpowers/specs/2026-05-31-tello-target-lock-design.md`

**Test commands (per stack):**
- Swift: `cd mobile && xcodebuild test -scheme ReconCompanion -destination 'platform=iOS Simulator,name=iPhone 16' -only-testing:ReconCompanionTests/<TestClass>` (run the whole suite by dropping `-only-testing`). The user builds/tests natively through Xcode — never Expo/EAS.
- Backend: `cd backend && .venv/bin/python -m pytest <path> -q`
- Frontend: `cd frontend && npm test -- <path>` (vitest)

**Conventions:** No force-unwraps in new Swift; `async/await` over completion handlers; value types where possible (`.claude/rules/swift.md`). Conventional commits (`.claude/rules/git.md`). One logical assertion per test (`.claude/rules/testing.md`). Do **not** push — commits stay local unless the operator says otherwise.

---

## File Structure

**Phase 1 — Wire contract** (foundation; all later phases depend on `target_type` existing)
- Modify `backend/app/contracts.py` — add `target_type`, `target_label` to `FollowState`.
- Modify `shared/contracts.ts` — same two fields on the `FollowState` interface.
- Modify `mobile/Sources/Contracts.swift` — same two fields on `FollowStateMessage`.
- Test `backend/tests/test_contracts.py` — round-trip + stale-preserves-target_type.

**Phase 2 — Testability seams** (additive; behavior unchanged, proven by existing tests)
- Modify `mobile/Sources/FollowController.swift` — add `DroneCommandSink` protocol.
- Modify `mobile/Sources/TelloCommander.swift` — conform to `DroneCommandSink`.
- Modify `mobile/Sources/FollowCoordinator.swift` — inject `commands` + `now`; add synchronous `currentPhase` mirror + test detection hook.
- Test `mobile/Tests/FollowCoordinatorTests.swift` (new) — seams work; hover-when-disarmed baseline.

**Phase 3 — TargetMode + requestLock + re-lock** (core behavior)
- Modify `mobile/Sources/FollowCoordinator.swift` — `TargetMode`, unified `arm(stream:mode:)`, `requestLock(_:)`, context-aware confirm timeout, `resumeFollow → requestLock`.
- Test `mobile/Tests/FollowCoordinatorTests.swift` — the full state-machine matrix.

**Phase 4 — Voice / intent vocabulary**
- Modify `mobile/Sources/DroneFunction.swift` — add `trackTag`, `confirm` cases + keyword matching.
- Modify `mobile/Sources/ContentView.swift` — route `followMe`/`track`/`trackTag`/`confirm`.
- Test `mobile/Tests/DroneIntentTests.swift` (new) — vocabulary mapping.

**Phase 5 — UI controls + target publish**
- Modify `mobile/Sources/ControlBar.swift` — `ME/TAG` toggle + `RE-LOCK` button (new callbacks).
- Modify `mobile/Sources/ContentView.swift` — wire the new ControlBar callbacks; pass `target_type` to `sendFollowState`.
- Modify `mobile/Sources/WorldClient.swift` — `sendFollowState` carries `targetType`/`targetLabel`.
- Modify `mobile/Sources/FollowCoordinator.swift` — expose `targetType`/`targetLabel` computed values.

**Phase 6 — Dashboard badge**
- Create `frontend/src/lib/followTarget.ts` — pure `followTargetLabel(state)`.
- Create `frontend/src/lib/followTarget.test.ts` — vitest.
- Modify `frontend/src/lib/contracts.ts` (or wherever `FollowState` is imported) — add the two fields.
- Modify `frontend/src/components/FollowInset.tsx` — render the target badge.

**Phase 7 — Docs**
- Modify `CLAUDE.md` — Tello role + command flow reflect visual-me / tag-designation.

---

## Phase 1 — Wire contract

### Task 1.1: Add `target_type`/`target_label` to the backend `FollowState`

**Files:**
- Modify: `backend/app/contracts.py` (the `FollowState` model, ~lines 138-161)
- Test: `backend/tests/test_contracts.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_contracts.py`:

```python
def test_follow_state_accepts_target_type_and_label():
    msg = parse_client_message({
        "type": "follow_state", "active": True, "phase": "following",
        "distance_m": 2.5, "bearing_deg": 10.0, "t": 1.0,
        "target_type": "visual_me", "target_label": None,
    })
    assert isinstance(msg, FollowState)
    assert msg.target_type == "visual_me"
    assert msg.target_label is None


def test_follow_state_target_type_defaults_to_none():
    msg = parse_client_message({
        "type": "follow_state", "active": False, "phase": "disarmed", "t": 1.0,
    })
    assert msg.target_type is None


def test_follow_state_rejects_bad_target_type():
    import pytest
    from pydantic import ValidationError
    with pytest.raises((ValidationError, ValueError)):
        FollowState(t=1.0, target_type="rocket")
```

Ensure `FollowState` is imported at the top of the test file (it likely already imports from `app.contracts`; add `FollowState` to that import if missing).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_contracts.py -q -k target_type`
Expected: FAIL (`target_type` not a field / no validation error raised).

- [ ] **Step 3: Add the fields**

In `backend/app/contracts.py`, inside `class FollowState`, add after the `source` field (before `t`):

```python
    # What the lock is on. visual_me = ObjectTracker lock on the soldier;
    # tag = an AprilTag designating another target. None when not following.
    target_type: Literal["visual_me", "tag"] | None = None
    # Raw identifier hint only (e.g. the tag id "7"); None for visual_me. The
    # human display string is composed on the dashboard, not sent here.
    target_label: str | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_contracts.py -q -k target_type`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/contracts.py backend/tests/test_contracts.py
git commit -m "feat(contracts): add target_type/target_label to FollowState"
```

### Task 1.2: Preserve `target_type` through the server stale-downgrade

**Files:**
- Modify: `backend/app/server.py` (stale-downgrade `model_copy`, ~line 483)
- Test: `backend/tests/test_contracts.py`

- [ ] **Step 1: Write the failing test**

The stale path does `fs.model_copy(update={"active": False, "phase": "stale", "t": now})`. `model_copy` already preserves unlisted fields, so `target_type` survives — pin it so a future refactor can't drop it:

Append to `backend/tests/test_contracts.py`:

```python
def test_follow_state_stale_copy_preserves_target_type():
    fs = FollowState(active=True, phase="following", distance_m=2.0, bearing_deg=5.0,
                     t=1.0, target_type="tag", target_label="7")
    stale = fs.model_copy(update={"active": False, "phase": "stale", "t": 9.0})
    assert stale.phase == "stale"
    assert stale.target_type == "tag"      # preserved, not dropped
    assert stale.target_label == "7"
```

- [ ] **Step 2: Run test to verify it passes immediately**

Run: `cd backend && .venv/bin/python -m pytest tests/test_contracts.py -q -k stale_copy`
Expected: PASS (this is a regression guard; `model_copy` already preserves the field). If it FAILS, the `FollowState` from Task 1.1 is missing the field — fix that first.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_contracts.py
git commit -m "test(contracts): pin target_type survives the stale downgrade"
```

### Task 1.3: Mirror the fields in the shared TS + mobile Swift contracts

**Files:**
- Modify: `shared/contracts.ts` (the `FollowState` interface, ~lines 83-90)
- Modify: `mobile/Sources/Contracts.swift` (the `FollowStateMessage` struct, ~lines 119-127)

- [ ] **Step 1: Update `shared/contracts.ts`**

In the `FollowState` interface, add after `bearing_deg`:

```typescript
  target_type?: "visual_me" | "tag" | null; // what the lock is on; null when not following
  target_label?: string | null;             // raw id hint (e.g. tag id); null for visual_me
```

- [ ] **Step 2: Update `mobile/Sources/Contracts.swift`**

Replace the `FollowStateMessage` struct with:

```swift
struct FollowStateMessage: Encodable, Sendable {
    let type = "follow_state"
    let active: Bool
    let phase: String
    let distance_m: Double
    let bearing_deg: Double
    let source: String
    let t: Double
    let target_type: String?   // "visual_me" | "tag" | nil (not following)
    let target_label: String?  // raw id hint (e.g. tag id); nil for visual_me
}
```

- [ ] **Step 3: Verify TS compiles**

Run: `cd frontend && npx tsc --noEmit` (if `shared/` is included in the frontend tsconfig) — Expected: no new errors. If `shared/` isn't type-checked by the frontend, skip; the field is additive.

- [ ] **Step 4: Commit**

```bash
git add shared/contracts.ts mobile/Sources/Contracts.swift
git commit -m "feat(contracts): mirror target_type/target_label in TS + Swift FollowState"
```

---

## Phase 2 — Testability seams (behavior unchanged)

These are additive refactors so the state machine is unit-testable without a real Tello, video, or wall clock. Existing behavior must not change.

### Task 2.1: `DroneCommandSink` protocol + `TelloCommander` conformance

**Files:**
- Modify: `mobile/Sources/FollowController.swift` (add the protocol near `RCCommand`)
- Modify: `mobile/Sources/TelloCommander.swift` (conformance)

- [ ] **Step 1: Add the protocol**

In `mobile/Sources/FollowController.swift`, add above `struct RCCommand`:

```swift
/// The minimal drone command surface the follow loop needs. `TelloCommander`
/// is the production implementation; tests inject a recording double so the
/// state machine can be exercised with no UDP socket / real drone.
protocol DroneCommandSink: AnyObject {
    func send(_ command: String)
    func rc(_ command: RCCommand)
}
```

- [ ] **Step 2: Conform `TelloCommander`**

In `mobile/Sources/TelloCommander.swift`, add at the end of the file:

```swift
extension TelloCommander: DroneCommandSink {}
```

(`TelloCommander` already has `func send(_ command: String)` and `func rc(_ command: RCCommand)` — verify the signatures match exactly; if `send`/`rc` differ, adjust the protocol to match the real signatures rather than changing `TelloCommander`.)

- [ ] **Step 3: Verify it builds**

Run: `cd mobile && xcodebuild build -scheme ReconCompanion -destination 'platform=iOS Simulator,name=iPhone 16'`
Expected: BUILD SUCCEEDED.

- [ ] **Step 4: Commit**

```bash
git add mobile/Sources/FollowController.swift mobile/Sources/TelloCommander.swift
git commit -m "refactor(follow): add DroneCommandSink seam for testable follow loop"
```

### Task 2.2: Inject `commands` + `now`, add synchronous phase mirror and a test detection hook

**Files:**
- Modify: `mobile/Sources/FollowCoordinator.swift`

- [ ] **Step 1: Add injected dependencies + init**

In `FollowCoordinator`, replace the bare `controller`/queue property region with injected deps. Add near the top of the class body (after `@Published` properties):

```swift
    // Injected for testability; production defaults wire the real singletons/clock.
    private let commands: DroneCommandSink
    private let now: () -> CFTimeInterval

    /// Synchronous mirror of `phase` (the @Published one updates on the main queue
    /// asynchronously). Tests read this immediately after driving the loop.
    private(set) var currentPhase: Phase = .disarmed

    init(commands: DroneCommandSink = TelloCommander.shared,
         now: @escaping () -> CFTimeInterval = { CACurrentMediaTime() }) {
        self.commands = commands
        self.now = now
    }
```

- [ ] **Step 2: Route all drone I/O through `commands`, all time through `now()`**

In `FollowCoordinator.swift`, replace every `TelloCommander.shared.send(...)` → `commands.send(...)`, every `TelloCommander.shared.rc(...)` → `commands.rc(...)`, and every `CACurrentMediaTime()` → `now()`. (Occurrences are in `arm`, `armTrack`, `pauseToManual`, `disarmAndLand`, `emergencyCut`, `ingest`, `trackStep`/`tick`, `confirmTarget`.) Then update `setPhase` to keep the mirror in sync:

```swift
    private func setPhase(_ p: Phase) {
        currentPhase = p
        DispatchQueue.main.async { if self.phase != p { self.phase = p } }
    }
```

- [ ] **Step 3: Add internal test seams**

Add these `internal` members (accessible via `@testable import`, invisible to the app) at the end of the class:

```swift
    // MARK: test seams (internal — used by FollowCoordinatorTests via @testable)

    /// Drive one rc-loop tick synchronously (the production timer calls `tick()`).
    func tickForTest() { tick() }

    /// Inject a detection as if the detector produced it, `age` seconds ago.
    func injectDetectionForTest(_ d: TagDetection?, age: CFTimeInterval = 0) {
        latest = d
        latestTime = now() - age
    }

    /// Place the coordinator directly into an airborne, confirmed, following-ready
    /// state without takeoff — the precondition for re-lock / manual tests.
    func enterAirborneForTest(mode: TargetMode) {
        self.mode = mode
        armed = true; followActive = true; tookOff = true; confirmed = true
        landing = false; manualHover = false; scripted = false
        setPhase(.following)
    }
```

(`TargetMode` is introduced in Phase 3; until then, temporarily type `mode:` as the existing `Mode`. Phase 3 Task 3.1 renames it — the test file written in Task 2.3 uses only `enterAirborneForTest`/`tickForTest`/`injectDetectionForTest`, not the mode name, so it survives the rename.)

- [ ] **Step 4: Verify build + existing tests unaffected**

Run: `cd mobile && xcodebuild build -scheme ReconCompanion -destination 'platform=iOS Simulator,name=iPhone 16'`
Expected: BUILD SUCCEEDED. Existing `FollowControllerTests` still compile (they don't touch `FollowCoordinator`).

- [ ] **Step 5: Commit**

```bash
git add mobile/Sources/FollowCoordinator.swift
git commit -m "refactor(follow): inject command sink + clock, add sync phase mirror + test seams"
```

### Task 2.3: Recording double + baseline coordinator test

**Files:**
- Create: `mobile/Tests/FollowCoordinatorTests.swift`

- [ ] **Step 1: Write the test (recording sink + disarmed baseline)**

```swift
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
        coord = FollowCoordinator(commands: sink, now: { [unowned self] in self.clock })
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
}
```

- [ ] **Step 2: Run to verify it passes**

Run: `cd mobile && xcodebuild test -scheme ReconCompanion -destination 'platform=iOS Simulator,name=iPhone 16' -only-testing:ReconCompanionTests/FollowCoordinatorTests`
Expected: PASS (`tick()` returns early when not `armed`).

- [ ] **Step 3: Commit**

```bash
git add mobile/Tests/FollowCoordinatorTests.swift
git commit -m "test(follow): recording command sink + disarmed baseline"
```

---

## Phase 3 — TargetMode + requestLock + re-lock

### Task 3.1: Rename `Mode` → `TargetMode {visualMe, tag}`, default visual-me

**Files:**
- Modify: `mobile/Sources/FollowCoordinator.swift`

- [ ] **Step 1: Rename the enum and default**

Replace:
```swift
    enum Mode { case tag, track }
    private var mode: Mode = .tag
```
with:
```swift
    /// What kind of target the lock is on. visualMe = ObjectTracker lock on the
    /// soldier (the default "me"); tag = an AprilTag designating another target.
    enum TargetMode { case visualMe, tag }
    private(set) var mode: TargetMode = .visualMe
```

- [ ] **Step 2: Update every `mode` use**

Replace `mode == .track` → `mode == .visualMe` (in `arm`, `armTrack`, `ingest`, the takeoff-settle re-lock blocks). Replace `mode = .tag` (in `disarmAndLand`, `emergencyCut`) → `mode = .visualMe` (reset to the default "me" target on land). In `ingest`, the branch `if self.mode == .track { trackStep } else { detect }` becomes `if self.mode == .visualMe { trackStep } else { detect }`.

- [ ] **Step 3: Verify build**

Run: `cd mobile && xcodebuild build -scheme ReconCompanion -destination 'platform=iOS Simulator,name=iPhone 16'`
Expected: BUILD SUCCEEDED.

- [ ] **Step 4: Commit**

```bash
git add mobile/Sources/FollowCoordinator.swift
git commit -m "refactor(follow): TargetMode {visualMe, tag}, default visual-me"
```

### Task 3.2: Unify `arm`/`armTrack` into `arm(stream:mode:)`

**Files:**
- Modify: `mobile/Sources/FollowCoordinator.swift`
- Modify: `mobile/Sources/ContentView.swift` (the `pendingArm` consumer call sites)

- [ ] **Step 1: Replace `arm(stream:)` + `armTrack(stream:)` with one method**

Replace both methods with:

```swift
    /// Take off and begin acquiring a lock of the given kind. Caller confirms intent
    /// (this launches a real drone). The lock still goes through the confirm gate
    /// before any follow rc is sent.
    func arm(stream: TelloDirectStream, mode: TargetMode = .visualMe) {
        guard phase == .disarmed else { return }
        self.stream = stream
        self.mode = mode
        stream.start()
        controller.config = config
        if mode == .tag {
            let size = tagSizeMeters
            detectQueue.async { self.detector.tagSizeMeters = size }
        } else {
            detectQueue.async { self.tracker.reset() }
        }
        stream.onPixelBuffer = { [weak self] pb in self?.ingest(pb) }

        commands.send("takeoff")
        confirmTimeoutLands = true   // initial arm: a never-confirmed takeoff lands
        rcQueue.async {
            self.armed = true
            self.followActive = true
            self.tookOff = false
            self.confirmed = false
            self.landing = false
            self.latest = nil
            self.latestTime = self.now()
            self.rcQueue.asyncAfter(deadline: .now() + self.takeoffSettle) {
                self.tookOff = true
                self.tookOffAt = self.now()
                self.latest = nil
                self.latestTime = self.now()
                if self.mode == .visualMe { self.detectQueue.async { self.tracker.reset() } }
            }
        }
        setPhase(.searching)
        startRCLoop()
    }
```

(Add the `private var confirmTimeoutLands = true` property near the other control-state vars — it is set by Task 3.4.)

- [ ] **Step 2: Update the `pendingArm` call sites in `ContentView.swift`**

Find where `pendingArm` is consumed (grep: `cd mobile && grep -rn "pendingArm" Sources/`). It currently calls `follow.arm(stream:)` for `.follow` and `follow.armTrack(stream:)` for `.track`. Update the `pendingArm` enum to `{ case visualMe, tag }` and its consumer to:

```swift
// in the confirmation handler that consumes pendingArm:
switch pendingArm {
case .visualMe: follow.arm(stream: stream, mode: .visualMe)
case .tag:      follow.arm(stream: stream, mode: .tag)
}
```

Update the producers in `handle()` accordingly (done in Task 4.2): `pendingArm = .visualMe` for follow-me, `pendingArm = .tag` for track-tag.

- [ ] **Step 3: Verify build**

Run: `cd mobile && xcodebuild build -scheme ReconCompanion -destination 'platform=iOS Simulator,name=iPhone 16'`
Expected: BUILD SUCCEEDED (all `armTrack(` references resolved/removed).

- [ ] **Step 4: Commit**

```bash
git add mobile/Sources/FollowCoordinator.swift mobile/Sources/ContentView.swift
git commit -m "refactor(follow): unify arm() into arm(stream:mode:)"
```

### Task 3.3: `requestLock(_:)` — re-lock / switch always through `confirming`

**Files:**
- Modify: `mobile/Sources/FollowCoordinator.swift`
- Test: `mobile/Tests/FollowCoordinatorTests.swift`

- [ ] **Step 1: Write the failing tests**

Add to `FollowCoordinatorTests`:

```swift
    func testRequestLockFromAirborneEntersSearchingNotFollowing() {
        coord.enterAirborneForTest(mode: .visualMe)
        coord.requestLock(.visualMe)
        XCTAssertEqual(coord.currentPhase, .searching)   // not .following — must re-confirm
    }

    func testRequestLockClearsConfirmationSoTickHovers() {
        coord.enterAirborneForTest(mode: .visualMe)
        coord.requestLock(.tag)                 // switch target type
        coord.injectDetectionForTest(tag(), age: 0)   // a fresh candidate exists
        coord.tickForTest()
        XCTAssertEqual(sink.lastRC, .hover)     // confirm gate holds — no follow rc yet
    }

    func testRequestLockThenConfirmThenTickFollows() {
        coord.enterAirborneForTest(mode: .visualMe)
        coord.requestLock(.visualMe)
        coord.injectDetectionForTest(tag(bearingDeg: 20), age: 0)
        coord.confirmTarget()
        coord.tickForTest()
        XCTAssertGreaterThan(sink.lastRC?.yaw ?? 0, 0)  // now it follows (yaws toward the tag)
    }
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd mobile && xcodebuild test -scheme ReconCompanion -destination 'platform=iOS Simulator,name=iPhone 16' -only-testing:ReconCompanionTests/FollowCoordinatorTests`
Expected: FAIL — `requestLock` does not exist (compile error).

- [ ] **Step 3: Implement `requestLock`**

Add to `FollowCoordinator`:

```swift
    /// Acquire (or switch to, or re-acquire) a lock of the given kind WITHOUT taking
    /// off — the drone is already airborne. Always routes through the confirm gate:
    /// re-inits the detector, drops any prior reading, and hovers in `searching`
    /// until `confirmTarget()`. This is the single entry for mid-flight switch and
    /// for "lock back onto me" after a manual takeover.
    func requestLock(_ mode: TargetMode) {
        guard isArmed else { return }
        self.mode = mode
        if mode == .visualMe { detectQueue.async { self.tracker.reset() } }
        confirmTimeoutLands = false   // mid-flight: a never-confirmed re-lock falls back to manual, not land
        rcQueue.async {
            self.followActive = true
            self.manualHover = false
            self.scripted = false
            self.landing = false
            self.tookOff = true        // already airborne — no settle delay
            self.confirmed = false     // MUST re-confirm (confirm-always)
            self.latest = nil
            self.latestTime = self.now()
        }
        setPhase(.searching)
        startRCLoop()
    }
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd mobile && xcodebuild test -scheme ReconCompanion -destination 'platform=iOS Simulator,name=iPhone 16' -only-testing:ReconCompanionTests/FollowCoordinatorTests`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add mobile/Sources/FollowCoordinator.swift mobile/Tests/FollowCoordinatorTests.swift
git commit -m "feat(follow): requestLock() routes every re-lock/switch through confirm gate"
```

### Task 3.4: Context-aware confirm timeout (arm → land, mid-flight → manual)

**Files:**
- Modify: `mobile/Sources/FollowCoordinator.swift`
- Test: `mobile/Tests/FollowCoordinatorTests.swift`

- [ ] **Step 1: Write the failing tests**

```swift
    func testConfirmTimeoutOnInitialArmLands() {
        // Simulate the post-takeoff hover with confirmTimeoutLands = true.
        coord.enterAirborneForTest(mode: .visualMe)
        coord.setConfirmTimeoutLandsForTest(true)
        coord.setUnconfirmedHoverForTest(tookOffAtAge: 31)  // > confirmTimeout (30s)
        coord.tickForTest()
        XCTAssertTrue(sink.sent.contains("land"))
    }

    func testConfirmTimeoutMidFlightFallsBackToManualNotLand() {
        coord.enterAirborneForTest(mode: .visualMe)
        coord.setConfirmTimeoutLandsForTest(false)          // a mid-flight re-lock
        coord.setUnconfirmedHoverForTest(tookOffAtAge: 31)
        coord.tickForTest()
        XCTAssertFalse(sink.sent.contains("land"))
        XCTAssertEqual(coord.currentPhase, .manual)
    }
```

Add the two test seams these need to `FollowCoordinator` (internal):

```swift
    func setConfirmTimeoutLandsForTest(_ v: Bool) { confirmTimeoutLands = v }
    func setUnconfirmedHoverForTest(tookOffAtAge: CFTimeInterval) {
        confirmed = false; tookOff = true; manualHover = false
        tookOffAt = now() - tookOffAtAge
    }
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd mobile && xcodebuild test -scheme ReconCompanion -destination 'platform=iOS Simulator,name=iPhone 16' -only-testing:ReconCompanionTests/FollowCoordinatorTests`
Expected: FAIL — `setConfirmTimeoutLandsForTest` missing, and the timeout always lands.

- [ ] **Step 3: Implement the property + branch the timeout**

Add the property near the other control-state vars:

```swift
    private var confirmTimeoutLands = true   // true on initial arm; false on mid-flight re-lock
```

In `tick()`, replace the confirm-timeout block:

```swift
        if !confirmed {
            commands.rc(.hover)
            if now() - tookOffAt > confirmTimeout {
                if confirmTimeoutLands {
                    // Initial arm never confirmed — land for safety.
                    landing = true
                    rcTimer?.cancel(); rcTimer = nil
                    DispatchQueue.main.async { self.disarmAndLand() }
                } else {
                    // Mid-flight re-lock/switch never confirmed — fall back to manual
                    // hover; the operator is already flying, don't drop the aircraft.
                    followActive = false; manualHover = true; confirmed = false
                    setPhase(.manual)
                }
            } else {
                setPhase(fresh ? .confirming : .searching)
            }
            return
        }
```

(Confirm `fresh` is computed above this block, as in the current `tick()`. `commands.rc` replaces `TelloCommander.shared.rc` per Phase 2.)

- [ ] **Step 4: Run to verify they pass**

Run: `cd mobile && xcodebuild test -scheme ReconCompanion -destination 'platform=iOS Simulator,name=iPhone 16' -only-testing:ReconCompanionTests/FollowCoordinatorTests`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add mobile/Sources/FollowCoordinator.swift mobile/Tests/FollowCoordinatorTests.swift
git commit -m "feat(follow): context-aware confirm timeout — land on arm, manual mid-flight"
```

### Task 3.5: `resumeFollow()` routes through `requestLock` (no auto-confirm)

**Files:**
- Modify: `mobile/Sources/FollowCoordinator.swift`
- Test: `mobile/Tests/FollowCoordinatorTests.swift`

- [ ] **Step 1: Write the failing test**

```swift
    func testResumeFollowGoesThroughConfirmNotAutoConfirm() {
        coord.enterAirborneForTest(mode: .visualMe)
        coord.pauseToManual()
        coord.resumeFollow()
        XCTAssertEqual(coord.currentPhase, .searching)  // re-acquire + re-confirm, not straight to following
        coord.injectDetectionForTest(tag(), age: 0)
        coord.tickForTest()
        XCTAssertEqual(sink.lastRC, .hover)             // still gated until confirmTarget()
    }
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd mobile && xcodebuild test -scheme ReconCompanion -destination 'platform=iOS Simulator,name=iPhone 16' -only-testing:ReconCompanionTests/FollowCoordinatorTests/testResumeFollowGoesThroughConfirmNotAutoConfirm`
Expected: FAIL — current `resumeFollow()` sets `confirmed = true`, so the tick would follow (or phase would not be the gated one).

- [ ] **Step 3: Reimplement `resumeFollow`**

Replace the body of `resumeFollow()` with a delegation to `requestLock` (preserves the current target mode; scout/scripted resume now also re-confirms — consistent with confirm-always):

```swift
    /// Resume autonomous following after a manual takeover or scripted maneuver.
    /// Re-acquires the CURRENT target mode through the confirm gate (confirm-always).
    func resumeFollow() {
        guard isArmed else { return }
        requestLock(mode)
    }
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd mobile && xcodebuild test -scheme ReconCompanion -destination 'platform=iOS Simulator,name=iPhone 16' -only-testing:ReconCompanionTests/FollowCoordinatorTests`
Expected: PASS (whole class).

- [ ] **Step 5: Commit**

```bash
git add mobile/Sources/FollowCoordinator.swift mobile/Tests/FollowCoordinatorTests.swift
git commit -m "fix(follow): resumeFollow re-confirms instead of auto-confirming"
```

---

## Phase 4 — Voice / intent vocabulary

### Task 4.1: Add `trackTag` + `confirm` DroneFunctions and keyword matching

**Files:**
- Modify: `mobile/Sources/DroneFunction.swift`
- Test: `mobile/Tests/DroneIntentTests.swift` (new)

- [ ] **Step 1: Write the failing tests**

Create `mobile/Tests/DroneIntentTests.swift`:

```swift
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
}
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd mobile && xcodebuild test -scheme ReconCompanion -destination 'platform=iOS Simulator,name=iPhone 16' -only-testing:ReconCompanionTests/DroneIntentTests`
Expected: FAIL — `.trackTag` / `.confirm` don't exist.

- [ ] **Step 3: Add the enum cases + purposes**

In `DroneFunction.swift`, add the two cases to the `enum DroneFunction` (after `track`):

```swift
    case trackTag = "track_tag"   // lock an AprilTag designating another target
    case confirm                   // approve the currently-locked target
```

Add to `purpose`:

```swift
        case .trackTag: return "lock onto the AprilTag to designate another target"
        case .confirm: return "approve the currently shown target lock"
```

(`isFlight` is `true` for both — they have no `missionCommand` — which is correct: like `track`/`followMe` they're phone-local follow controls handled by explicit early returns in `ContentView.handle()`, never the flight-execute branch. No change to `telloCommand` needed; its `switch` falls through to `default: return nil`.)

- [ ] **Step 4: Add keyword matching (order matters — tag/confirm before generic track/follow)**

In `DroneIntent.match`, insert these BEFORE the existing `track that / lock on / follow that` line and the `follow` line:

```swift
        // Designate an AprilTag target — checked before the generic track/follow
        // phrases (which include "track the" / "follow that") so the tag wins.
        if has(t, ["track the tag", "follow the tag", "track that tag", "the apriltag",
                   "track the apriltag", "designate", "mark that", "lock the tag"]) { return DroneAction(.trackTag) }
        // Approve the shown lock. Bare "go" is intentionally NOT used — it collides
        // with "go up" / "go down" / "go back".
        if has(t, ["confirm", "confirmed", "lock it in", "approve target", "yes follow"]) { return DroneAction(.confirm) }
```

Then add `"track me"` to the existing visual-track needle list (the `track that / track the / lock on …` line) so "track me" maps to `.track` (visual-me).

- [ ] **Step 5: Run to verify they pass**

Run: `cd mobile && xcodebuild test -scheme ReconCompanion -destination 'platform=iOS Simulator,name=iPhone 16' -only-testing:ReconCompanionTests/DroneIntentTests`
Expected: PASS. (The Gemma prompt in `DronePilot.systemPrompt` auto-includes the new functions because it iterates `DroneFunction.allCases` — no change needed there.)

- [ ] **Step 6: Commit**

```bash
git add mobile/Sources/DroneFunction.swift mobile/Tests/DroneIntentTests.swift
git commit -m "feat(voice): add trackTag + confirm commands to the drone vocabulary"
```

### Task 4.2: Route the new vocabulary in `ContentView.handle()`

**Files:**
- Modify: `mobile/Sources/ContentView.swift` (the `handle(_:)` method)

- [ ] **Step 1: Update the routing**

In `handle(_ action: DroneAction)`, change the `followMe`/`track` blocks and add `trackTag`/`confirm` blocks (place all of these before the `if fn.isFlight` branch):

```swift
        if fn == .followMe || fn == .track {   // both mean "lock onto me" (visual)
            if follow.phase == .disarmed { pendingArm = .visualMe } else { follow.requestLock(.visualMe) }
            return
        }

        if fn == .trackTag {                    // designate another target via AprilTag
            if follow.phase == .disarmed { pendingArm = .tag } else { follow.requestLock(.tag) }
            return
        }

        if fn == .confirm {                     // approve the shown lock
            if follow.isArmed { follow.confirmTarget() }
            return
        }
```

Remove the old separate `if fn == .track { … relock() }` block (its behavior is now folded into the combined `followMe || track` line; `relock()` is superseded by `requestLock(.visualMe)`).

- [ ] **Step 2: Verify build**

Run: `cd mobile && xcodebuild build -scheme ReconCompanion -destination 'platform=iOS Simulator,name=iPhone 16'`
Expected: BUILD SUCCEEDED. (`pendingArm` now has `.visualMe`/`.tag` cases from Task 3.2.)

- [ ] **Step 3: Commit**

```bash
git add mobile/Sources/ContentView.swift
git commit -m "feat(voice): route followMe/track→visualMe, trackTag→tag, confirm→confirmTarget"
```

---

## Phase 5 — UI controls + target publish

### Task 5.1: `ME/TAG` toggle + `RE-LOCK` button in `ControlBar`

**Files:**
- Modify: `mobile/Sources/ControlBar.swift`
- Modify: `mobile/Sources/ContentView.swift` (pass the new callbacks)

- [ ] **Step 1: Add callbacks + buttons to `ControlBar`**

`ControlBar` currently only sends mission `Command`s. Add follow-target callbacks (optional, so call sites that don't need them stay valid):

```swift
struct ControlBar: View {
    let onCommand: (Command) -> Void
    let enabled: Bool
    /// Follow-target controls (phone-local; not mission commands). nil-safe: when
    /// not provided, the target row is hidden.
    var onLockMe: (() -> Void)? = nil
    var onLockTag: (() -> Void)? = nil
    var onRelock: (() -> Void)? = nil

    var body: some View {
        VStack(spacing: 10) {
            if onLockMe != nil || onLockTag != nil || onRelock != nil {
                HStack(spacing: 10) {
                    targetButton("TRACK ME", action: onLockMe)
                    targetButton("TRACK TAG", action: onLockTag)
                    targetButton("RE-LOCK", action: onRelock)
                }
            }
            HStack(spacing: 10) {
                button("FOLLOW", command: .followMe)
                button("HOLD", command: .hold)
                button("RECALL", command: .recall)
            }
            stopButton
        }
        .padding(14)
        .background(Theme.panel)
        .overlay(Rectangle().frame(height: 1).foregroundColor(Theme.hairline), alignment: .top)
    }

    private func targetButton(_ title: String, action: (() -> Void)?) -> some View {
        Button { action?() } label: {
            Text(title).font(Theme.mono(12, weight: .semibold))
                .frame(maxWidth: .infinity, minHeight: 42)
                .foregroundColor(action != nil ? Theme.ink : Theme.faint)
                .overlay(Rectangle().stroke(action != nil ? Theme.ink : Theme.faint, lineWidth: 1.2))
        }
        .disabled(action == nil)
    }

    // ... existing button(_:command:) and stopButton unchanged ...
}
```

- [ ] **Step 2: Wire the callbacks where `ControlBar` is constructed in `ContentView`**

The current call site is `ControlBar(onCommand: { client.send($0) }, enabled: isConnected)`. Update it to drive the coordinator (re-lock only valid while airborne):

```swift
ControlBar(
    onCommand: { client.send($0) },
    enabled: isConnected,
    onLockMe: { follow.isArmed ? follow.requestLock(.visualMe) : (pendingArm = .visualMe) },
    onLockTag: { follow.isArmed ? follow.requestLock(.tag) : (pendingArm = .tag) },
    onRelock: { if follow.isArmed { follow.requestLock(follow.mode) } }
)
```

(If the ternary-with-assignment doesn't compile cleanly, expand into `if/else` closures.)

- [ ] **Step 3: Verify build**

Run: `cd mobile && xcodebuild build -scheme ReconCompanion -destination 'platform=iOS Simulator,name=iPhone 16'`
Expected: BUILD SUCCEEDED.

- [ ] **Step 4: Commit**

```bash
git add mobile/Sources/ControlBar.swift mobile/Sources/ContentView.swift
git commit -m "feat(ui): ME/TAG target toggle + RE-LOCK button in ControlBar"
```

> The `CONFIRM` button already exists in `TelloVideoView.confirmBar` (shown when `phase == .confirming`) and calls `follow.confirmTarget()` — it now gates re-locks/switches too, no change needed.

### Task 5.2: Expose `targetType`/`targetLabel`; publish on the wire

**Files:**
- Modify: `mobile/Sources/FollowCoordinator.swift`
- Modify: `mobile/Sources/WorldClient.swift`
- Modify: `mobile/Sources/ContentView.swift` (the `sendFollowState` call site)

- [ ] **Step 1: Add computed target fields to `FollowCoordinator`**

```swift
    /// Wire target_type: only meaningful while actually following a target.
    var targetType: String? {
        guard phase == .following || phase == .confirming else { return nil }
        return mode == .visualMe ? "visual_me" : "tag"
    }
    /// Raw id hint for the dashboard (tag id); nil for visual_me. The visual tracker
    /// carries no id, and the tag id is not currently surfaced, so this is nil for
    /// now (reserved for when a specific tag id is selected). See spec non-goals.
    var targetLabel: String? { nil }
```

- [ ] **Step 2: Extend `sendFollowState`**

In `WorldClient.swift`, add the two parameters and pass them into `FollowStateMessage` (which gained the fields in Task 1.3):

```swift
    func sendFollowState(active: Bool, phase: String, distanceM: Double, bearingDeg: Double,
                         targetType: String? = nil, targetLabel: String? = nil) {
        guard let task else { return }
        let msg = FollowStateMessage(active: active, phase: phase, distance_m: distanceM,
                                     bearing_deg: bearingDeg, source: "phone",
                                     t: Date().timeIntervalSince1970,
                                     target_type: targetType, target_label: targetLabel)
        guard let data = try? encoder.encode(msg), let json = String(data: data, encoding: .utf8) else { return }
        task.send(.string(json)) { _ in }
    }
```

- [ ] **Step 3: Pass target fields at the call site**

Find the `sendFollowState(` caller (grep: `cd mobile && grep -rn "sendFollowState(" Sources/`). It currently passes `active/phase/distanceM/bearingDeg`. Add `targetType: follow.targetType, targetLabel: follow.targetLabel`.

- [ ] **Step 4: Verify build**

Run: `cd mobile && xcodebuild build -scheme ReconCompanion -destination 'platform=iOS Simulator,name=iPhone 16'`
Expected: BUILD SUCCEEDED.

- [ ] **Step 5: Commit**

```bash
git add mobile/Sources/FollowCoordinator.swift mobile/Sources/WorldClient.swift mobile/Sources/ContentView.swift
git commit -m "feat(follow): publish target_type on the FollowState wire"
```

---

## Phase 6 — Dashboard badge

### Task 6.1: Pure `followTargetLabel` helper + vitest

**Files:**
- Create: `frontend/src/lib/followTarget.ts`
- Create: `frontend/src/lib/followTarget.test.ts`
- Modify: `frontend/src/lib/contracts.ts` (add the two fields to the imported `FollowState`)

- [ ] **Step 1: Add the fields to the frontend `FollowState` type**

In `frontend/src/lib/contracts.ts` (the type `FollowInset` imports), add to the `FollowState` interface:

```typescript
  target_type?: "visual_me" | "tag" | null;
  target_label?: string | null;
```

- [ ] **Step 2: Write the failing test**

Create `frontend/src/lib/followTarget.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
import { followTargetLabel } from "./followTarget";
import type { FollowState } from "./contracts";

const base: FollowState = {
  type: "follow_state", active: true, phase: "following",
  distance_m: 2, bearing_deg: 0, t: 1,
};

describe("followTargetLabel", () => {
  it("labels a visual-me lock", () => {
    expect(followTargetLabel({ ...base, target_type: "visual_me" })).toBe("ME (visual)");
  });

  it("labels a tag lock with its id", () => {
    expect(followTargetLabel({ ...base, target_type: "tag", target_label: "7" })).toBe("TAG #7");
  });

  it("labels a tag lock with no id", () => {
    expect(followTargetLabel({ ...base, target_type: "tag" })).toBe("TAG");
  });

  it("returns null when there is no target", () => {
    expect(followTargetLabel({ ...base, target_type: null })).toBeNull();
    expect(followTargetLabel(null)).toBeNull();
  });
});
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd frontend && npm test -- src/lib/followTarget.test.ts`
Expected: FAIL — module `./followTarget` not found.

- [ ] **Step 4: Implement the helper**

Create `frontend/src/lib/followTarget.ts`:

```typescript
import type { FollowState } from "./contracts";

/**
 * Human display label for the follow target, composed from target_type +
 * target_label. Kept out of the FollowInset component so it can be unit-tested.
 * Returns null when nothing is being followed.
 */
export function followTargetLabel(state: FollowState | null): string | null {
  if (!state || !state.target_type) return null;
  if (state.target_type === "visual_me") return "ME (visual)";
  return state.target_label ? `TAG #${state.target_label}` : "TAG";
}
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd frontend && npm test -- src/lib/followTarget.test.ts`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/followTarget.ts frontend/src/lib/followTarget.test.ts frontend/src/lib/contracts.ts
git commit -m "feat(dashboard): followTargetLabel helper + FollowState target fields"
```

### Task 6.2: Render the target badge in `FollowInset`

**Files:**
- Modify: `frontend/src/components/FollowInset.tsx`

- [ ] **Step 1: Import the helper + render the badge**

At the top of `FollowInset.tsx`, add:
```typescript
import { followTargetLabel } from "@/lib/followTarget";
```

Inside the component, after `if (!state) return null;`, compute:
```typescript
  const targetLabel = followTargetLabel(state);
```

In the text column (the `<div className="flex flex-col gap-0.5 pr-1">`), add a line under the phase span:
```tsx
        {targetLabel && (
          <span className="text-[10px] uppercase tracking-[0.15em] text-text-muted">
            {targetLabel}
          </span>
        )}
```

- [ ] **Step 2: Verify it builds + lint**

Run: `cd frontend && npx tsc --noEmit && npm run lint`
Expected: no new errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/FollowInset.tsx
git commit -m "feat(dashboard): show follow target badge (ME / TAG) in FollowInset"
```

---

## Phase 7 — Docs

### Task 7.1: Update `CLAUDE.md` for the visual-me / tag-designation model

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update the Tello role + command flow**

In `CLAUDE.md`, under the **Tello (soldier companion)** role and the **Command flow** / **Phone (mobile client)** sections, replace the "follows the soldier using an AprilTag worn by the soldier" framing with the implemented model:

> The Tello tracks the soldier by **on-device visual lock** (`ObjectTracker`, the default "me" target); an **AprilTag** is used to designate *other* targets (a vehicle, a spot, another person). The operator switches target by voice ("follow me" / "track the tag") or the dashboard's `ME`/`TAG` toggle, can take manual control by voice/buttons at any time (`pauseToManual`), and re-locks on command — **every lock is approved through the `confirming` gate before the drone follows**. Visual tracking has no identity, so re-lock targets whatever subject is centered; this is operator-assisted by design.

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: Tello tracks visual-me by default; AprilTag designates other targets"
```

---

## Self-Review

**Spec coverage** (each spec section → task):
- Target model (visual-me default, tag for others) → Task 3.1 (default `.visualMe`), 3.2 (arm mode), 4.x (vocab).
- Manual override (exists) → unchanged; re-lock interplay → 3.3/3.5.
- Re-lock on command, centered subject → 3.3 (`requestLock` → `ObjectTracker.reset`), 4.2/5.1 (voice + button).
- Confirm-always → 3.3 (`confirmed=false`), 3.5 (`resumeFollow` no longer auto-confirms).
- Context-aware confirm timeout → 3.4.
- Wire `target_type`/`target_label` → 1.1, 1.3, 5.2; stale preservation → 1.2.
- Dashboard badge → 6.1, 6.2.
- Testability seams (CommandSink, clock, synthetic feed) → 2.1, 2.2, 2.3.
- Voice vocabulary (trackTag, confirm) → 4.1; routing → 4.2.
- UI (ME/TAG toggle, RE-LOCK, confirm bar gate) → 5.1.
- Docs divergence note → 7.1.
- Non-goals (no person re-ID, no laptop-driven selection, no new mission stages, no multi-tag UI) → respected; `target_label` left `nil` (Task 5.2) per the deferred tag-id-selection non-goal.

**Type/signature consistency:** `TargetMode {visualMe, tag}` (3.1) used consistently in `arm(stream:mode:)` (3.2), `requestLock(_:)` (3.3), `targetType` (5.2), `ControlBar` callbacks (5.1). `DroneCommandSink.send/rc` (2.1) matched by `RecordingCommandSink` (2.3) and `commands.` calls (2.2). `confirmTimeoutLands` set in `arm` (3.2) + `requestLock` (3.3), read in `tick` (3.4). `target_type` enum string values `"visual_me"`/`"tag"` identical across pydantic (1.1), TS (1.3/6.1), Swift (`targetType`, 5.2), and `followTargetLabel` (6.1).

**Placeholder scan:** No TBD/TODO; every code step shows complete code. Two locate-and-update steps use `grep` for known call-site patterns (`pendingArm` in 3.2, `sendFollowState(` in 5.2) because those call sites live in unread regions of `ContentView`; the exact replacement code is given.

---

## Execution notes / risks

- **Swift tests require the iOS simulator** (`xcodebuild test`). Phases 1 and 6 (Python/TS) are runnable headless; Phases 2-5 (Swift) need Xcode/simulator on the dev machine.
- **Threading in tests:** the test seams (`tickForTest`, `injectDetectionForTest`, `enterAirborneForTest`) run synchronously on the test thread; production paths still use `rcQueue`/`detectQueue`. The seams set `rcQueue`-owned vars directly — safe because tests never start the real timer.
- **`pauseToManual`/`tick` already call `commands`/`now` after Phase 2** — verify no stray `TelloCommander.shared` / `CACurrentMediaTime()` remain (grep both in `FollowCoordinator.swift` after Task 2.2).
- **Scout/scripted resume** now re-confirms (Task 3.5) — confirm with the operator this is acceptable (it is the "confirm-always" decision applied consistently).
