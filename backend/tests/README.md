# `tests/` — backend test suite (pytest · Brain)

## Responsibility
Pin the spine and SLAM contracts with deterministic, fast tests. No hardware, no
network, no wallclock, no unseeded randomness — every time- or RNG-dependent path
is driven by an injectable [`FakeClock`](../app/clock.py) or a seeded
`np.random.default_rng(...)`, so runs are bit-stable and CI-safe. ✅ 34 tests.

## Run
```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest                  # 34 tests
pytest tests/slam       # just the SLAM geometry/anchor suite
pytest -k state_machine # one file by keyword
```
Config: [`../pytest.ini`](../pytest.ini) sets `testpaths=tests` and
`pythonpath=.` (so `app.*` and `tests.slam.synth` import without install).

## Spine tests
- `test_contracts.py` ✅ — Contract A/B (de)serialization: valid `intent` /
  `device_location` parse to the right model; unknown `command` and unknown
  message `type` are rejected; `Entity.confidence` bounds enforced.
- `test_state_machine.py` ✅ — mission arbiter: `follow_me` from idle, `hold`
  only from following (no-op from idle), `stop`/`recall` always-live from any
  stage, transitions logged with `FakeClock` timestamps, `fail()` records the
  reason and stops.
- `test_world_model.py` ✅ — entity lifecycle on `FakeClock`: admit-as-active,
  active→stale→lost→GC'd across the TTL/lost windows, producers can't force
  `lost` (overridden to active on admit), upsert-by-id refreshes/re-activates.
- `test_video.py` ✅ — `make_source` selects tello/url/mock and falls back to an
  honest `DisabledSource` (never a silent mock) on unset/unknown; sources are
  non-blocking before connect; `MockCameraSource` emits valid JPEG (SOI/EOI) that
  changes over `FakeClock` time; `mjpeg_stream` yields well-formed multipart parts.

## SLAM tests — `slam/`
GPS-less monocular VO + AprilTag metric anchor (see
[`../../docs/SLAM.md`](../../docs/SLAM.md)). Geometry is checked against known
synthetic projections rather than images, so it's exact and deterministic.
- `synth.py` — fixtures, not tests: pinhole `project()` / `in_front()` and a
  seeded `point_cloud()`. Place known 3D points, project through cameras at known
  poses, assert the estimators recover the known geometry.
- `test_anchor.py` ✅ — AprilTag anchor: recover camera centre from a tag
  observation, recover the known VO→metre scale from a tag baseline, zero VO
  baseline raises.
- `test_vo_geometry.py` ✅ — visual odometry geometry: relative pose recovers
  translation direction and rotation, `relative_scale` recovers the baseline
  ratio between two steps, degenerate input raises.
- `test_vo_pipeline_smoke.py` ✅ — full `MonocularVO` image path (ORB on
  generated frames): pipeline runs end-to-end and anchors the gauge at the origin;
  a textureless frame degrades gracefully (pose held, no fabrication, no crash).
- `test_local_map.py` ✅ — `LocalMap`: metric scale applied to camera position,
  origin shifted to the launch point, `to_entities` emits `mavic_cam`/`anchor_tag`/
  landmark entities with plain metric `Vec3` (GPS-less invariant — no lat/lng),
  and `integrate` upserts them into the `WorldModel`.

## Discipline (keep it)
- No `time.time()` / `Date.now()` in tests — inject `FakeClock` and `advance()`.
- No unseeded RNG — always `np.random.default_rng(seed)`.
- Tests import only the module under test plus `tests.slam.synth`; no sockets, no
  device, no recorded media required.
