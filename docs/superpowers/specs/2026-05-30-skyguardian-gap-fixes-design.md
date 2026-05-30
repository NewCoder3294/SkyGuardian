# SkyGuardian — Gap-Closure Design (pre-judging hardening)

**Date:** 2026-05-30
**Track:** Autonomous Navigation
**Scope:** Full-day, ambitious. Close the credibility/safety gaps surfaced by code review so the live demo and the judging narrative hold up under probing.

## Context

A code-level review confirmed six real gaps between SkyGuardian's framing and its shipped defaults (all verified against source, not the README):

1. No end-to-end integration evidence (unit tests only; `captures/`, `models/` hold only READMEs).
2. Metric map scale is heuristic (`depth.py` `scale=5.0`; `fusion.py` ground-plane z=0 assumption; two-view VO drifts, no loop closure).
3. Intel reasoning is text-only by default (`intel.py` `with_vision=False`; vision pass ~2 min/frame on M3; `_heuristic_threat_level()` keyword-matches labels, LLM only overrides via a `LEVEL:` line).
4. No arming interlock — phone and laptop `FollowController` can both command the Tello; prevented only by an operating rule, no code.
5. "Autonomous navigation" overclaimed — Mavic is video-in only (no flight code); the only flight autonomy is the Tello AprilTag follow loop (reactive control, not navigation).
6. Voice LLM is half-wired — live path is `SFSpeechRecognizer` → `DroneIntent.match` (keyword); `DronePilot` (Cactus/Gemma) exists and the `cactus.xcframework` is present and linked in `project.yml`, but is not on the live voice path.
7. (Operational) Dual-NIC networking is fragile; documented fallback is "everyone on the Tello AP."

## Goals

- Make the **Autonomous Navigation** claim genuine with a real, bounded autonomous flight behavior — without removing the existing follow-me or breaking voice.
- Close the **safety gap** (#4) in code so an autonomous, laptop-commanded drone is safe to fly on stage.
- Make the on-device **LLM voice** (#6) and **vision reasoning** (#3) claims demonstrably true, while keeping reliable fallbacks.
- Produce **evidence the full loop runs** (#1) and de-risk the live demo (#7).
- Turn the remaining framing gaps (#2, and the honest limits of #3/#5) into owned talking points, not surprises.

## Non-goals

- No Mavic flight autonomy (it stays human-piloted, video-in only — we will not claim otherwise).
- No attempt to make VO metric-accurate or add loop closure (#2 is reframed, not solved).
- No always-on per-frame vision (the 2-min cost is real; vision is an on-demand "deep look").
- No new map/UI framework — we plot through the existing world-model → dashboard path.

## Work items

### A. Autonomous approach-and-standoff (centerpiece, #5)

**Behavior:** the Tello autonomously navigates to a YOLO-detected entity and holds a safe standoff, then hovers. Flow: perception detects an entity → a target is selected (operator tap on the map/feed, voice "investigate that contact", or auto-pick nearest unknown) → the drone autonomously approaches and stations off at a set radius, with abort/timeout/geofence.

**Architecture — extend, don't rebuild.** `follow/controller.py` already runs a PD visual-servo loop, drives the Tello via `send_rc(lr, fb, ud, yaw)`/`hover()`, runs a state machine, and publishes the drone + target as world-model entities (`_emit_entities`, `source=FOLLOW`). The approach behavior is a sibling that reuses this machinery:

- New `follow/approach.py`: an `ApproachController` (or an `APPROACH` mode on a shared base) whose **target source is a world-model entity bearing/range** instead of an AprilTag `TagReading`. States: `SEEKING → APPROACHING → STANDOFF(hold) → ABORT`. Reuses the existing PD gains and RC-drive path; the only new input is "where is the target" (from detections projected into the local frame) and a standoff setpoint instead of follow distance.
- Mission intent over the WS: a new `Command` (e.g. `approach`/`investigate`) carrying a target entity id; routed by `server.py` to the laptop controller. `stop`/`hold`/`recall` already abort.
- Bounds: configurable standoff radius, approach speed cap, mission timeout, and a hard abort. The drone never closes inside the standoff ring.

**Map plotting (constraint 1):** `_emit_entities` already puts the drone and target into the world model, so both clients plot them with no new render path. The approach controller additionally emits: the **selected target** (highlighted), the **standoff ring**, and reuses the existing movement **trail** so the drone's approach path is visible live on `LocalMap2D`/`LocalMap3D`. (Small UI: distinguish an "approach target" entity/annotation; the map already renders entities + trails.)

**Coexistence with follow-me (constraint 2):** AprilTag follow-me (`FollowController`) is untouched and remains a selectable mode. Follow-me and approach are **mutually-exclusive laptop modes** arbitrated by the interlock (B) — the laptop runs one behavior at a time, and only when it holds the arming lock. Detection-based follow and AprilTag follow both remain available.

**Demo de-risk:** the approach loop is exercised in a **deterministic sim/replay harness** (synthetic target track → asserted approach + standoff, à la the existing VO smoke test) so a flaky Tello can't kill the demo; live hardware is a bonus.

### B. Arming interlock (#4) — safety prerequisite for A

A single software-enforced **armed-controller token** in the backend. `tello/client.py` + `server.py` gain an exclusive lock: any laptop controller (`FollowController`, `ApproachController`) refuses to send RC/flight commands unless it holds the lock; arming is exclusive vs. the phone-direct controller. Arming/disarming is explicit and surfaced in mission state over the WS so the dashboard shows who holds the drone. This is what makes A safe to fly on stage and closes the flagged gap in code rather than prose.

### C. Wire DronePilot/Cactus onto the live voice path (#6) — preserve voice (constraint 3)

`VoiceController` keeps `SFSpeechRecognizer` (offline STT, already hard-gated to on-device). After transcription it routes the transcript through **`DronePilot` (Cactus/Gemma function-calling) first**, falling back to the deterministic `DroneIntent.match` when Cactus is `UNAVAILABLE` or returns low-confidence/no-parse. Net: real on-device LLM voice control, with the keyword matcher as a guaranteed safety net so **voice never breaks**. The voice vocabulary gains the new `approach`/`investigate` intent (routed to A) alongside all existing commands.

### D. On-demand vision assessment (#3)

Keep text-only as the live default. Add an **on-demand "deep look"**: a single `INTEL_VISION=1` assessment over the current frame, triggered explicitly (button/voice), so "the model actually looks at the scene" is demonstrably true without paying 2 min every frame. Capture one such assessment for the demo reel. Talking point covers the heuristic-threat-level default honestly.

### E. Integration smoke test + recorded e2e run (#1, #7)

- **Software integration test:** drive the real pipeline end-to-end from a recorded input (source → SLAM/YOLO → world model → WS broadcast), asserting entities reach a subscribed client. First test that exercises the whole seam, not a single unit.
- **Recorded hardware demo:** capture a clean end-to-end run (Mavic feed → dashboard, Tello follow + autonomous approach, phone client) **using the exact stage network setup**, so the recording doubles as proof the dual-NIC config works and as a fallback if the live room fights us.

### F. Reframe (no code): #2 and honest limits

Own #2 as a designed tradeoff (offline, ~5 fps, AprilTag-anchored relative frame). Small honesty touch: label map positions as relative/approximate in the UI. Prepare judge-facing talking points for #2, the #3 default, and the #5 scope (Mavic human-piloted; autonomy is the Tello approach + follow).

## Testing strategy

- **A:** deterministic sim/replay unit tests for the approach state machine (synthetic target tracks → assert approach, standoff hold, abort, timeout); no real hardware required to prove correctness.
- **B:** unit tests that a controller without the lock cannot emit commands, and that arming is exclusive.
- **C:** existing `IntentParserTests` keep passing (fallback intact); add a test that DronePilot output maps to the same closed `DroneAction` vocabulary and that fallback triggers on `UNAVAILABLE`.
- **E:** the integration test is itself part of the deliverable.
- All tests deterministic (fake clock / synthetic inputs); no `Date.now()`/random; mock hardware.

## Risks & fallbacks

- **Real-hardware tuning for A** is the top risk → mitigated by the sim/replay harness being the source of truth; live flight is demoed only if stable.
- **Cactus on-device behavior for C** may be slow/variable → the keyword fallback guarantees voice always works; DronePilot is preferred, not required.
- **Networking (#7)** → recorded demo using the stage setup is the insurance.
- **Interlock interactions (B×A)** → arming state is explicit and shown in the UI so the operator always knows who holds the drone.

## Out of scope

Mavic flight autonomy; VO accuracy/loop-closure; always-on vision; new UI framework; anything that overclaims beyond what the code does.
