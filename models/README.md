# `models/` — Local model weights (offline, no cloud)

All inference runs on local hardware. Weights live here, **git-ignored** (large
binaries) — distribute out-of-band among the team. The `.gitignore` excludes
`models/**/*.{pt,pth,onnx,bin}`, so only this README is tracked.

## Owns
Local-only weight files for every model subsystem. Nothing here is fetched from
the network at runtime.

## Expected contents
Drop-in locations for each subsystem's weights. These subdirectories are created
out-of-band when the weights land — only this README is tracked.
- ⬜ `yolo/` — YOLO detection weights (e.g. `yolov8s-world.pt`) for the Mavic
  recon perception path. YOLO detection not started yet
  (`backend/app/perception/`; the `slam/` subpackage there is built).
- ✅ `slam/` — ORB-SLAM3 vocabulary / config for the GPS-less monocular mapping
  subsystem (built, tested). The default pure-Python VO needs no weights; this
  holds the optional ORB-SLAM3 backend's vocabulary. See
  [`../docs/SLAM.md`](../docs/SLAM.md).
- 🟡 `gemma/` — on-device Gemma 3n weights for the mobile voice + vision layer
  (loaded on the phone via Cactus, not the laptop). Framework embedded; model
  download pending. See [`../docs/VOICE.md`](../docs/VOICE.md).

## Rule
No model is fetched from the network at runtime (offline-first). If a weight
isn't present, the subsystem degrades loudly (health = `degraded`) — it never
silently calls out.
