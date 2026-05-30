# Cross-Frame Drone Path Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render the Tello's flight path on both the phone map and the laptop dashboard map, co-registered into one shared frame.

**Architecture:** The world frame is north-up with the launch AprilTag at the origin (already the dashboard's `LocalMap2D` convention and the SLAM origin). The phone observes that same anchor tag, computes its operator-origin → launch-origin **translation** (`FrameAligner`), re-expresses its localized operator + drone positions in the world frame, and publishes them as a new `EntityReport` client message. The backend upserts them into the `world_model`; the existing broadcast fans them to both clients. The dashboard gains per-entity trail rendering mirroring the phone's.

**Tech Stack:** Python/FastAPI/Pydantic (backend), TypeScript/React/Canvas + Vitest (dashboard), Swift/SwiftUI + XCTest + simd + the AprilTag C library (mobile).

---

## File Structure

**Backend**
- Modify `backend/app/contracts.py` — add `EntityReport` message + `parse_client_message` branch.
- Modify `backend/app/server.py` — handle `EntityReport` in `ws_endpoint`; new `_apply_entity_report`.
- Modify `backend/tests/test_contracts.py` — `EntityReport` validation tests.
- Modify `backend/tests/test_world_model.py` — phone-report upsert + TTL stale-out.

**Shared**
- Modify `shared/contracts.ts` — mirror `EntityReport` + extend `ClientMessage`.

**Dashboard**
- Create `frontend/src/lib/trails.ts` — pure per-entity trail accumulator.
- Create `frontend/src/lib/trails.test.ts` — vitest unit tests.
- Modify `frontend/src/components/LocalMap2D.tsx` — accumulate + draw trails.

**Mobile**
- Modify `mobile/Sources/AprilTagDetector.swift` — expose anchor pose (camera position in tag frame).
- Create `mobile/Sources/FrameAligner.swift` — operator-origin → world-origin translation.
- Create `mobile/Tests/FrameAlignerTests.swift` — transform round-trip tests.
- Modify `mobile/Sources/Contracts.swift` — `EntityReportMessage`.
- Modify `mobile/Sources/Localizer.swift` — apply `FrameAligner`; expose world entities.
- Modify `mobile/Sources/WorldClient.swift` — `sendEntityReport`.
- Modify `mobile/Sources/ContentView.swift` — wire anchor observation + periodic report.
- Modify `mobile/Tests/ContractsTests.swift` — `EntityReportMessage` encode test.

---

## Task 1: Backend contract — `EntityReport`

**Files:**
- Modify: `backend/app/contracts.py`
- Test: `backend/tests/test_contracts.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_contracts.py`:

```python
import math
import pytest
from app.contracts import parse_client_message, EntityReport
from pydantic import ValidationError


def test_entity_report_parses_with_entities():
    raw = {
        "type": "entity_report",
        "entities": [
            {"id": "drone", "type": "drone", "position": {"x": 1.0, "y": 2.0, "z": 0.0},
             "timestamp": 100.0, "source": "follow"},
        ],
        "source": "phone",
        "t": 100.0,
    }
    msg = parse_client_message(raw)
    assert isinstance(msg, EntityReport)
    assert msg.entities[0].id == "drone"


def test_entity_report_rejects_nan_position():
    raw = {
        "type": "entity_report",
        "entities": [
            {"id": "drone", "type": "drone",
             "position": {"x": math.nan, "y": 0.0, "z": 0.0},
             "timestamp": 1.0, "source": "follow"},
        ],
        "source": "phone", "t": 1.0,
    }
    with pytest.raises((ValidationError, ValueError)):
        parse_client_message(raw)


def test_entity_report_rejects_too_many_entities():
    raw = {
        "type": "entity_report",
        "entities": [
            {"id": f"e{i}", "type": "object", "position": {"x": 0, "y": 0, "z": 0},
             "timestamp": 1.0, "source": "follow"} for i in range(20)
        ],
        "source": "phone", "t": 1.0,
    }
    with pytest.raises((ValidationError, ValueError)):
        parse_client_message(raw)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_contracts.py -k entity_report -v`
Expected: FAIL — `ImportError: cannot import name 'EntityReport'`.

- [ ] **Step 3: Implement `EntityReport` + parser branch**

In `backend/app/contracts.py`, after the `DeviceLocation` class add:

```python
class EntityReport(BaseModel):
    """Phone-localized entities (operator + drone) expressed in the shared WORLD
    frame (north-up metres, launch anchor tag = origin). The phone co-registers
    against the same launch tag the Mavic uses, so these upsert directly into the
    world model and render on both maps. Bounded + finite so a malformed payload
    can't poison the snapshot.
    """

    model_config = ConfigDict(allow_inf_nan=False)

    type: Literal["entity_report"] = "entity_report"
    entities: list[Entity] = Field(max_length=8)
    source: str = "phone"
    t: float
```

Update the `ClientMessage` union and parser:

```python
ClientMessage = Union[IntentMessage, DeviceLocation, FollowState, EntityReport]


def parse_client_message(raw: dict) -> ClientMessage:
    """Validate an inbound client message. Raises pydantic.ValidationError on
    unknown command / malformed payload — unknown intents are rejected, never guessed.
    """
    kind = raw.get("type")
    if kind == "intent":
        return IntentMessage.model_validate(raw)
    if kind == "device_location":
        return DeviceLocation.model_validate(raw)
    if kind == "follow_state":
        return FollowState.model_validate(raw)
    if kind == "entity_report":
        return EntityReport.model_validate(raw)
    raise ValueError(f"unknown client message type: {kind!r}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_contracts.py -k entity_report -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/contracts.py backend/tests/test_contracts.py
git commit -m "feat(contracts): add EntityReport client message for phone-localized world entities"
```

---

## Task 2: Backend — apply `EntityReport` into the world model

**Files:**
- Modify: `backend/app/server.py` (add `_apply_entity_report`; branch in `ws_endpoint` ~line 1013)
- Test: `backend/tests/test_world_model.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_world_model.py`:

```python
from app.clock import Clock
from app.contracts import Entity, EntityType, EntitySource
from app.world_model import WorldModel


class FakeClock(Clock):
    def __init__(self, t=0.0):
        self._t = t
    def now(self) -> float:
        return self._t


def test_phone_reported_drone_appears_then_goes_stale():
    clock = FakeClock(100.0)
    world = WorldModel(clock=clock)
    world.upsert(Entity(
        id="drone", type=EntityType.DRONE,
        position={"x": 5.0, "y": 3.0, "z": 0.0},
        timestamp=100.0, source=EntitySource.FOLLOW, label="tello", ttl_s=4.0,
    ))
    snap = world.snapshot()
    assert any(e.id == "drone" and e.status.value == "active" for e in snap)

    clock._t = 105.0  # 5s later, past ttl_s=4 → stale
    snap = world.snapshot()
    drone = next(e for e in snap if e.id == "drone")
    assert drone.status.value == "stale"
```

- [ ] **Step 2: Run test to verify it fails (or passes trivially) and confirm baseline**

Run: `cd backend && .venv/bin/python -m pytest tests/test_world_model.py -k phone_reported -v`
Expected: PASS — this validates the existing `WorldModel` TTL path the handler relies on. (If `Clock` import differs, align with the existing import in this test file.)

- [ ] **Step 3: Implement the handler**

In `backend/app/server.py`, add near `_apply_device_location` (~line 977):

```python
def _apply_entity_report(msg: EntityReport) -> None:
    """Phone-localized entities (operator + drone), already in the shared world
    frame. The phone co-registers against the launch anchor tag, so these upsert
    straight into the world model. TTL on each entity ages them out if the phone
    link drops (no frozen drone left on the map)."""
    for entity in msg.entities:
        world.upsert(entity)
```

Add the import to the existing contracts import block (top of `server.py`):

```python
    EntityReport,
```

Add the branch in `ws_endpoint` after the `FollowState` branch (~line 1013):

```python
            elif isinstance(msg, EntityReport):
                _apply_entity_report(msg)
```

- [ ] **Step 4: Run the full backend suite**

Run: `cd backend && .venv/bin/python -m pytest -q`
Expected: PASS (all existing tests + the new one).

- [ ] **Step 5: Commit**

```bash
git add backend/app/server.py backend/tests/test_world_model.py
git commit -m "feat(server): upsert phone EntityReport into the world model"
```

---

## Task 3: Shared TS contract mirror

**Files:**
- Modify: `shared/contracts.ts`

- [ ] **Step 1: Add the mirror (type-only; no test framework for shared)**

In `shared/contracts.ts`, after the `DeviceLocation` interface add:

```typescript
export interface EntityReport {
  type: "entity_report";
  entities: Entity[];
  source: "phone";
  t: number;
}
```

Update the union:

```typescript
export type ClientMessage = IntentMessage | DeviceLocation | EntityReport;
```

- [ ] **Step 2: Type-check**

Run: `cd frontend && npx tsc --noEmit -p tsconfig.json`
Expected: no new errors (the dashboard imports `Entity` from its own `lib/contracts`; this mirror is the canonical reference).

- [ ] **Step 3: Commit**

```bash
git add shared/contracts.ts
git commit -m "feat(contracts): mirror EntityReport in shared TS contracts"
```

---

## Task 4: Dashboard trail accumulator (pure lib)

**Files:**
- Create: `frontend/src/lib/trails.ts`
- Test: `frontend/src/lib/trails.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/lib/trails.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
import { TrailStore } from "./trails";

describe("TrailStore", () => {
  it("starts a trail for a moving entity", () => {
    const store = new TrailStore();
    store.update([{ id: "drone", type: "drone", x: 0, y: 0 }]);
    store.update([{ id: "drone", type: "drone", x: 1, y: 0 }]);
    expect(store.get("drone")).toEqual([{ x: 0, y: 0 }, { x: 1, y: 0 }]);
  });

  it("dedupes sub-threshold jitter", () => {
    const store = new TrailStore(0.2 /* min metres */);
    store.update([{ id: "drone", type: "drone", x: 0, y: 0 }]);
    store.update([{ id: "drone", type: "drone", x: 0.1, y: 0 }]); // < 0.2 m
    expect(store.get("drone")).toEqual([{ x: 0, y: 0 }]);
  });

  it("caps the ring buffer", () => {
    const store = new TrailStore(0, 3 /* cap */);
    for (let i = 0; i < 5; i++) {
      store.update([{ id: "drone", type: "drone", x: i, y: 0 }]);
    }
    expect(store.get("drone")).toEqual([{ x: 2, y: 0 }, { x: 3, y: 0 }, { x: 4, y: 0 }]);
  });

  it("ignores non-moving entity types", () => {
    const store = new TrailStore();
    store.update([{ id: "poi1", type: "poi", x: 0, y: 0 }]);
    expect(store.get("poi1")).toEqual([]);
  });

  it("clears a trail when its entity disappears", () => {
    const store = new TrailStore();
    store.update([{ id: "drone", type: "drone", x: 0, y: 0 }]);
    store.update([]); // entity gone
    expect(store.get("drone")).toEqual([]);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/lib/trails.test.ts`
Expected: FAIL — `Cannot find module './trails'`.

- [ ] **Step 3: Implement `TrailStore`**

Create `frontend/src/lib/trails.ts`:

```typescript
import type { EntityType } from "./contracts";

export interface TrailPoint {
  x: number;
  y: number;
}

interface MovingInput {
  id: string;
  type: EntityType;
  x: number;
  y: number;
}

/** Moving entity types that get a path. Mirrors mobile WorldClient.appendTrails. */
const MOVING: ReadonlySet<EntityType> = new Set(["soldier", "drone"]);

/**
 * Accumulates per-entity movement trails from the WS entity stream — the
 * dashboard equivalent of mobile/Sources/Localizer.swift's droneTrail. Dedupes
 * sub-threshold jitter, caps history, and clears a trail when its entity leaves
 * the snapshot.
 */
export class TrailStore {
  private trails = new Map<string, TrailPoint[]>();

  constructor(
    private minMetres = 0.2,
    private cap = 240,
  ) {}

  update(entities: MovingInput[]): void {
    const seen = new Set<string>();
    for (const e of entities) {
      if (!MOVING.has(e.type)) continue;
      seen.add(e.id);
      const pts = this.trails.get(e.id) ?? [];
      const last = pts[pts.length - 1];
      if (last) {
        const dx = last.x - e.x;
        const dy = last.y - e.y;
        if (dx * dx + dy * dy < this.minMetres * this.minMetres) continue;
      }
      pts.push({ x: e.x, y: e.y });
      if (pts.length > this.cap) pts.splice(0, pts.length - this.cap);
      this.trails.set(e.id, pts);
    }
    // Drop trails whose entity left the snapshot.
    for (const id of this.trails.keys()) {
      if (!seen.has(id)) this.trails.delete(id);
    }
  }

  get(id: string): TrailPoint[] {
    return this.trails.get(id) ?? [];
  }

  all(): Map<string, TrailPoint[]> {
    return this.trails;
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/lib/trails.test.ts`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/trails.ts frontend/src/lib/trails.test.ts
git commit -m "feat(dashboard): pure per-entity trail accumulator with tests"
```

---

## Task 5: Dashboard — draw trails in `LocalMap2D`

**Files:**
- Modify: `frontend/src/components/LocalMap2D.tsx`

- [ ] **Step 1: Add a TrailStore ref and feed it from entities**

In `LocalMap2D`, add the import at the top:

```typescript
import { TrailStore } from "@/lib/trails";
```

Inside the component, near the other refs (after `entitiesRef`):

```typescript
  const trailsRef = useRef<TrailStore>(new TrailStore());
```

Immediately after the existing `entitiesRef.current = entities;` line, feed the store:

```typescript
  trailsRef.current.update(
    entities.map((e) => ({ id: e.id, type: e.type, x: e.position.x, y: e.position.y })),
  );
```

- [ ] **Step 2: Draw trails beneath entity glyphs**

In the `draw` callback, add a `drawTrails` call **before** `drawEntities` (so glyphs sit on top):

```typescript
    drawOrigin(ctx, w, h, v);
    drawTrails(ctx, w, h, v, trailsRef.current);
    drawEntities(ctx, w, h, v, entitiesRef.current);
```

- [ ] **Step 3: Implement `drawTrails`**

Add this function alongside `drawEntities` (bottom of the file, module scope):

```typescript
function drawTrails(
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  v: ViewState,
  trails: TrailStore,
) {
  ctx.lineWidth = 1.5;
  ctx.strokeStyle = "rgba(167, 107, 28, 0.45)"; // amber, matches drone glyph
  for (const pts of trails.all().values()) {
    if (pts.length < 2) continue;
    ctx.beginPath();
    for (let i = 0; i < pts.length; i++) {
      const [sx, sy] = worldToScreen(pts[i].x, pts[i].y, w, h, v);
      if (i === 0) ctx.moveTo(sx, sy);
      else ctx.lineTo(sx, sy);
    }
    ctx.stroke();
  }
}
```

- [ ] **Step 4: Verify build + existing tests**

Run: `cd frontend && npx tsc --noEmit -p tsconfig.json && npx vitest run`
Expected: type-check clean; all vitest suites PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/LocalMap2D.tsx
git commit -m "feat(dashboard): render moving-entity trails on the tactical map"
```

---

## Task 6: Mobile contract — `EntityReportMessage`

**Files:**
- Modify: `mobile/Sources/Contracts.swift`
- Test: `mobile/Tests/ContractsTests.swift`

- [ ] **Step 1: Write the failing test**

Add to `mobile/Tests/ContractsTests.swift`:

```swift
func testEntityReportMessageEncodesWithEntities() throws {
    let drone = Entity(id: "drone", type: .drone, position: Vec3(x: 1, y: 2, z: 0),
                       confidence: 1, timestamp: 100, source: .follow, label: "tello",
                       ttlS: 4, status: .active)
    let msg = EntityReportMessage(entities: [drone], source: "phone", t: 100)
    let data = try JSONEncoder().encode(msg)
    let obj = try JSONSerialization.jsonObject(with: data) as! [String: Any]
    XCTAssertEqual(obj["type"] as? String, "entity_report")
    let ents = obj["entities"] as! [[String: Any]]
    XCTAssertEqual(ents.first?["id"] as? String, "drone")
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd mobile && xcodebuild test -scheme SkyGuardian -destination 'platform=iOS Simulator,name=iPhone 15' -only-testing:SkyGuardianTests/ContractsTests/testEntityReportMessageEncodesWithEntities 2>&1 | tail -20`
Expected: FAIL — `cannot find 'EntityReportMessage' in scope`.

- [ ] **Step 3: Implement the message**

In `mobile/Sources/Contracts.swift`, after `FollowStateMessage`:

```swift
/// Phone-localized entities (operator + drone) expressed in the shared WORLD
/// frame (north-up metres, launch anchor tag = origin). Mirrors backend
/// EntityReport. The laptop upserts these into the world model so they render on
/// both maps.
struct EntityReportMessage: Encodable, Sendable {
    let type = "entity_report"
    let entities: [Entity]
    let source: String
    let t: Double
}
```

> Note: `Entity` is already `Codable` (it currently only decodes from `world_snapshot`; encoding for the report uses the same `CodingKeys`, emitting `ttl_s`).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd mobile && xcodebuild test -scheme SkyGuardian -destination 'platform=iOS Simulator,name=iPhone 15' -only-testing:SkyGuardianTests/ContractsTests/testEntityReportMessageEncodesWithEntities 2>&1 | tail -20`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add mobile/Sources/Contracts.swift mobile/Tests/ContractsTests.swift
git commit -m "feat(mobile): add EntityReportMessage mirroring backend EntityReport"
```

---

## Task 7: Mobile — expose anchor pose from `AprilTagDetector`

**Files:**
- Modify: `mobile/Sources/AprilTagDetector.swift`

- [ ] **Step 1: Add the anchor-frame offset to `TagDetection`**

The detector already runs `estimate_tag_pose` (rotation `pose.R`, translation `pose.t`) but only reads `tz`. We need the tag's **horizontal** position relative to the camera to translate frames. The existing `distance` (tz, metres along optical axis) + `bearingRad` already give that in polar form, which is exactly what `Localizer` consumes for the drone. So **no struct change is required** — `FrameAligner` (Task 8) consumes the same `(distance, bearingRad)` the follow loop already produces.

Confirm `TagDetection` exposes both (it does, per current source):

```swift
struct TagDetection {
    let id: Int
    let center: CGPoint
    let corners: [CGPoint]
    let distance: Double      // metres along optical axis
    let bearingRad: Double    // + = tag to the right
    let elevationRad: Double
    // ...
}
```

- [ ] **Step 2: No code change / no new test**

This task is a verification gate: the existing `(distance, bearingRad)` are sufficient inputs for `FrameAligner`. Confirm by reading `mobile/Sources/AprilTagDetector.swift` and checking `make(...)` returns finite `distance`/`bearingRad`.

Run: `cd mobile && grep -n "distance\|bearingRad" Sources/AprilTagDetector.swift`
Expected: both fields populated in the returned `TagDetection`.

- [ ] **Step 3: Commit (no-op marker)**

No commit — this task gates Task 8. Proceed.

---

## Task 8: Mobile — `FrameAligner`

**Files:**
- Create: `mobile/Sources/FrameAligner.swift`
- Test: `mobile/Tests/FrameAlignerTests.swift`

The world frame is north-up with the launch tag at the origin — the same convention as the phone's `Localizer` (operator at origin, north-up) and the dashboard. So co-registration is a **translation**: the operator's position in the world frame. From the anchor observation, the tag is at `(distance, bearing)` from the camera; rotated by the operator's compass heading the tag's north-up offset from the operator is `(d·sin(heading+bearing), d·cos(heading+bearing))`. The operator's position in the world (tag-origin) frame is the negative of that.

- [ ] **Step 1: Write the failing test**

Create `mobile/Tests/FrameAlignerTests.swift`:

```swift
import XCTest
@testable import SkyGuardian

final class FrameAlignerTests: XCTestCase {
    func testUnalignedReturnsNil() {
        let aligner = FrameAligner()
        XCTAssertNil(aligner.toWorld(Vec3(x: 1, y: 2, z: 0)))
    }

    func testTagDueNorthPlacesOperatorDueSouth() {
        // Heading 0 (facing north), tag straight ahead (bearing 0) at 5 m.
        // Tag is 5 m north of operator → operator is at (0, -5) in world frame.
        let aligner = FrameAligner()
        aligner.observe(distance: 5, bearingRad: 0, headingDeg: 0)
        let op = aligner.toWorld(Vec3(x: 0, y: 0, z: 0))!
        XCTAssertEqual(op.x, 0, accuracy: 1e-6)
        XCTAssertEqual(op.y, -5, accuracy: 1e-6)
    }

    func testDronePointTranslatesByOperatorOffset() {
        // Same anchor; a drone 3 m north of the operator (0,3) → world (0, -2).
        let aligner = FrameAligner()
        aligner.observe(distance: 5, bearingRad: 0, headingDeg: 0)
        let drone = aligner.toWorld(Vec3(x: 0, y: 3, z: 0))!
        XCTAssertEqual(drone.x, 0, accuracy: 1e-6)
        XCTAssertEqual(drone.y, -2, accuracy: 1e-6)
    }

    func testReobservationUpdatesTransform() {
        let aligner = FrameAligner()
        aligner.observe(distance: 5, bearingRad: 0, headingDeg: 0)
        aligner.observe(distance: 10, bearingRad: 0, headingDeg: 0) // tag now 10 m north
        let op = aligner.toWorld(Vec3(x: 0, y: 0, z: 0))!
        XCTAssertEqual(op.y, -10, accuracy: 1e-6)
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd mobile && xcodebuild test -scheme SkyGuardian -destination 'platform=iOS Simulator,name=iPhone 15' -only-testing:SkyGuardianTests/FrameAlignerTests 2>&1 | tail -20`
Expected: FAIL — `cannot find 'FrameAligner' in scope`.

- [ ] **Step 3: Implement `FrameAligner`**

Create `mobile/Sources/FrameAligner.swift`:

```swift
import Foundation

/// Co-registers the phone's launch frame (operator at origin, north-up) with the
/// shared WORLD frame (launch anchor tag = origin, north-up). Because both frames
/// are north-up, alignment is a pure translation: the operator's position in the
/// world frame, derived from observing the launch anchor tag.
///
/// Observing the tag at (distance, bearing) with the operator's compass heading
/// places the tag at world-relative offset (d·sin(h+b), d·cos(h+b)) from the
/// operator; the operator therefore sits at the negative of that in the
/// tag-origin world frame. Re-observing the tag refreshes the translation
/// (drift correction).
@MainActor
final class FrameAligner: ObservableObject {
    /// Operator position in the world frame; nil until the first observation.
    @Published private(set) var operatorWorld: Vec3?

    var isAligned: Bool { operatorWorld != nil }

    /// Feed a fresh anchor-tag observation (same units the follow loop uses).
    func observe(distance: Double, bearingRad: Double, headingDeg: Double) {
        guard distance > 0, distance.isFinite, bearingRad.isFinite, headingDeg.isFinite else { return }
        let world = headingDeg * .pi / 180 + bearingRad
        let tagOffsetX = distance * sin(world)
        let tagOffsetY = distance * cos(world)
        operatorWorld = Vec3(x: -tagOffsetX, y: -tagOffsetY, z: 0)
    }

    /// Map a launch-frame (operator-origin) point into the world frame. nil while unaligned.
    func toWorld(_ p: Vec3) -> Vec3? {
        guard let op = operatorWorld else { return nil }
        return Vec3(x: p.x + op.x, y: p.y + op.y, z: p.z)
    }

    func reset() { operatorWorld = nil }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd mobile && xcodebuild test -scheme SkyGuardian -destination 'platform=iOS Simulator,name=iPhone 15' -only-testing:SkyGuardianTests/FrameAlignerTests 2>&1 | tail -20`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add mobile/Sources/FrameAligner.swift mobile/Tests/FrameAlignerTests.swift
git commit -m "feat(mobile): FrameAligner co-registers launch frame to world frame"
```

---

## Task 9: Mobile — `Localizer` exposes world-frame entities

**Files:**
- Modify: `mobile/Sources/Localizer.swift`

- [ ] **Step 1: Add a world-frame entities output driven by a FrameAligner**

Extend `Localizer` to optionally map its entities through a `FrameAligner`, exposing a `worldEntities` array (empty while unaligned). Add to `Localizer`:

```swift
    /// Entities re-expressed in the shared world frame (empty until aligned).
    /// These are what get published to the laptop; `entities` stays launch-frame
    /// for the on-device view so the local map still works pre-alignment.
    @Published private(set) var worldEntities: [Entity] = []

    /// Recompute worldEntities from the current launch-frame entities + aligner.
    func project(through aligner: FrameAligner) {
        worldEntities = entities.compactMap { e in
            guard let wp = aligner.toWorld(e.position) else { return nil }
            return Entity(id: e.id, type: e.type, position: wp, confidence: e.confidence,
                          timestamp: e.timestamp, source: e.source, label: e.label,
                          ttlS: e.ttlS, status: e.status)
        }
    }
```

- [ ] **Step 2: Set a real timestamp on published entities**

In `Localizer.update(...)`, the current entities use `timestamp: 0`. For the world model TTL to work, published entities need a real time. Change both `Entity(...)` constructions in `update` to stamp `timestamp: Date().timeIntervalSince1970` and use a finite `ttlS` (e.g. `4`) instead of `9999`:

```swift
        let now = Date().timeIntervalSince1970
        var ents: [Entity] = [
            Entity(id: "operator", type: .soldier, position: Vec3(x: 0, y: 0, z: 0),
                   confidence: 1, timestamp: now, source: .manual, label: "operator",
                   ttlS: 4, status: .active),
        ]
        // ... drone branch:
            ents.append(Entity(id: "drone", type: .drone, position: drone, confidence: 1,
                               timestamp: now, source: .follow, label: "tello",
                               ttlS: 4, status: .active))
```

> Per the testing rules, this introduces `Date()` in non-test code only; the unit tests for `FrameAligner` and contracts do not depend on it.

- [ ] **Step 3: Build to verify compilation**

Run: `cd mobile && xcodebuild build -scheme SkyGuardian -destination 'platform=iOS Simulator,name=iPhone 15' 2>&1 | tail -10`
Expected: BUILD SUCCEEDED.

- [ ] **Step 4: Commit**

```bash
git add mobile/Sources/Localizer.swift
git commit -m "feat(mobile): Localizer projects entities into the world frame for publishing"
```

---

## Task 10: Mobile — `WorldClient.sendEntityReport`

**Files:**
- Modify: `mobile/Sources/WorldClient.swift`

- [ ] **Step 1: Add the send method**

In `WorldClient`, alongside `sendFollowState`:

```swift
    /// Publish phone-localized entities (operator + drone) in the world frame so
    /// the laptop upserts them into the world model and both maps render them.
    /// Best-effort, fire-and-forget — drops silently if the socket isn't up.
    func sendEntityReport(_ entities: [Entity]) {
        guard let task, !entities.isEmpty else { return }
        let msg = EntityReportMessage(entities: entities, source: "phone",
                                      t: Date().timeIntervalSince1970)
        guard let data = try? encoder.encode(msg), let json = String(data: data, encoding: .utf8) else {
            return
        }
        task.send(.string(json)) { _ in }
    }
```

- [ ] **Step 2: Build to verify compilation**

Run: `cd mobile && xcodebuild build -scheme SkyGuardian -destination 'platform=iOS Simulator,name=iPhone 15' 2>&1 | tail -10`
Expected: BUILD SUCCEEDED.

- [ ] **Step 3: Commit**

```bash
git add mobile/Sources/WorldClient.swift
git commit -m "feat(mobile): WorldClient.sendEntityReport publishes world-frame entities"
```

---

## Task 11: Mobile — wire anchor observation + periodic publish

**Files:**
- Modify: `mobile/Sources/ContentView.swift`

This connects the pieces: a `FrameAligner` instance, observing the launch anchor tag once (and opportunistically again), and publishing the projected world entities on each localizer update.

- [ ] **Step 1: Add a FrameAligner and an "ALIGN" control**

In `ContentView`, add the state object near `localizer`:

```swift
    @StateObject private var aligner = FrameAligner()
```

Add an alignment action that uses the latest follow detection of the **anchor tag** as the observation. In `updateLocalizer()` (~line 84), after the existing `localizer.update(...)`, add the projection + publish:

```swift
        localizer.project(through: aligner)
        if !localizer.worldEntities.isEmpty {
            client.sendEntityReport(localizer.worldEntities)
        }
```

- [ ] **Step 2: Observe the anchor tag**

Add a method that feeds the anchor observation into the aligner from the current detection. The operator triggers this while pointing at the launch tag (a button bound to it), and it can also be called automatically whenever the anchor tag id is detected:

```swift
    /// Call while pointing the phone at the launch anchor tag. Uses the same
    /// (distance, bearing) the follow loop produces, plus the compass heading.
    private func alignToAnchor() {
        guard follow.distance > 0 else { return }
        aligner.observe(distance: follow.distance,
                        bearingRad: follow.bearingRad,
                        headingDeg: location.headingDeg)
    }
```

> If `follow.bearingRad` / `location.headingDeg` names differ in the current source, use the same accessors already passed into `localizer.update(...)` in `updateLocalizer()` (that call is the source of truth for the available signals).

- [ ] **Step 3: Add an ALIGN button to the Map tab control area**

In the Map view's control stack (where MISSION LINK / controls live), add:

```swift
    Button(aligner.isAligned ? "RE-ALIGN" : "ALIGN") { alignToAnchor() }
        .font(Theme.mono(11, weight: .semibold))
```

- [ ] **Step 4: Build + run the app, verify end-to-end**

Run: `cd mobile && xcodebuild build -scheme SkyGuardian -destination 'platform=iOS Simulator,name=iPhone 15' 2>&1 | tail -10`
Expected: BUILD SUCCEEDED.

Manual verification (device, on the demo network):
1. Backend running with the laptop on the shared network; dashboard open at `/operator`.
2. Phone connected (MISSION LINK). Point at the launch anchor tag → tap **ALIGN**.
3. With the Tello followed, confirm a **drone glyph + trail** appears on the dashboard map at the correct offset from LAUNCH, matching the phone map.

- [ ] **Step 5: Commit**

```bash
git add mobile/Sources/ContentView.swift
git commit -m "feat(mobile): align to launch anchor tag and publish world entities"
```

---

## Final verification

- [ ] Backend suite: `cd backend && .venv/bin/python -m pytest -q` → all PASS.
- [ ] Dashboard: `cd frontend && npx vitest run && npx tsc --noEmit` → all PASS, no type errors.
- [ ] Mobile: `cd mobile && xcodebuild test -scheme SkyGuardian -destination 'platform=iOS Simulator,name=iPhone 15'` → all PASS.
- [ ] Manual: drone path renders identically on phone + dashboard, co-registered to LAUNCH.

## Self-review notes (spec coverage)

- Shared anchor-tag common frame → Tasks 8, 11.
- `FrameAligner` (PnP/observation + drift recompute + unaligned state) → Task 8; re-observe → Task 11 RE-ALIGN.
- `Localizer` applies T → Task 9.
- `EntityReport` contract (approach A) → Tasks 1, 3, 6.
- Backend upsert + TTL stale-out → Tasks 2, 9 (finite ttl/timestamp).
- Dashboard trail rendering mirroring phone → Tasks 4, 5.
- Error handling (unaligned → no publish; stale TTL; bad payload rejected) → Tasks 1, 2, 8, 9.
- Tests: FrameAligner round-trip (8), contract (1, 6), world_model TTL (2), trail accumulator (4).

> **Known simplification vs. spec:** `FrameAligner` implements the north-up **translation** form (both frames already north-up per the dashboard's axis convention), rather than a full PnP rotation matrix. This is correct whenever the launch tag's frame is north-aligned with the world convention. If the anchor tag is mounted at an arbitrary yaw, extend `observe(...)` to also derive the in-plane rotation from `pose.R` (exposed via Task 7) — captured as the rotation-extension follow-up.
