# `follow/` — Tello soldier-follow controller (Track 1 · Robotics)

**The make-or-break piece.** Detect the AprilTag worn by the soldier, station-keep
with a PD regulator, and command the Tello. See
[`../../../CLAUDE.md`](../../../CLAUDE.md) and
[`../../../docs/VIDEO.md`](../../../docs/VIDEO.md).

## Responsibility
Detect the soldier-worn AprilTag from the Tello forward camera → bearing + distance →
station-keep with a PD regulator → send RC commands to the Tello. Handle tag loss
(hover/coast) and the `holding` / `recall` / `stopped` mission stages.

## Owns
The follow loop. The **only** Tello connection lives in [`../tello/`](../tello/);
`FollowController` is the only legitimate caller of `TelloClient.send_rc`. Nothing
else commands the Tello.

## Interfaces
- **Reads:** mission stage from [`../state_machine.py`](../state_machine.py)
  (`Stage.IDLE` / `FOLLOWING` / `HOLDING` / `RECALL` / `STOPPED`).
- **Reads:** Tello frames via a `TelloVideoSource` ([`../tello/video.py`](../tello/video.py)),
  consumed as JPEG bytes through `read_jpeg()` — the same FrameSource protocol the
  Mavic source uses.
- **Drives:** the Tello through `TelloClient` ([`../tello/client.py`](../tello/client.py))
  — `send_rc` / `hover` / `land`.
- **Writes:** `soldier` and `tello` entities into the `WorldModel`
  ([`../world_model.py`](../world_model.py)) via `upsert`, `source = EntitySource.FOLLOW`.

## Modules
- `apriltag.py` — detection + bearing/distance estimate. `detect_soldier_tag(...)`
  returns a `TagReading` (`tag_id`, `distance_m`, `bearing_x_norm`, `bearing_y_norm`,
  `centre_px`, `timestamp`) or `None` when no tag is in frame. Built on the shared
  SLAM primitives in [`../perception/slam/anchor.py`](../perception/slam/anchor.py)
  (`detect_tags` via pupil-apriltags `tag36h11`, `tag_camera_pose` via PnP) so the
  follow geometry and the Mavic metric-scale anchor stay consistent.
- `controller.py` — `FollowController`: the async station-keep loop + loss handling.

## `apriltag.py` — detection
- `detect_soldier_tag(frame_bgr, camera, tag_size_m, expected_tag_id, timestamp)`.
  - `camera` is a `CameraModel` (from `slam/types.py`); `FollowController` builds it
    with `CameraModel.from_resolution(img_width, img_height)`.
  - `expected_tag_id` filters to the soldier's badge id; pass `None` (the default in
    the controller) to accept any detected tag during bring-up.
  - `distance_m` is the norm of the camera centre in the tag frame from
    `tag_camera_pose`. `bearing_x_norm` is the horizontal pixel offset of the tag
    centre from the principal point, normalised to `[-1, 1]` (+ve = tag right of
    centre). `bearing_y_norm` is the vertical offset (+ve = tag above centre).
  - Honest about uncertainty: returns `None` if pupil-apriltags is missing
    (`detect_tags` raises `RuntimeError`), no tag is found, the expected id is
    absent, or PnP fails. Never fabricates a reading.

## `controller.py` — `FollowController`
Construct once at startup; call `start()` from the server's startup hook (it schedules
`_run()` as an asyncio task). Constructor wiring:
`FollowController(tello, video, world, mission, clock=None, img_width=960, img_height=720, tag_size_m=0.18, soldier_tag_id=None)`.

Loop (`_run`, paced at `_LOOP_HZ = 15`):
1. `video.read_jpeg()` → decode with cv2 (`cv2`/`numpy` imported lazily; the loop
   returns early if cv2 is absent).
2. `detect_soldier_tag(...)` → optional `TagReading`.
3. On a reading: cache it, clear the loss timer, and emit entities.
4. On no reading: start the tag-loss timer if a prior reading existed.
5. `_drive_tello(reading, now)` — stage-dependent flight commands.

Stage handling (`_drive_tello`):
- `STOPPED` → `land()` if connected; no further commands.
- `HOLDING` → `hover()` (zero RC) to hold position.
- `RECALL` → drive back toward the launch area with a fixed reverse RC
  (`send_rc(0, -_RC_LIMIT // 2, 0, 0)`). With only tag-relative sensing this is an
  approximation; the operator initiates recall when near base.
- `IDLE` → no commands (but detection keeps running so the dashboard still sees the
  soldier).
- `FOLLOWING` with no reading → `hover()` and coast; the state machine trips a fault
  if loss exceeds its window.
- `FOLLOWING` with a reading → PD regulator (below).

PD regulator (FOLLOWING, tag visible):
- Errors: `dist_err = distance_m − _TARGET_DISTANCE_M` (default 1.2 m),
  `bearing_x` (yaw), `bearing_y` (vertical). Derivative uses the clock-supplied `dt`.
- Outputs, each clipped to `±_RC_LIMIT = 35`:
  - `fb` from `_KP_DIST=35` / `_KD_DIST=12`
  - `yaw` from `_KP_YAW=60` / `_KD_YAW=18`
  - `ud` from `_KP_VERT=40` / `_KD_VERT=10`
- Issued as `send_rc(0, fb, ud, yaw)` — lateral (`lr`) held at 0; the soldier is kept
  centred via yaw. Gains are conservative and meant to be tuned on hardware.

Entity emission (`_emit_entities`): upserts `soldier` (`EntityType.SOLDIER`,
`confidence 0.9`, `ttl_s 2.0`) placed forward/lateral/vertical of the Tello from the
tag bearing and distance, and `tello` (`EntityType.DRONE`, `confidence 1.0`,
`ttl_s 2.0`) at `Vec3(0, 0, 1)` (the launch origin, ~1 m up) — only when
`tello.state is TelloState.CONNECTED`.
Both use `source = EntitySource.FOLLOW`. Coordinates are Tello-body-relative for now;
they become globally consistent once Tello video is fed through the main SLAM stack.

The controller does not assume a Tello is connected: `send_rc`/`hover`/`land` are
no-ops when the link is down, no `tello` entity is published, and the state machine
reflects the fault.

## Build notes
- Bind the Tello UDP socket to the Tello WiFi interface IP (not `0.0.0.0`). Handled in
  the Tello client / networking, not here.
- Calibrate the Tello camera once for stable distance estimates; `CameraModel.from_resolution`
  assumes a focal estimate and a centred principal point.
- Use a big tag (15–20 cm; default `tag_size_m = 0.18`), follow close (1–1.5 m).
  AprilTag detection degrades with motion blur on the low-res stream.
- Follow behind + below + offset to dodge downwash and keep line of sight.
- On tag loss: hover and coast, do not drift; the state machine trips a named failure
  on timeout.
