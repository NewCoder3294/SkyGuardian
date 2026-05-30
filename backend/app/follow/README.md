# `follow/` — Tello soldier-follow controller (Track 1 · Robotics)

**The make-or-break piece.** De-risk standalone on Day 1 before the chain depends on it.

## Responsibility
Detect the AprilTag worn by the soldier → station-keep with a PD regulator →
send flight commands to the Tello. Handle tag loss (hover/coast) and `recall`/`stop`.

## Owns
The **only** Tello connection. Nothing else commands the Tello.

## Interfaces
- **Reads:** mission stage from `state_machine` (`following` / `holding` / `recall` / `stopped`).
- **Writes:** `drone` (Tello) and `soldier` entities into the `WorldModel` via `upsert`
  (source = `follow`).

## Build notes (harvested from prior approaches, reimplement fresh)
- Bind the Tello UDP socket to the Tello WiFi interface IP (not 0.0.0.0).
- Calibrate the Tello camera once for stable distance estimates.
- Use a big tag (15–20 cm), follow close (1–1.5 m); AprilTag detection degrades
  with motion blur on the low-res stream.
- Follow behind + below + offset to dodge downwash and keep line of sight.
- On tag loss: hover and coast, do not drift; trip a named failure on timeout.

## Planned modules
- `apriltag.py` — detection + pose (pupil-apriltags / OpenCV).
- `controller.py` — station-keep PD + loss handling.
- `tello_link.py` — thin wrapper over the Tello client in `app/tello/`.
