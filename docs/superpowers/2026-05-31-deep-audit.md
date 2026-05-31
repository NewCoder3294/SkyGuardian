# SkyGuardian (recon-companion) — Deep Audit

**Date:** 2026-05-31
**Scope:** Python/FastAPI backend (brain), Next.js/TS dashboard, Swift/SwiftUI iOS app (Tello follow/scout).
**Method:** Adversarially verified findings, each backed by quoted `file:line` evidence. Severities reflect the corrected (post-verification) ratings, not the original claims.

---

## Executive summary

All findings below are **confirmed against the source** (high or medium verification confidence). The audit found **no critical issues**. The headline themes are: (1) a high-severity timestamp-domain bug that silently kills the dashboard's alerting and "age" readouts during clip playback, (2) several medium open-loop / state-consistency / freshness gaps on the backend flight-control paths (all mitigated in the default `TELLO_DISABLE=1` phone-flies topology, but real when the laptop controller is armed), (3) one medium iOS data race on shared control state, and (4) a cluster of low-severity correctness/contention/validation gaps.

### Counts by severity

| Severity | Count |
|----------|-------|
| Critical | 0 |
| High     | 1 |
| Medium   | 5 |
| Low      | 6 |
| **Total**| **12** |

### Top 8 to fix first

1. **[HIGH] Playback feeds video-relative timestamps into wall-clock consumers** — `frontend/src/app/operator/page.tsx:119-130` (also `ThreatAlert.tsx:24-27`, `IntelPanel.tsx:124,165-170`, `ConsolePanel.tsx:65-66`). ThreatAlert never fires and all "age"/"visible" readouts break during playback.
2. **[MEDIUM] RECALL drives the Tello open-loop backward with no target/timeout/bearing** — `backend/app/follow/controller.py:159-165`. Flies blind until an operator intervenes or the link drops.
3. **[MEDIUM] Arming lock decoupled from mission stage on rejected transitions** — `backend/app/server.py:397-405` (+ call site `:1129-1131`). APPROACH from IDLE/STOPPED/RECALL hands the lock to "approach" while stage stays put; neither laptop controller drives.
4. **[MEDIUM] TelloVideoSource serves the last decoded JPEG forever — no freshness window** — `backend/app/tello/video.py:54-56,62-64`. A video-only freeze lets the follow loop station-keep on a frozen frame.
5. **[MEDIUM] Data race on `mode` (written main thread, read on detect/rc queues)** — `mobile/Sources/FollowCoordinator.swift:125` (writes `:125,207,222`; reads `:106,143,241`). Stale read can run the wrong target source on an airborne drone.
6. **[MEDIUM] `disarmAndLand`/`emergencyCut` mutate `mode` + `onPixelBuffer` on the caller thread while detect/rc closures are in flight** — `mobile/Sources/FollowCoordinator.swift:199,207,216,222`. Same cross-thread discipline break as #5, on the stop/failsafe path.
7. **[LOW] Designator can promote STALE/LOST detections to DESIGNATED** — `backend/app/server.py:382-394,448-450` + `backend/app/perception/designation.py:51-57`. Operator can see a designated marker on a target perception lost up to 12 s ago.
8. **[LOW] EntityReport from the phone can clobber reserved ids (`tello`/`designated_target`) with unbounded `ttl_s`** — `backend/app/server.py:1100-1114`, `backend/app/contracts.py:60,207-220`.

---

## Backend

### [MEDIUM] RECALL drives the Tello backward open-loop — no target, no timeout, no bearing
- **File:** `backend/app/follow/controller.py:159-165`
- **Confidence:** high
- **Issue:** The RECALL branch sends a constant `self._tello.send_rc(0, -_RC_LIMIT // 2, 0, 0)` (fb = -18) every loop tick at 15 Hz, ignoring all sensing. The comment promises "use bearing to launch in the local frame if available," but the implementation never reads `reading`, has no distance/bearing feedback, no loss-of-tag handling, and no timeout. Unlike the FOLLOWING branch (which hovers when `reading is None`, `controller.py:171-175`), RECALL flies blindly backward indefinitely. There is no auto-exit from RECALL (`state_machine.py` only leaves RECALL via FOLLOW_ME or STOP; `.fail()` is never invoked anywhere in the backend), so a forgotten/garbled RECALL flies the drone backward until it hits something or the link drops. Mitigated by being the normally-disarmed alternate controller (`TELLO_DISABLE=1` default), so it fires only when the laptop is the armed controller.
- **Fix:** Bound the RECALL drive: add a duration/distance timeout that drops to HOLDING or STOPPED, and actually use the last tag bearing as the comment claims. At minimum, hover when there is no valid `reading` instead of issuing open-loop thrust, and cap total RECALL flight time.

### [MEDIUM] APPROACH/STOP/RECALL transfer the arming lock even when the mission transition is rejected
- **File:** `backend/app/server.py:397-405` (call site `:1129-1131`)
- **Confidence:** high
- **Issue:** `_route_arming_for_command()` is called unconditionally right after `mission.apply()` in the WS handler, with no check that the transition actually happened. The router always moves the lock on the **raw** command (`if command is Command.APPROACH: lock.release("follow"); lock.acquire("approach")`), but `state_machine.py` only allows APPROACH from FOLLOWING/HOLDING (`_NORMAL_TRANSITIONS`, `state_machine.py:50-53`). Sending APPROACH while stage is IDLE/STOPPED/RECALL makes `mission.apply()` a no-op (stage unchanged) yet hands the lock to "approach". The approach loop only runs when `mission.stage is Stage.APPROACH` (`server.py:607`), so neither controller drives: follow is disarmed (`can_command("follow")` now false) and approach is gated off by the wrong stage. The system sits in an inconsistent `(lock=approach, stage=IDLE)` state until a later FOLLOW_ME self-heals it. `test_approach_wiring.py` bakes the unconditional behaviour in as expected. Safety impact is mitigated: the lock is consumed only by the two laptop controllers, which are inert under `TELLO_DISABLE=1` (the supported phone-flies topology).
- **Fix:** Gate arming on the actual resulting stage, not the raw command: `new_stage = mission.apply(cmd)` then route by `new_stage` (acquire approach only when `new_stage is APPROACH`, follow only when FOLLOWING/RECALL), and release everything (or acquire a neutral owner) on STOPPED so an emergency stop disarms rather than re-arms the laptop controller.

### [MEDIUM] TelloVideoSource serves the last decoded frame forever — no freshness window
- **File:** `backend/app/tello/video.py:54-56` (reader: `:62-64`)
- **Confidence:** high
- **Issue:** `read_jpeg()` returns the cached `_latest_jpeg` unconditionally with no freshness check. On a dropped link the reader nulls only `_frame_reader` (`video.py:62-64`), never `_latest_jpeg`, so the cached frame stays populated indefinitely. The FollowController consumes this every tick (`controller.py:113`), keeps detecting the tag on a stale frame, and keeps issuing RC. This is exactly the failure mode `StreamVideoSource` was hardened against (`_FRESH_WINDOW_S = 3.0`, `video.py:143-149,180-186`); `TelloVideoSource` has no equivalent guard. The genuinely unguarded path is a **video-only freeze**: the video UDP stream can stall while the command channel still answers `get_battery()`, so `is_connected` stays True (1 Hz heartbeat, `client.py:194-204`), the reader re-encodes djitellopy's retained last frame, the tag is detected on the frozen frame, and `send_rc()` succeeds — the controller station-keeps on a stale frame with no bound. (A clean disconnect *is* backstopped: once the heartbeat flips `is_connected` false, `send_rc` returns without forwarding to the SDK and the Tello firmware auto-hovers, so RC does not literally reach the aircraft "forever" — but the heartbeat-lag and video-freeze windows are real.)
- **Fix:** Mirror `StreamVideoSource`: record `_latest_t = time.monotonic()` on each successful decode and have `read_jpeg()` return `None` once `monotonic() - _latest_t > FRESH_WINDOW`. Also clear `_latest_jpeg = None` when `not self._client.is_connected`. The FollowController already treats `reading is None` as "tag lost -> hover", so this makes a stalled link safe.

### [LOW] Designation runs `world.snapshot()` twice per tick and can promote STALE/LOST detections to DESIGNATED
- **File:** `backend/app/server.py:382-394, 448-450` (+ `backend/app/perception/designation.py:51-57`)
- **Confidence:** high
- **Issue:** In `_broadcast_loop` each tick calls `_apply_designation(now)` then broadcasts `WorldSnapshot(entities=world.snapshot(), ...)`; `_apply_designation` itself calls `world.snapshot()` (`server.py:383`). `world.snapshot()` calls `tick()` (`world_model.py:54-57`), so `tick()` runs twice per broadcast tick (redundant; impact trivial). More substantively, `Designator.select()` filters only on `source == YOLO` and high-value label, with **no status filter**. With default YOLO `ttl_s=3.0` and `lost_factor=3.0`, an entity goes STALE at >3 s, LOST at >9 s, and is GC-dropped at >12 s. So a detection last refreshed up to ~12 s ago — already STALE or LOST — remains an eligible designation candidate and can be promoted to the operator's DESIGNATED target, pinning a stale marker on the maps. (Read-only situational awareness; commands nothing.)
- **Fix:** Take one snapshot per tick and pass it to both designation and the broadcast (`snap = world.snapshot(); _apply_designation(now, snap); broadcast(WorldSnapshot(entities=snap, ...))`). In `Designator.select()`, restrict candidates to `e.status == EntityStatus.ACTIVE`.

### [LOW] Periodic intel loop and on-demand `/intel/deep-look` can run inferences concurrently
- **File:** `backend/app/server.py:775-800, 558-566` (gate at `:538-540`)
- **Confidence:** high
- **Issue:** The periodic loop serializes itself with `_intel_state["running"]` (set/cleared in try/finally around `summarise()`), but `post_deep_look()` never reads or sets that flag — it goes straight to `_run_deep_look(_deep_look_reasoner, ...)`. The deep-look reasoner is a separate `IntelReasoner(with_vision=True)` but POSTs to the same local Ollama (`127.0.0.1:11434`). A vision pass is ~30-120 s. Triggering deep-look mid-loop doubles load/latency on saturated hardware; the loop's guard can't see deep-look either, so both can start during the other. `post_intel_chat()` also bypasses the flag. There is no `asyncio.Lock`/`Semaphore` anywhere — the `running` dict flag is the only serialization. Consequence is latency only (Ollama queues, 180 s timeout gives headroom); no incorrect results.
- **Fix:** Have `post_deep_look()` participate in the same interlock (return-busy when `running` is set; set/clear with try/finally), or serialize all Ollama inference behind a single `asyncio.Lock`/`Semaphore` so the periodic loop, chat, and deep-look never contend.

### [LOW] Stale-frame mismatch between perception boxes (6 s) and the JPEG (3 s) handed to the intel reasoner
- **File:** `backend/app/server.py:551-555`
- **Confidence:** medium
- **Issue:** The intel loop reads `boxes` from `perception.latest_boxes()` (6 s wall-clock staleness window, `pipeline.py:200-205`) and the JPEG from `mavic_camera.read_jpeg()` (3 s monotonic window, `video.py:180-186`) as two independent samples. Since the stream decodes faster than perception samples, the JPEG and the box-source frame are routinely different frames, so the reasoner can be fed a frame/label pair that never co-occurred. (The finding's "docstring guarantee" framing is inaccurate — the reasoner doc describes "latest JPEG + detection labels", i.e. two independently-latest inputs.) Impact is confined to `_intel_summary`, an advisory dashboard string; no flight/arming/world-model path is touched.
- **Fix:** Capture frame and boxes from a single coherent perception snapshot (one API returning JPEG + boxes + shared timestamp), or align the two staleness windows so the frame and labels come from the same perception tick.

---

## Contracts / Validation

### [LOW] EntityReport from the phone can overwrite reserved world-model ids with unbounded TTLs
- **File:** `backend/app/server.py:1100-1114`, `backend/app/contracts.py:60, 207-220`
- **Confidence:** high
- **Issue:** `_apply_entity_report` upserts every client `Entity` verbatim (`world.upsert(entity)`), with no id namespacing, no TTL clamp, and no receipt-time restamping. `EntityReport` validates finiteness and caps the list at 8 but does **not** constrain `entity.id`, and `Entity.ttl_s` is unbounded (`contracts.py:60`, default 5.0, no Field constraint). The world model keys solely on `id` with last-writer-wins and no source/ownership check (`world_model.py:21-24`). A malformed phone payload can upsert `id="tello"` or `id="designated_target"` with an arbitrary position and a huge `ttl_s`, clobbering server/follow-owned markers and pinning a false marker ACTIVE indefinitely. Note: the `id="soldier"` collision is **intended** (the phone's `Localizer.swift:30-34` deliberately emits `soldier` to share the entity), and the legitimate phone path uses `id="drone"`, so only abusive/malformed payloads hit the `tello`/`designated_target` collisions. The "attacker" framing is out of scope per the documented offline single-trusted-peer threat model (`server.py:1106-1111` names namespacing/TTL-clamping as accepted future hardening). FollowState already gets receipt-time restamping (`server.py:1141`); EntityReport does not.
- **Fix:** Namespace phone-reported ids (e.g. prefix `phone:`) so they can't collide with server-owned ids, clamp `ttl_s` to a small server-side max, and replace the client timestamp with `clock.now()` at receipt (apply the same discipline already used for FollowState).

---

## Dashboard

### [HIGH] Playback mode feeds video-relative timestamps into wall-clock consumers — breaks ThreatAlert, "visible" dot, and all "age" readouts
- **File:** `frontend/src/app/operator/page.tsx:119-130` (and `:132-144`)
- **Confidence:** high
- **Issue:** In playback the detection layer/log are built with the frame's video-relative time (`t: f.t`), where `PlaybackFrame.t` is "seconds from video start" (`playback.ts:25`) — a small value like ~12.5. These flow through `effectiveDetections`/`effectiveDetectionLog` into ThreatAlert (`page.tsx:242`), IntelPanel (`:326`), and ConsolePanel (`:273`). All consumers assume unix-epoch seconds (correct for the live path, where `pipeline.py:263-264` stamps with `time.time()`≈1.7e9):
  - `ThreatAlert.tsx:24-27`: `const now = Date.now()/1000; ... if (now - layer.t > 2) continue;` → with `layer.t≈12.5`, `now - layer.t ≈ 1.7e9 >> 2`, so **every** layer is skipped and ThreatAlert **never fires during clip playback** (its sole purpose nullified).
  - `IntelPanel.tsx:124`: same comparison → `visibleNow` always empty (no live dot, `activeThreats`=0, degraded sort).
  - `IntelPanel.tsx:165-170` `fmtAge`: `Date.now()/1000 - t` → garbage ages (millions of minutes).
  - `ConsolePanel.tsx:65-66` `fmtTime`: `new Date(f.t*1000)` with `f.t≈12.5` → renders `1970-01-01 00:00:12`.

  Box rendering is unaffected; only staleness/age/alert metadata is corrupted, and only in the VOD/playback path (live RTMP is correct). Silent failure with no error/warning. Bounded to the secondary playback path, which is the only reason this isn't critical.
- **Fix:** Normalize the timestamp domain before these components see it. Either (a) when synthesizing the playback `DetectionLayer`/`DetectionEvent`, convert frame time to an absolute epoch reference (e.g. `Date.now()/1000` for the current frame so "visible now" is true), or (b) thread an `isPlayback`/`mode` flag into ThreatAlert/IntelPanel so the staleness/age math uses playhead-relative time. ThreatAlert in playback should fire for the current frame's boxes regardless of the 2 s wall-clock window.

### [LOW] 3D map does not render the `designated_target` reticle that the 2D map does
- **File:** `frontend/src/components/LocalMap3D.tsx:148-171`
- **Confidence:** high
- **Issue:** `LocalMap2D` special-cases the designated recon target (`LocalMap2D.tsx:489` `const isDesignated = e.id === "designated_target"; ... if (isDesignated) drawDesignationReticle(...)`, plus an un-truncated red callout). `LocalMap3D.EntityMarker` has no equivalent branch — it renders purely by `entity.type` via `renderShape`, so the `POI`-typed designated target gets the generic amber torus + amber label. Both maps render from the same `effectiveOpEntities` array and the operator can toggle 2D/3D (`MapViewToggle`), so the same snapshot shows a prominent red reticle in 2D and an ordinary amber glyph in 3D — the operator loses the "which one is the designated target" cue exactly when they pan into 3D. (Read-only awareness, not targeting.)
- **Fix:** In `LocalMap3D.EntityMarker`, detect `entity.id === "designated_target"` and render an analogous reticle (red ring/torus + red label). Factor the id check into a shared helper so 2D and 3D stay in sync.

### [LOW] IntelPanel `seenCount` counts every box occurrence, so "times seen" inflates with crowd size
- **File:** `frontend/src/components/IntelPanel.tsx:111-119`
- **Confidence:** high
- **Issue:** `buildBoard` increments the per-label counter once per **box** (`for (const b of ev.boxes) { ... n: prev.n + 1 }`), not once per frame/sighting. The column is headed "Seen" and documented "total times seen this session" (`:13-17`). A single frame with 3 `person` boxes adds 3, a frame with 1 person adds 1, so the count conflates "frames a class appeared in" with "total instance count" and varies with crowd size rather than sighting frequency. (Deterministic for a given log — the title's "non-deterministic" wording is loose; effect is display + a tiebreak sort only, no functional consequence.)
- **Fix:** Decide the intended semantic. For distinct sightings/frames, dedupe per event: `const labelsInFrame = new Set(ev.boxes.map(b => b.label.toLowerCase())); for (const key of labelsInFrame) { ... n: prev.n + 1 ... }`. If instance count is intended, rename the column/doc to "instances".

---

## Mobile / Flight (iOS)

### [MEDIUM] Data race on `mode` — written on main thread, read on detectQueue and rcQueue without synchronization
- **File:** `mobile/Sources/FollowCoordinator.swift:125` (writes `:125, 207, 222`; reads `:106, 143, 241`)
- **Confidence:** high
- **Issue:** `mode` (`:38` plain `var`) is written on the calling/main thread (`armTrack:125 mode = .track`, `disarmAndLand:207`, `emergencyCut:222`) but read on `detectQueue` in `ingest` (`:241 if self.mode == .track`) and on `rcQueue` inside the takeoff-settle closures (`:106, :143`). The class is otherwise meticulous about confining control state to `rcQueue` (`:51` "Control state — only touched on rcQueue", `:200` "rcTimer + control state are rcQueue-owned") — `mode` is the lone exception, violating the file's own stated invariant. There's no happens-before edge between the main-thread writes and the background reads, so this is a genuine data race (TSan would flag it): a stale read on the detect queue means a track-mode arm can run the AprilTag detector path (or vice-versa) for an indeterminate window — wrong target source feeding the live RC loop on an airborne drone. Also `arm()` (`:81`) never resets `mode`, so it inherits the prior value. (Downgraded high→medium: a single-word enum won't tear on ARM64, so the realistic failure is a stale read, not corruption; and in `armTrack` the `:125` write precedes wiring `onPixelBuffer` at `:127`, shrinking the wrong-path window.)
- **Fix:** Confine `mode` to a single queue like the rest of control state — set it inside `rcQueue.async` in `armTrack`/`disarmAndLand`/`emergencyCut`, and read it only on `rcQueue` (have `ingest` capture a mode snapshot via rcQueue), or guard every access with `detLock`. Do **not** leave it as a plain cross-thread `var`. Also reset `mode` in `arm()`.

### [MEDIUM] `disarmAndLand` / `emergencyCut` mutate `mode` and `stream.onPixelBuffer` on the caller thread while detect/rc closures may still be in flight
- **File:** `mobile/Sources/FollowCoordinator.swift:199, 207, 216, 222`
- **Confidence:** high (same code path as the `mode` race, confirmed)
- **Issue:** Both stop paths null `stream?.onPixelBuffer` and set `mode = .tag` on the **caller thread**, outside the `rcQueue.async` block that owns the rest of the control-state teardown (`disarmAndLand:199-211`, `emergencyCut:216-226`). `mode = .tag` at `:207`/`:222` sits outside the `rcQueue.async` at `:200-204`/`:217-220`, and the `onPixelBuffer = nil` happens before that block runs. Meanwhile a previously-dispatched `ingest` detect closure (reading `mode` on `detectQueue`, `:241`) or an rcQueue settle closure (`:106,143`) may still be in flight, so the failsafe/stop path races the very state it is trying to tear down — the same cross-thread discipline break as the `mode` race, but on the safety-critical land/cut path.
- **Fix:** Perform all teardown (including `mode = .tag` and clearing `onPixelBuffer`) inside the single owning `rcQueue.async` block, ordered after timer cancellation, so the stop/failsafe sequence is serialized with respect to in-flight detect/rc work. Pair this with the `mode`-confinement fix above.

---

## Stale / Dead items to remove

- [ ] **`test_approach_wiring.py`** — currently asserts the **unconditional** arming-lock routing as expected behaviour (`server.py:397-405`). Update (do not just delete) once arming is gated on the resulting stage, so the test pins the corrected behaviour instead of the bug.
- [ ] **`.fail()` transition in `state_machine.py`** — referenced as an exit from RECALL but **never invoked anywhere** in the backend (grep returned zero call sites). Either wire it (e.g. as the RECALL timeout target from the fix above) or remove the dead transition so the state machine reflects reachable states.
- [ ] **Comment vs. implementation drift in RECALL** (`controller.py:160-163`) — the "use bearing to launch in the local frame if available" comment describes behaviour the code does not implement. Remove or implement; do not leave an aspirational comment on a live-flight branch.

## Docs to update / add

- [ ] **`docs/DEMO.md` / `CLAUDE.md`** — document that the playback/VOD dashboard path uses video-relative timestamps and that ThreatAlert + age/visible readouts are live-RTMP-only until the High finding is fixed (or, preferably, fix it and note parity).
- [ ] **`CLAUDE.md` "One Tello controller armed at a time"** — note that several backend flight defects (RECALL open-loop, arming-lock decoupling, stale-frame follow) are latent and only reachable when the laptop FollowController is the armed controller (`TELLO_DISABLE=0`); the default dual-live demo (`TELLO_DISABLE=1`) keeps them inert. This is the operating-rule context that bounds their severity.
- [ ] **`backend` freshness contract** — document the freshness-window discipline (`StreamVideoSource` has `_FRESH_WINDOW_S`; `TelloVideoSource` does not yet) so the asymmetry is visible to future maintainers, and record the 6 s (boxes) vs 3 s (JPEG) window mismatch consumed by the intel reasoner.
- [ ] **Ollama serialization** — document that the periodic intel loop, deep-look, and chat all share one local Ollama with only the `_intel_state["running"]` flag as serialization (and that deep-look/chat bypass it), pending a shared lock/semaphore.
- [ ] **EntityReport id/TTL policy** — document the offline single-trusted-peer threat model and the accepted future hardening (id namespacing, server-side `ttl_s` clamp, receipt-time restamping) so the unbounded-`ttl_s` / reserved-id collision gap is a tracked decision, not a silent hole.
- [ ] **`mobile/Sources/FollowCoordinator.swift`** — the "Control state — only touched on rcQueue" invariant (`:51`, `:200`) is violated by `mode`; once fixed, keep the invariant comment accurate (and note `arm()` resets `mode`).
