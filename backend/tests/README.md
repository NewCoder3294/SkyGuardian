# `tests/` — backend test suite (pytest · Brain)

## Responsibility
Pin the spine, the flight-control hardening, the upload guards, the capture
pipeline, and the SLAM contracts with deterministic, fast tests. No hardware, no
network, no wallclock, no unseeded randomness — every time- or RNG-dependent path
is driven by an injectable [`FakeClock`](../app/clock.py) or a seeded
`np.random.default_rng(...)`, so runs are bit-stable and CI-safe. ✅ 187 tests.

## Run
The repo ships a `.venv` in `backend/`; the canonical invocation is:
```bash
cd backend
.venv/bin/python -m pytest -q                  # 187 tests
.venv/bin/python -m pytest -q tests/slam       # just the SLAM geometry/anchor suite
.venv/bin/python -m pytest -q -k state_machine # one file by keyword
```
To build the venv from scratch:
```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt  # pulls requirements.txt + pytest + httpx
```
Config: [`../pytest.ini`](../pytest.ini) sets `testpaths = tests` and
`pythonpath = .` (so `app.*` and `tests.slam.synth` import without an install).

## Spine + control-plane tests
- `test_contracts.py` ✅ (15) — Contract (de)serialization via
  `parse_client_message`: a valid `intent` parses to `IntentMessage` with the
  right `Command`, `device_location` parses to `DeviceLocation`; an unknown
  `command` and an unknown message `type` are rejected; `Entity.confidence`
  bounds and NaN/inf rejection are enforced; `FollowState` (`target_type`/
  `target_label`, bounds), `EntityReport` (≤8 entities, finite), and
  `LabelEvent` round-trip.
- `test_state_machine.py` ✅ (8) — `MissionStateMachine` arbiter:
  `FOLLOW_ME` from idle → `FOLLOWING`, `HOLD` only from following (no-op from
  idle), `APPROACH` transitions, `STOP`/`RECALL` always-live from any stage,
  transitions logged with `FakeClock` timestamps (event `t` reflects advanced
  clock), and `fail()` records `last_error` and drops to `STOPPED`.
- `test_world_model.py` ✅ (6) — entity lifecycle on `FakeClock`:
  `upsert` admits as `ACTIVE`; entity goes `ACTIVE`→`STALE` past `ttl_s`,
  →`LOST` past the lost window, then GC'd out of the snapshot; producers can't
  force `LOST` (overridden to `ACTIVE` on admit); upsert-by-id refreshes and
  re-activates with a fresh timestamp.
- `test_video.py` ✅ (6) — `make_source` selects a `StreamVideoSource` for
  `url:`/`file:`/`device:N` specs and bare paths, returns a `NullSource` for
  empty/`None`, and rejects a non-integer `device:` spec and an unknown source
  kind. `NullSource` never produces frames and reports `is_streaming is False`.
- `test_follow_state.py` ✅ (12) — the relative soldier↔Tello geometry the phone
  reports: inbound `FollowState` parse/store with laptop receipt time + advisory
  `source` overwrite, outbound rebroadcast each tick, and the fail-stale downgrade
  to `phase="stale"` / `active=False` after `_FOLLOW_STALE_S`.
- `test_tello_disable.py` ✅ (2) — `TELLO_DISABLE` gates the laptop Tello stack:
  the Tello client/camera/follow producers are skipped at startup and
  `_tello_health()` reports `"disabled"`.
- `test_label_event.py` ✅ (5) — `LabelEvent` ingest: confirm/reject/correct
  decisions parse and are recorded for the data flywheel.
- `test_map_area.py` ✅ (8) / `test_map_area_route.py` ✅ (4) — OSM buildings
  fetch/projection and the `POST /map/area` route + `buildings_updated` broadcast.
- `test_intel_deep_look.py` ✅ (3) — the `_run_deep_look` helper and the
  `POST /intel/deep-look` route (driven as a coroutine; Ollama not contacted).
- `test_upload_guards.py` ✅ (7) — hardening on the operator video-upload
  control-plane endpoint in `app.server` (see the upload/MJPEG/JPEG routes there).
  The handler is driven directly as a coroutine, so no `python-multipart` and no
  running server are needed and the perception path is never reached — every case
  rejects first. Covers: `_save_upload_capped` aborts and deletes the partial file
  past `max_bytes` but writes a payload under the cap; `_require_operator` is a
  no-op when `_OPERATOR_KEY` is unset and raises `HTTPException(401)` on a
  missing/wrong key when set; and `upload_source_video` rejects a non-video
  extension (`400`), a concurrent upload while the single status slot is
  `processing` (`409`), and an oversize body (`413`, marking `_upload_status` as
  `error`). An autouse fixture repoints `_UPLOADS_DIR` at `tmp_path`, clears
  `_OPERATOR_KEY`, and resets `server._upload_status` around each test so order
  can't leak state.

## Flight-control hardening + arming tests
- `test_arming.py` ✅ (7) — `ArmingLock`: exclusive single-owner acquire/release,
  a second owner's `acquire` returns `False` while held, `can_command` reflects
  the holder, and re-acquire by the same owner is idempotent.
- `test_audit_fixes.py` ✅ (13) — pins the 2026-05-31 deep-audit fixes: bounded
  RECALL (hover on no tag, `mission.fail("recall_timeout")` past `_RECALL_MAX_S`),
  the `TelloVideoSource` freshness window (`read_jpeg()` returns `None` once stale),
  and `_route_arming_for_command` routing on the resulting stage (a rejected
  transition doesn't move the lock; STOPPED disarms every laptop owner).

## Designation tests
- `test_designation.py` ✅ (6) — the pure `Designator.select`: ACTIVE + YOLO +
  high-value filter, confidence-desc ranking with proximity then id tie-breaks,
  and `None` when there's no candidate.
- `test_designation_integration.py` ✅ (2) — `server._apply_designation` against a
  real `WorldModel`: a high-value YOLO detection becomes a `designated_target`
  entity in the tick's snapshot; the prior mark TTL-clears when no candidate.

## Approach-controller tests
- `test_approach.py` ✅ (20) — `target.py` geometry (`TargetReading`,
  `BoxTargetDetector` pinhole range/bearing) and the `ApproachController` PD loop
  phases (SEEKING → APPROACHING → STANDOFF → ABORT).
- `test_approach_wiring.py` ✅ (3) — the `APPROACH` command routes the `ArmingLock`
  to the approach owner via `_route_arming_for_command`.
- `test_approach_sim.py` ✅ (1) — a scripted `SyntheticTargetDetector` drives the
  controller through a full approach with a `FakeClock`.

## Perception integration tests
- `test_pipeline_integration.py` ✅ (4) — the only end-to-end perception test: the
  loop runs across frames with stubbed detectors and upserts entities into a real
  `WorldModel` (the rest of the suite is unit-level).

## Capture / Foundry export tests
- `test_capture_*` ✅ (recorder, schema, pipeline, cleaning, packaging) and
  `test_foundry_export.py` / `test_foundry_isolation.py` — the optional
  `app/capture/` recording + dataset-packaging path (gated by `CAPTURE_ENABLED`).

## SLAM tests — `slam/` (16)
GPS-less monocular VO + AprilTag metric anchor (see
[`../../docs/SLAM.md`](../../docs/SLAM.md)). Geometry is checked against known
synthetic projections rather than images, so it's exact and deterministic.
- `synth.py` — fixtures, not tests: pinhole `project()` / `in_front()` and a
  seeded `point_cloud()`. Place known 3D points, project them through cameras at
  known poses, assert the estimators recover the known geometry.
- `test_anchor.py` ✅ (3) — AprilTag anchor (`app.perception.slam.anchor`):
  `tag_camera_pose` recovers the camera centre from a tag observation,
  `metric_scale_from_tag` recovers the known VO→metre scale from a tag baseline,
  and a zero VO baseline raises.
- `test_vo_geometry.py` ✅ (4) — visual odometry geometry (`app.perception.slam.vo`):
  `estimate_relative_pose` + `integrate_step` recover translation direction and
  rotation, `relative_scale` recovers the baseline ratio between two steps, and
  degenerate input raises.
- `test_vo_pipeline_smoke.py` ✅ (2) — full `MonocularVO.process_sequence` image
  path (ORB on generated frames): the pipeline runs end-to-end and anchors the
  gauge at the origin (frame 0 at position zero, identity rotation); a textureless
  (blank) frame degrades gracefully — pose held at origin, no fabrication, no crash.
- `test_vo_caching.py` ✅ (3) — `MonocularVO`'s feature/pair caches: a re-processed
  window reuses cached ORB features + pair poses (no recompute) and the caches stay
  bounded to the current window so memory doesn't grow with sequence length.
- `test_local_map.py` ✅ (4) — `LocalMap`: metric scale applied to the camera
  position, origin shifted to the launch point, `to_entities` emits
  `mavic_cam`/`anchor_tag`/landmark entities with plain metric `Vec3` (GPS-less
  invariant — no lat/lng fields), and `integrate` upserts them into the
  `WorldModel`.

## Discipline (keep it)
- No `time.time()` / `Date.now()` in tests — inject `FakeClock` and `advance()`.
- No unseeded RNG — always `np.random.default_rng(seed)`.
- Tests import only the module under test plus `tests.slam.synth`; no sockets, no
  device, no recorded media required.
