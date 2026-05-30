# `models/` — Local model weights (offline, no cloud)

All inference runs on local hardware. Weights live here, **git-ignored** (large
binaries) — distribute out-of-band among the team.

## Expected contents
- `yolo/` — YOLO detection weights (e.g. `yolov8s-world.pt`) for Mavic recon.
- `slam/` — ORB-SLAM3 vocabulary / config.
- `gemma/` — on-device Gemma weights for the mobile voice layer (lives on the phone via Cactus).

## Rule
No model is fetched from the network at runtime. If a weight isn't here, the
subsystem degrades loudly (health = `degraded`), it does not silently call out.
