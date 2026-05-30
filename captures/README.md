# `captures/` — Recorded media for hardware-free dev (git-ignored)

Recorded Mavic clips (and Tello frames with an AprilTag in view) so perception
and the follow controller can be developed and replayed without live drones.

Only this README is tracked. Video files are git-ignored by extension
(`captures/**/*.mp4`, `*.mov`, `*.avi` — see [`.gitignore`](../.gitignore)),
so drop recordings here and share them out-of-band. Keep clips short and
representative.

Suggested layout (create as needed):

- `mavic/` — recorded recon video for YOLO + SLAM dev. Feeds the perception
  stack ([`backend/app/perception/`](../backend/app/perception/),
  [`docs/SLAM.md`](../docs/SLAM.md)).
- `tello/` — recorded Tello frames with an AprilTag in view, for follow tuning
  ([`backend/app/follow/`](../backend/app/follow/)).

## How clips here get consumed

A clip in `captures/` is a plain file path. Two paths read it; neither path
writes anything back into `captures/`.

**1. As the live Mavic source (`MAVIC_SOURCE=file:...`).**
Point the brain at a clip instead of an RTMP/device feed. `backend/run.sh`
`cd`s into `backend/` before launching uvicorn, so a relative `file:` path is
resolved against `backend/` — use an absolute path or `../captures/...`:

```
MAVIC_SOURCE=file:../captures/mavic/clip.mp4 backend/run.sh
```

`video.make_source` parses the `file:` spec (`Path(value).expanduser()`) and
builds a `StreamVideoSource` (cv2.VideoCapture-backed, background reader
thread). The perception loop then samples it at `PERCEPTION_FPS` (default
5 Hz) exactly as it would a live stream, running SLAM + YOLO and upserting
entities into the world model — so a recorded clip drives the dashboard like a
real Mavic feed. Unset `MAVIC_SOURCE` yields a `NullSource` (idle, no frames).
See [`backend/app/video.py`](../backend/app/video.py) and
[`backend/app/server.py`](../backend/app/server.py).

**2. As SLAM-test input (`scripts/run_slam_video.py`).**
Offline, GPS-less monocular mapping over a recorded clip, no server required:

```
python scripts/run_slam_video.py captures/mavic/clip.mp4 [--fps 8] [--tag-size 0.20]
```

It samples frames, runs the VO + AprilTag-anchor pipeline, and prints the
resulting trajectory/entities. See
[`scripts/run_slam_video.py`](../scripts/run_slam_video.py).

## Not this directory: dashboard "Upload video"

The dashboard's upload button (`POST /video/source/upload`) does **not** use
`captures/`. Uploaded clips and their sidecar detection JSON are written under
`.context/uploads/` (also git-ignored) and processed once by
`perception.file_processor.process_video_file` into a time-indexed JSON the
browser scrubs over. `captures/` is for clips you stage manually for the two
paths above.
