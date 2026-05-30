# Video Relay

The laptop owns the drone video and re-streams it to clients as **MJPEG over
HTTP**. Clients never connect to a drone directly — they read the laptop's relay.
This honors the single-controller rule (only the laptop commands the Tello) and
keeps everything on the local network (no cloud).

```
[ Tello ] --UDP H.264--> [ laptop: TelloVideoSource ] --MJPEG--> /video/tello --> phone
[ Mavic ] --server stream--> [ laptop: StreamVideoSource ] --MJPEG--> /video/mavic --> dashboard
```

## Endpoints
- `GET /video/tello` — Tello companion feed (the phone).
- `GET /video/mavic` — Mavic recon feed (the dashboard).

Both return `multipart/x-mixed-replace; boundary=frame` — renderable by any
browser, or the app's `MJPEGView`.

## Sources (`backend/app/video.py`)
Selected by env, **real by default — no mock in the path**:

| Spec | Source |
|---|---|
| `tello` (default for `TELLO_SOURCE`) | `TelloVideoSource` — djitellopy: connect + streamon at startup (off the event loop), latest frame non-blocking |
| `url:<RTSP/HTTP/MJPEG>` | `StreamVideoSource` — any OpenCV-openable stream (Mavic) |
| `mock` | `MockCameraSource` — synthetic FPV, **explicit opt-in** for UI dev |
| unset / unknown | `DisabledSource` — honest empty feed (never a fake frame) |

Connection happens in a background thread at startup, so the server stays
responsive and the feed is simply empty until the link is up.

## Run
```bash
USE_MOCK=0 TELLO_SOURCE=tello uvicorn app.server:app --host 0.0.0.0 --port 8011
# verify in any browser:  http://127.0.0.1:8011/video/tello
```

## Notes / next
- Frame read + JPEG encode run via `asyncio.to_thread` to keep the loop free.
- With two laptop interfaces, bind the Tello socket to the Tello WiFi IP (djitellopy
  connects to `192.168.10.1`); see networking notes in `CLAUDE.md`.
- The Tello feed is also the **vision input** for the on-device model (see VOICE.md).
