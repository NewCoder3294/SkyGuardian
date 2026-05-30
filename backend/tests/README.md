# `tests/` — backend test suite (pytest · Brain)

## Responsibility
Pin the spine, the upload guards, and the SLAM contracts with deterministic, fast
tests. No hardware, no network, no wallclock, no unseeded randomness — every time-
or RNG-dependent path is driven by an injectable [`FakeClock`](../app/clock.py) or a
seeded `np.random.default_rng(...)`, so runs are bit-stable and CI-safe. ✅ 40 tests.

## Run
The repo ships a `.venv` in `backend/`; the canonical invocation is:
```bash
cd backend
.venv/bin/python -m pytest -q                  # 40 tests
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

## Spine + control-plane tests (27)
- `test_contracts.py` ✅ (5) — Contract (de)serialization via
  `parse_client_message`: a valid `intent` parses to `IntentMessage` with the
  right `Command`, `device_location` parses to `DeviceLocation`; an unknown
  `command` and an unknown message `type` are rejected; `Entity.confidence`
  bounds are enforced (>1.0 raises).
- `test_state_machine.py` ✅ (6) — `MissionStateMachine` arbiter:
  `FOLLOW_ME` from idle → `FOLLOWING`, `HOLD` only from following (no-op from
  idle), `STOP`/`RECALL` always-live from any stage, transitions logged with
  `FakeClock` timestamps (event `t` reflects advanced clock), and `fail()`
  records `last_error` and drops to `STOPPED`.
- `test_world_model.py` ✅ (5) — entity lifecycle on `FakeClock`:
  `upsert` admits as `ACTIVE`; entity goes `ACTIVE`→`STALE` past `ttl_s`,
  →`LOST` past the lost window, then GC'd out of the snapshot; producers can't
  force `LOST` (overridden to `ACTIVE` on admit); upsert-by-id refreshes and
  re-activates with a fresh timestamp.
- `test_video.py` ✅ (4) — `make_source` selects a `StreamVideoSource` for
  `url:`/`file:`/`device:N` specs and bare paths, returns a `NullSource` for
  empty/`None`, and rejects a non-integer `device:` spec and an unknown source
  kind. `NullSource` never produces frames and reports `is_streaming is False`.
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

## SLAM tests — `slam/` (13)
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
