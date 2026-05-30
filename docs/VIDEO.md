# Video Sources & Serving

The laptop (the brain) owns all drone video. It re-streams frames to clients as
JPEG over HTTP — never as a raw drone stream. Clients (dashboard, phone) read the
laptop's relay; they never connect to a drone directly. This honors the
single-controller rule (only the laptop commands the Tello) and keeps everything
on the local network (no cloud, no internet).

```
[ Tello  ] --UDP H.264 (djitellopy)--> [ laptop: TelloVideoSource  ] --JPEG--> /video/follower.* --> phone + dashboard
[ Mavic  ] --RTMP/HTTP server stream--> [ laptop: StreamVideoSource ] --JPEG--> /video/leader.*   --> dashboard
```

In the dashboard, **leader** = Mavic (manned recon) and **follower** = Tello
(companion). The endpoint names use leader/follower; the source classes are
generic.

## The FrameSource abstraction (`backend/app/video.py`)

Everything downstream — the perception pipeline, the follow controller, the
HTTP endpoints — consumes a `FrameSource`: anything exposing `start()`,
`stop()`, and `read_jpeg() -> bytes | None`. `read_jpeg()` is non-blocking and
returns the *latest* decoded JPEG (or `None` when nothing is ready). Callers
pace themselves; sources never block them waiting on a frame.

| Class | Role |
|---|---|
| `NullSource` | No-op. `read_jpeg()` always returns `None`. Used when `MAVIC_SOURCE` is unset, and as the parked source while an uploaded file is loaded. |
| `StreamVideoSource` | `cv2.VideoCapture`-backed, with a background reader thread that keeps only the latest decoded frame (drops stale frames). Backs RTMP/HTTP streams, local files, and capture devices. |
| `TelloVideoSource` | Adapts djitellopy's `BackgroundFrameRead` into the same protocol (`backend/app/tello/video.py`). |
| `SwitchableSource` | Hot-swap wrapper. Holds one inner source behind a lock; `replace()` swaps it atomically without rewiring consumers. |

`cv2` is imported lazily inside `StreamVideoSource` and `TelloVideoSource` so the
module stays importable in test environments without OpenCV.

### `make_source(spec)` — building the Mavic source from env

`make_source` parses the `MAVIC_SOURCE` env spec into a concrete source:

| Spec | Result |
|---|---|
| `url:<RTSP/RTMP/HTTP>` | `StreamVideoSource(value)` |
| `file:<path>` | `StreamVideoSource(path)` — local clip (path is `expanduser`'d) |
| `device:<index>` | `StreamVideoSource(int(index))` — local capture device |
| bare path/URL (no `:`) | `StreamVideoSource(spec)` — best-effort stream target |
| unset / empty | `NullSource` |

An unknown `kind:` prefix, or a non-integer `device:` index, raises `ValueError`.

### `is_streaming`

`StreamVideoSource.is_streaming` is `True` only once at least one frame has
actually been decoded — `cv2.VideoCapture` returns a non-`None` object even when
the URL never connects, so "object exists" is not a reliable signal. The reader
only fills `_latest_jpeg` after a successful read+encode. `SwitchableSource`
forwards `is_streaming` to its current inner source; `NullSource` is always
`False`.

## Source wiring (`backend/app/server.py`)

- The Mavic feed is built once at import from `MAVIC_SOURCE` via `make_source`,
  then wrapped in a `SwitchableSource` named `mavic_camera`. The wrapper lets the
  operator hot-swap to an uploaded file (and back to the RTMP feed) without
  restarting the backend.
- The Tello feed is a `TelloVideoSource` named `tello_camera`, fed by the shared
  `TelloClient`.
- Both are `start()`ed on app startup and `stop()`ped on shutdown (best-effort,
  so a failing stop never blocks releasing the Tello link).

## Endpoints

All endpoints are served by the brain on **port 8000** (see `backend/run.sh`).

### Leader (Mavic)
- `GET /video/leader.jpg` — single latest JPEG, `Cache-Control: no-store`.
  Returns **204** when no frame is ready. This is what the dashboard polls
  (~10 Hz); each request completes, so the browser tab never shows a perpetual
  loading spinner.
- `GET /video/leader.mjpg` — legacy `multipart/x-mixed-replace` stream. Kept for
  debugging; the dashboard prefers the polled `.jpg`.

### Follower (Tello)
- `GET /video/follower.jpg` — single latest JPEG, same semantics as the leader
  `.jpg` (204 when no frame).
- `GET /video/follower.mjpg` — legacy multipart stream.

The MJPEG generator (`_mjpeg_stream`) emits each part as
`--frame\r\nContent-Type: image/jpeg\r\n\r\n<jpeg>\r\n`, skips duplicate
payloads, and caps output at ~20 Hz. It writes no empty preamble part (which
trips browsers that expect a `Content-Type` in every section).

### Source state & switching (leader only)
- `GET /video/source` — current leader mode: `{ kind, label, streaming,
  rtmp_default, upload }`, where `kind` is `rtmp` / `file` / `device` / `none`
  (`none` when `MAVIC_SOURCE` was unset at startup; the rest are derived from the
  `MAVIC_SOURCE` prefix) and `upload` is the upload-status block below.
- `POST /video/source/rtmp` — swap the leader back to the env-configured
  `MAVIC_SOURCE`. **400** if no `MAVIC_SOURCE` was set at startup. Resets
  perception/SLAM state so the new feed isn't anchored against the old feed's
  landmarks.
- `POST /video/source/upload` (multipart `file`) — accept a pre-recorded clip.
  Saves it under `.context/uploads/`, parks the live leader to `NullSource`,
  resets perception, and kicks off `_process_uploaded_file` (runs
  `perception.file_processor.process_video_file` in a worker thread). Returns
  immediately; the dashboard polls status until ready.
- `GET /video/upload/status` — granular processing status (polled by
  `SourceSelector` during an upload). Same shape as the `upload` block in
  `/video/source`: `{ name, state, progress, error, duration_s, frame_count,
  detection_count }`, where `state` ∈ `idle | uploading | processing | ready |
  error`.

### Uploaded-file playback
- `GET /video/file/{name}` — serve a previously-uploaded clip as `video/mp4`
  via `FileResponse` (HTTP byte-range support is automatic, so the dashboard's
  `<video>` scrubber can seek). Name is basename-sanitized; **404** if missing.
- `GET /video/detections/{name}` — pre-computed per-timestamp detections +
  entities for an uploaded clip, used to overlay boxes on native playback.

#### Why upload runs offline instead of through the live pipeline
YOLO + depth latency (~150 ms/frame) makes real-time HD playback on CPU
infeasible, and the operator needs to scrub arbitrarily, whereas the live path
emits over WebSocket once. So the clip is processed once up front into a sidecar
JSON (`<name>.detections.json` next to the file), and the browser plays the raw
file natively, overlaying detections looked up at `video.currentTime`.

## Run

```bash
# bare (no live feed — leader is NullSource):
backend/run.sh

# with a Mavic stream:
MAVIC_SOURCE=url:rtmp://localhost:1935/leader backend/run.sh
# run.sh execs: uvicorn app.server:app --host 0.0.0.0 --port 8000 --reload

# verify in any browser:
#   http://127.0.0.1:8000/video/leader.jpg
#   http://127.0.0.1:8000/video/follower.jpg
```

The dashboard runs on a separate port (3001) and derives these HTTP URLs from
its WebSocket URL via `httpFromWs` in `frontend/src/lib/feedUrl.ts`, so it works
against any LAN host.

## Notes

- Frame read + JPEG encode run via `asyncio.to_thread` in the endpoints to keep
  the event loop free.
- `StreamVideoSource` and `TelloVideoSource` each keep only the latest frame, so
  the 5 Hz perception loop never plays catch-up on a 20–30 Hz stream.
- With two laptop interfaces, bind the Tello socket to the Tello WiFi IP
  (djitellopy connects to `192.168.10.1`); see the networking notes in
  `CLAUDE.md`.
- The Tello feed is also the **vision input** for follow-me (AprilTag) — see the
  follow controller, not just video relay.
