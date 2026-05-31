# Video Sources & Serving

This doc covers the **brain's** video relay: how the laptop ingests the Mavic
and Tello feeds and re-streams them to the dashboard as JPEG over HTTP. The
brain decodes each feed once and serves the latest frame to any number of
clients — it never proxies a raw drone stream. Everything stays on the local
network (no cloud, no internet).

```
[ Tello  ] --UDP H.264 (djitellopy)--> [ laptop: TelloVideoSource  ] --JPEG--> /video/follower.* --> dashboard
[ Mavic  ] --RTMP/HTTP server stream--> [ laptop: StreamVideoSource ] --JPEG--> /video/leader.*   --> dashboard
```

In the dashboard, **leader** = Mavic (manned recon) and **follower** = Tello
(companion). The endpoint names use leader/follower; the source classes are
generic.

> Note on the Tello link: the brain reading Tello frames for relay/perception
> is separate from *controlling* the Tello. In the current build the **phone**
> is the primary Tello controller and reads the Tello's own video stream
> directly over its AP; the laptop's `TelloVideoSource` is the laptop-side feed
> for the dashboard and the backend perception/follow path. Only one Tello
> controller is armed at a time (operating rule, no code interlock) — see
> `CLAUDE.md`. This doc is about the brain's relay, not about who flies the
> drone.

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
| unset / empty (or `None`) | `NullSource` |

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
  restarting the backend. The wrapper's `initial_kind` is derived from the
  `MAVIC_SOURCE` prefix at import: `rtmp` for `url:`, `file` for `file:`,
  `device` for `device:`, else `none` (unset). `initial_label` is the raw
  `MAVIC_SOURCE` string.
- The Tello feed is a `TelloVideoSource` named `tello_camera`, fed by the shared
  `TelloClient`.
- Both are `start()`ed on app startup and `stop()`ped on shutdown (best-effort,
  so a failing stop never blocks releasing the Tello link).

## Control-plane hardening (`backend/app/server.py`)

The brain is a drone control plane, so even on a closed LAN the state-mutating
video endpoints get a CSRF/DoS floor:

- **CORS allowlist** — `CORSMiddleware` is restricted to `DASHBOARD_ORIGINS`
  (default `http://localhost:3000,http://127.0.0.1:3000`, comma-split), not
  `*`, with `allow_methods=["GET","POST"]`. Browsers enforce CORS even on
  streaming responses, so a random page can't read the feeds or drive the POSTs.
- **Operator key** — `_require_operator` gates the POSTs (`/video/source/rtmp`,
  `/video/source/upload`) behind the `X-Operator-Key` header. No-op when
  `OPERATOR_KEY` is unset (local demos stay frictionless); when set, a missing/
  wrong header is **401**.
- **Upload caps** — `MAX_UPLOAD_MB` (default 500; stored as bytes) and a
  video-extension allowlist `_ALLOWED_VIDEO_EXTS` =
  `.mp4 .mov .m4v .avi .mkv .webm`. See the upload endpoint for how these are
  enforced.

## Endpoints

All endpoints are served by the brain on **port 8000** (see `backend/run.sh`).
The video POSTs additionally require the operator key when `OPERATOR_KEY` is set
(above).

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

Both MJPEG endpoints share `_mjpeg_response` / `_mjpeg_stream`. The generator
emits each part as `--frame\r\nContent-Type: image/jpeg\r\n\r\n<jpeg>\r\n`,
skips duplicate payloads (identity compare against the last bytes object), and
sleeps 0.05 s between ticks (~20 Hz cap). It writes no empty preamble part
(which trips browsers that expect a `Content-Type` in every section), and sets
`Cache-Control: no-cache, no-store, must-revalidate` + `Pragma: no-cache`.

### Source state & switching (leader only)
- `GET /video/source` — current leader mode: `{ kind, label, streaming,
  rtmp_default, upload }`. `kind`/`label`/`streaming` come straight from the
  `SwitchableSource` (`kind` ∈ `rtmp` / `file` / `device` / `none`, derived from
  the `MAVIC_SOURCE` prefix at startup and updated by swaps). `rtmp_default` is
  `MAVIC_SOURCE` if set, else `_DEFAULT_RTMP_URL`. `upload` is a copy of the
  upload-status block below.
- `POST /video/source/rtmp` (operator-gated) — swap the leader to the RTMP
  feed: `MAVIC_SOURCE` if set, otherwise the loopback default `_DEFAULT_RTMP_URL`
  (`MAVIC_RTMP_DEFAULT` env, default `url:rtmp://127.0.0.1:1935/live` — a local
  MediaMTX relay). There is no 400 here; with neither env set it still attempts
  the loopback default. Calls `perception.reset()` so the new feed isn't
  anchored against the old feed's landmarks/tags, and clears `_upload_status`
  back to `idle`.
- `POST /video/source/upload` (multipart `file`, operator-gated) — accept a
  pre-recorded clip. Validates + caps it (see guards below), saves it under
  `.context/uploads/` as `<uuid8>-<basename>`, parks the live leader to
  `NullSource` (`kind="file"`, `label=<safe_name>`), calls `perception.reset()`,
  and kicks off `_process_uploaded_file` (runs
  `perception.file_processor.process_video_file` in a worker thread, passing the
  YOLO/depth/COCO-ensemble env knobs and `PERCEPTION_FPS` as `sample_fps`).
  Returns immediately with `{ ok, kind:"file", label, status_url }`; the
  dashboard polls status until ready.
  - **Guards:** **409** if a prior upload is still `uploading`/`processing`;
    **400** if the extension isn't in `_ALLOWED_VIDEO_EXTS`; **413** if the
    streamed size exceeds `MAX_UPLOAD_MB` (`_save_upload_capped` writes in 1 MiB
    chunks and unlinks the partial file on overflow). The `uuid8` prefix means a
    re-upload can't clobber a clip the dashboard is still scrubbing.
- `GET /video/upload/status` — granular processing status (polled by
  `SourceSelector` during an upload). Same shape as the `upload` block in
  `/video/source`: `{ name, state, progress, error, duration_s, frame_count,
  detection_count }`, where `state` ∈ `idle | uploading | processing | ready |
  error` and `progress` is the 0..1 processing fraction.

### Uploaded-file playback
- `GET /video/file/{name}` — serve a previously-uploaded clip as `video/mp4`
  via `FileResponse` (HTTP byte-range support is automatic, so the dashboard's
  `<video>` scrubber can seek). `name` is reduced to its basename
  (`Path(name).name`) before lookup; **404** if missing.
- `GET /video/detections/{name}` — the pre-computed `<name>.detections.json`
  sidecar (per-timestamp detections + entities) used to overlay boxes on native
  playback. Also basename-sanitized; **404** (with a "poll status until ready"
  hint) if the sidecar doesn't exist yet.

#### Why upload runs offline instead of through the live pipeline
YOLO + depth latency (~150 ms/frame) makes real-time HD playback on CPU
infeasible, and the operator needs to scrub arbitrarily, whereas the live path
emits over WebSocket once. So the clip is processed once up front into a sidecar
JSON (`<name>.detections.json` next to the file), and the browser plays the raw
file natively, overlaying detections looked up at `video.currentTime`.

## Run

```bash
# bare (no live feed — leader is NullSource; server still boots cleanly):
backend/run.sh

# with a Mavic stream:
MAVIC_SOURCE=url:rtmp://127.0.0.1:1935/live backend/run.sh
# run.sh execs: uvicorn app.server:app --host 0.0.0.0 --port 8000 --reload

# the dashboard "RTMP" button targets _DEFAULT_RTMP_URL when MAVIC_SOURCE is
# unset — override the loopback default with:
#   MAVIC_RTMP_DEFAULT=url:rtmp://127.0.0.1:1935/live

# verify in any browser:
#   http://127.0.0.1:8000/video/leader.jpg
#   http://127.0.0.1:8000/video/follower.jpg
```

When `OPERATOR_KEY` is set, the source-swap/upload POSTs require an
`X-Operator-Key: <key>` header.

The dashboard runs on a separate port (3000) and derives these HTTP URLs from
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
