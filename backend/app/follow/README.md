# `follow/` — Tello soldier-follow controller (Track 1 · Robotics)

**The make-or-break piece.** Detect the AprilTag worn by the soldier, station-keep
with a PD regulator, and command the Tello. See
[`../../../CLAUDE.md`](../../../CLAUDE.md) and
[`../../../docs/VIDEO.md`](../../../docs/VIDEO.md).

> **Controller role: backend / alternate.** In the current build the **phone is the
> primary Tello controller** — it runs its own on-device follow loop (visual-"me"
> lock by default; an AprilTag designates other targets) and voice control, and
> commands the Tello directly over the Tello AP (`192.168.10.1:8889`). This module
> is the laptop-side `FollowController` (plus the alternate `ApproachController`),
> wired into `server.py` (constructed at module load, `follow.start()` from the
> startup hook). Per CLAUDE.md only **one controller may be armed at a time**, now
> enforced by a **code interlock** — [`arming.py`](./arming.py) `ArmingLock`: every
> laptop controller must hold the exclusive lock before it drives the Tello, and
> arming owner `"phone"` disarms every laptop controller. The lock starts UNHELD
> (laptop disarmed by default); `_route_arming_for_command` in `server.py` transfers
> it to follow/approach based on the resulting mission stage. It backstops — but
> does not replace — the operating rule, since the phone talks to the Tello over its
> own AP outside the lock. "Armed" here means the controller holds the lock and the
> mission stage permits RC — see the no-op behaviour below for how this loop stays
> inert when the link is down or the lock is unheld.

## Responsibility
Detect the soldier-worn AprilTag from the Tello forward camera → bearing + distance →
station-keep with a PD regulator → send RC commands to the Tello. Handle tag loss
(hover/coast) and the `holding` / `recall` / `stopped` mission stages.

## Owns
The follow + approach loops on the **laptop**. The only Tello connection on the
backend lives in [`../tello/`](../tello/); `FollowController` and
`ApproachController` are the backend callers of `TelloClient.send_rc`, and each is
gated by the shared `ArmingLock` (only the lock holder may drive). (The phone has
its own independent Tello link via `TelloCommander` — that is a separate
controller, not this one.)

## Interfaces
- **Reads:** mission stage from [`../state_machine.py`](../state_machine.py)
  (`Stage.IDLE` / `FOLLOWING` / `HOLDING` / `APPROACH` / `RECALL` / `STOPPED`) and
  the shared `ArmingLock` (drives only while it holds the lock).
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
- `arming.py` — `ArmingLock`: the thread-safe single-owner interlock. `acquire`/
  `release`/`can_command(owner)` + a read-only `holder`. Exclusive: a second owner's
  `acquire` returns `False` while another holds it.
- `controller.py` — `FollowController`: the async station-keep loop + loss handling.
- `approach.py` — `ApproachController`: the alternate autonomous approach-and-standoff
  controller (PD over a YOLO target box rather than an AprilTag), phases
  SEEKING → APPROACHING → STANDOFF → ABORT (terminal on `_LOSS_TIMEOUT_S`).
- `target.py` — `TargetReading` + `BoxTargetDetector` (pinhole range from box height)
  + `SyntheticTargetDetector` (scripted readings for tests) feeding the approach loop.

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
`FollowController(tello, video, world, mission, arming, clock=None, owner="follow", img_width=960, img_height=720, tag_size_m=0.18, soldier_tag_id=None)`.

`arming` is the shared `ArmingLock`; the loop fail-closes (returns without driving)
on any tick where it does not hold the lock for `owner`. `server.py` builds it with
the shared `TelloClient` / `TelloVideoSource` / `WorldModel` / `MissionStateMachine`
/ `ArmingLock`, `owner="follow"`, and two env knobs:
- `FOLLOW_TAG_SIZE_M` — physical tag edge length in metres (default `0.18`); must match
  the printed soldier badge for distance to be metric.
- `FOLLOW_TAG_ID` — integer `tag36h11` id of the soldier badge; unset → `soldier_tag_id`
  is `None` and the detector accepts any tag in frame (bring-up mode).

`img_width` / `img_height` keep their constructor defaults (`960×720`); they size the
`CameraModel` used for PnP, so they should match the Tello stream resolution.

Loop (`_run`, paced at `_LOOP_HZ = 15`):
1. `video.read_jpeg()` → decode with cv2 (`cv2`/`numpy` imported lazily; the loop
   returns early if cv2 is absent). `read_jpeg()` is freshness-windowed in
   `TelloVideoSource`, so a frozen/stale stream returns `None` (treated as tag loss).
2. `detect_soldier_tag(...)` → optional `TagReading`.
3. On a reading: cache it, clear the loss timer, and emit entities.
4. On no reading: start the tag-loss timer if a prior reading existed.
5. `_drive_tello(reading, now)` — stage-dependent flight commands.

Stage handling (`_drive_tello`):
- **Arming gate (first):** if `arming.can_command(owner)` is `False`, return
  immediately — fail-closed, no None-guard. A missing/unheld lock means no driving.
- `STOPPED` → `land()` if connected; no further commands.
- `HOLDING` → `hover()` (zero RC) to hold position.
- `RECALL` → **bounded** open-loop recall. With no valid tag reading it `hover()`s
  (mirrors the FOLLOWING tag-lost path — never blind-thrust). With a reading it yaws
  to re-centre the tag and drives backward toward the operator
  (`send_rc(0, -_RC_LIMIT // 2, 0, yaw)`). Total recall time is capped: once
  `_RECALL_MAX_S = 8.0` elapses it calls `mission.fail("recall_timeout")` (→ STOPPED)
  and hovers, so recall can never drive forever. The recall budget is reset whenever
  the stage leaves RECALL.
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
`label "operator"`, `confidence 0.9`, `ttl_s 2.0`) placed forward/lateral/vertical of
the Tello from the tag bearing and distance, and `tello` (`EntityType.DRONE`,
`label "companion"`, `confidence 1.0`, `ttl_s 2.0`) at `Vec3(0, 0, 1)` (the launch
origin, ~1 m up) — only when `tello.state is TelloState.CONNECTED`.
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
