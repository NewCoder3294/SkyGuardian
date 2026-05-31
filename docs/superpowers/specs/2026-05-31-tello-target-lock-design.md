# Tello Target Lock: visual-me / AprilTag tracking, manual override, command re-lock

**Date:** 2026-05-31
**Status:** Design approved; pending spec review → implementation plan
**Scope:** Phone-side (`mobile/Sources/FollowCoordinator.swift` + small new type), with a minimal `FollowState` wire addition and a dashboard label.

## Goal

Let the operator:
1. **Track a target** that is either **themselves (visual lock)** or an **AprilTag** (used to designate *other* things — a vehicle, a spot, another person).
2. **Take manual control** at any time by **voice or buttons** (nudge the drone around).
3. **Lock back onto the target on command** ("follow me" / a button), re-acquiring through an explicit confirm.

This is largely a re-shaping of existing machinery (two follow modes, a manual-hover pause, a confirm gate already exist) into one coherent, switchable, target-aware state machine — not a from-scratch build.

## Decided behavioral model

| Aspect | Decision |
|---|---|
| Default target | Track **me** visually (`ObjectTracker` / Vision `VNTrackObjectRequest`) |
| AprilTag | Designate **other** targets; switch to/from it mid-flight |
| Manual override | Voice or buttons → steady hover, `manual` phase (already exists) |
| Re-lock trigger | **On command** (voice "follow me" / `RE-LOCK` button); re-locks the subject centered in view |
| Re-identification of "me" | None inherent (visual tracking has no identity) — operator-assisted: the centered subject becomes the lock |
| Confirm gate | **Always** — every new lock (re-lock me *or* switch to tag) hovers in `confirming` until the operator approves |

### Divergence from current docs (intentional)

`CLAUDE.md` currently states the Tello *"Follows the soldier using an AprilTag worn by the soldier."* This design **flips that**: visual `.visualMe` becomes the "me" target and the AprilTag is repurposed for designating other targets. Visual tracking is less robust than a worn tag (no identity; can drift/mis-lock in clutter); the "confirm-always" gate and command-only re-lock are the mitigations. `CLAUDE.md` (Tello role + command flow) is updated to match as part of this work.

## Current state (grounded in code)

- **Two follow modes exist.** `.tag` (`AprilTagDetector`, tag36h11) and visual track (`ObjectTracker`); both synthesize a `TagDetection` (distance/bearing/elevation) consumed by the pure PD controller `FollowController.command(for:) → RCCommand`, streamed at 15 Hz (`rcInterval = 0.066s`) via `TelloCommander.shared.rc()`. **Mode is fixed at arm time (`arm()` vs `armTrack()`) — no mid-flight switch.**
- **Phases** (`FollowCoordinator.Phase`): `disarmed / searching / confirming / following / lost / manual`. Server injects `stale` when the phone stream ages > 2 s.
- **Confirm gate exists.** `confirming` hovers until `confirmTarget()`; 30 s timeout currently auto-lands.
- **Manual override exists.** Movement voice/buttons → `pauseToManual()` (`followActive=false`, `manualHover=true`, steady hover, phase `manual`).
- **Resume exists but auto-confirms.** `resumeFollow()` sets `confirmed=true` directly and re-enters `searching` — this is the one behavior we change.
- **Re-lock today** is visual-only (`relock()` → `ObjectTracker.reset()`); AprilTag has no explicit re-lock.

## Architecture (Approach A — extend `FollowCoordinator`)

### `TargetMode`, orthogonal to `Phase`

```
TargetMode = .visualMe   // ObjectTracker — the default "me" target
           | .tag        // AprilTagDetector — designate another target
```

`Phase` is unchanged. `TargetMode` is *what kind of thing* we lock; `Phase` is *where we are* acquiring/following it. The mode/lock-arbitration logic is **extracted into a small focused type** so `FollowCoordinator` (already large) does not grow further.

### One unified entry: `requestLock(mode)`

The single path that starts a lock, switches target type, or re-locks after manual:
1. set `self.mode = mode`; clear the previous target's last reading (`latest = nil`); re-initialize that detector — for `.visualMe`, `ObjectTracker.reset()`, which re-acquires using its existing logic (salient subject nearest frame center, else a centered default box); for `.tag`, arm `AprilTagDetector` (strongest `decisionMargin` tag in view);
2. set `confirmed = false`, phase → `searching`;
3. on a stable candidate → `confirming` (hover, show lock; no follow RC);
4. → `following` only after `confirmTarget()`.

Manual is a **pause overlay**: `pauseToManual()` → `manual` + hover. Leaving manual is `requestLock(currentMode)`, so re-lock always flows back through `confirming`. **`resumeFollow()` no longer auto-confirms** (it routes through `confirming`).

### State machine

```
 disarmed ─arm(mode)─► searching ─candidate─► confirming ─CONFIRM─► following
     ▲                    ▲                       │                    │
  land/disarm             │                  30s timeout          stale >1.5s
     │                    requestLock(mode)   (on arm→land;          ▼
     │                    (re-lock / switch)  mid-flight→manual)    lost ─45s─► land
     │                    ▲          ▲                                │
     └── manual ◄─pauseToManual()────┴────────────────────────────────┘
            └── requestLock(.visualMe | .tag) ─► searching … confirming … following
```

Threading unchanged: `mode` / `confirmed` / phase mutate on `rcQueue` (serial); detection on `detectQueue`. `requestLock` dispatches its state changes onto `rcQueue`.

## Voice & button vocabulary

On-device `DronePilot.resolve()` (Gemma function-call) with `DroneIntent.match()` keyword fallback. Two new `DroneFunction` cases: `trackTag`, `confirm`.

| Operator input | Function | Action |
|---|---|---|
| "follow me", "lock on(to me)", "track me", "come back" | `followMe` / `track` | `requestLock(.visualMe)` |
| "track the tag", "follow that tag", "designate", "lock the tag" | `trackTag` *(new)* | `requestLock(.tag)` |
| "confirm", "go", "lock it", "yes" | `confirm` *(new)* | `confirmTarget()` — valid only in `confirming` |
| "forward/back/left/right/up/down/rotate…", "flip" | movement (exists) | `pauseToManual()` + `execute()` → `manual` |
| "hold", "recall", "stop", "land", "emergency" | exists | unchanged — priority/safety, always live |

**`ContentView.handle()` routing:** `followMe`/`track` → `requestLock(.visualMe)`; `trackTag` → `requestLock(.tag)`; `confirm` → `confirmTarget()`; movement → `pauseToManual()+execute()` (unchanged); safety/mission intents unchanged.

**Buttons** (`ControlBar` + the existing confirm bar in `TelloVideoView`):
- **`ME / TAG` target toggle** — tap requests a lock in that mode (→ `confirming`); the mid-flight switch.
- **`RE-LOCK`** — `requestLock(currentMode)`; one-tap "lock back onto me".
- **`CONFIRM`** — exists in the confirm bar (`phase == .confirming`); now the gate for re-locks/switches too.
- Manual nudge buttons and the always-on hard **LAND/STOP** — unchanged.

Every lock has both a voice path and a button path.

## Wire contract & dashboard

Additions to **`FollowState`**, mirrored in `backend/app/contracts.py`, `shared/contracts.ts`, `mobile/Sources/Contracts.swift`:

| Field | Type | Meaning |
|---|---|---|
| `target_type` | `"visual_me" \| "tag" \| null` | what the lock is on; `null` when not following |
| `target_label` | `string \| null` (optional) | raw identifier hint only — e.g. the tag id `"7"`; `null` for `visual_me` |

Both **optional, default `null`** → existing messages and the stale path keep validating. The human display string (`"ME (visual)"`, `"TAG #7"`) is **composed on the dashboard** by the pure `followTargetLabel(state)` helper from `target_type` + `target_label`, not sent on the wire.

- **No new `IntentMessage` commands.** From the laptop's mission view the phone is still `following` (or `holding` in manual); `requestLock(.visualMe)` / `requestLock(.tag)` both still send `FOLLOW_ME`, `pauseToManual()` still sends `HOLD`. The mode distinction rides on `FollowState` as advisory telemetry.
- **Server (`server.py`)** passes `target_type`/`target_label` through the rebroadcast; stale-downgrade keeps the last `target_type` with `phase="stale"`.
- **Dashboard (`FollowInset`)** adds a target badge — `FOLLOWING · ME (visual)` / `FOLLOWING · TAG #7` — beside the existing range/bearing radar and phase.

## Error handling & safety

- **Nothing follows without approval.** Every lock (initial / switch / re-lock) passes through `confirming` (hover, no follow RC) until `confirmTarget()`. Designating another target can never blind-chase.
- **Context-aware confirm timeout:** initial **arm** → 30 s no-confirm → `disarmAndLand()` (kept failsafe); **mid-flight** re-lock/switch → 30 s no-confirm → fall back to **`manual` hover, not land**.
- **Manual & kill always reachable.** Any nudge (voice/button) → `pauseToManual()` from any armed phase (`following`/`confirming`/`lost`). `STOP / RECALL / LAND / emergency` stay top-priority, bypassing mode/phase.
- **Visual-`me` fragility:** lock loss while `following` → `lost` → hover (1.5 s stale → `lost`, 45 s → auto-land). Re-acquire is **command-only** (never silent auto-lock onto a passerby). The lost auto-land timer runs only in `lost`, **never in `manual`**.
- **Clean detector swap:** `requestLock` clears the prior reading (`latest = nil`) and re-inits the target detector while hovering in `searching`, so a half-initialized tracker / stale prior detection can't cause erratic motion.
- **Wire stays valid:** `target_type` is a validated enum across pydantic/TS/Codable; `FollowState`'s finite/bounded invariants are unchanged.

## Testing

Three additive testability seams (no behavior change):
- **`CommandSink` protocol** (`rc`/`takeoff`/`land`); `TelloCommander.shared` conforms; `FollowCoordinator` takes one (default = singleton). Tests inject a `RecordingCommandSink`.
- **Synthetic detection feed** — hand the coordinator `TagDetection?` values directly (no image pipeline), as `FollowControllerTests` already do.
- **Injectable clock** (`now: () -> TimeInterval`, default `CACurrentMediaTime`) for deterministic timeout tests.

Test matrix (one logical assertion each; no real hardware; deterministic):

- **`FollowCoordinatorTests` (XCTestCase):** re-lock from `manual` lands in `confirming` not `following`; `confirmTarget()` → `following` + follow RC flows; `requestLock(.tag)` while following → back to `searching`, detector swapped, prior reading cleared; movement cmd → `pauseToManual()` → `manual` + steady hover; confirm-timeout → land on initial arm, `manual` on mid-flight re-lock; lost auto-land fires in `lost` but not `manual`; `FollowState.target_type` reflects current mode.
- **`IntentParserTests`:** "follow me"/"track me" → visual-me; "track the tag"/"designate" → `trackTag`; "confirm"/"go" → `confirm`; negative: "follow me" does not match `trackTag`.
- **`ContractsTests` + backend `test_contracts.py`:** `FollowState` round-trips `target_type`/`target_label`; omitted/`null` is backward-compatible; backend rejects bad enum values; server rebroadcast preserves `target_type`; stale-injection keeps it with `phase="stale"`.
- **TS (vitest):** pure `followTargetLabel(state)` helper (`"ME (visual)"` / `"TAG #7"`) tested for mapping; keeps label logic out of the `FollowInset` component.

## Files touched

- `mobile/Sources/FollowCoordinator.swift` — `requestLock`, `TargetMode`, rework `resumeFollow`, context-aware confirm timeout, seams (CommandSink, clock, synthetic feed).
- New small Swift type for mode/lock arbitration (extracted from `FollowCoordinator`).
- `mobile/Sources/DroneFunction.swift` — add `trackTag`, `confirm`; keyword sets.
- `mobile/Sources/DronePilot.swift` — Gemma system prompt lists the new functions.
- `mobile/Sources/ContentView.swift` — `handle()` routing.
- `mobile/Sources/ControlBar.swift` (+ `TelloVideoView.swift`) — `ME/TAG` toggle, `RE-LOCK` button, confirm bar gate.
- `mobile/Sources/Contracts.swift`, `shared/contracts.ts`, `backend/app/contracts.py` — `target_type`/`target_label` on `FollowState`.
- `backend/app/server.py` — pass-through in rebroadcast/stale path.
- `frontend/src/components/FollowInset.tsx` + a pure `followTargetLabel` lib helper.
- Tests: `mobile/Tests/FollowCoordinatorTests.swift` (new), `IntentParserTests`, `ContractsTests`; `backend/tests/test_contracts.py`; a frontend vitest for the label helper.
- `CLAUDE.md` — update the Tello role + command flow to the visual-me/tag model.

## Non-goals (YAGNI)

- **No person re-identification.** Visual "me" has no identity; re-lock is operator-assisted (centered subject).
- **No laptop-driven target selection / `ApproachController` revival.** Stays phone-side; `Designator` remains read-only situational awareness.
- **No arming interlock** between phone and laptop (still an operating rule, out of scope here).
- **No new mission stages.** The laptop mission state machine is unchanged; target type is advisory telemetry only.
- **No multi-tag disambiguation UI** beyond "strongest tag in view, operator confirms"; specific tag-ID selection is deferred.
