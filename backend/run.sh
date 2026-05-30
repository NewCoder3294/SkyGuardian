#!/usr/bin/env bash
# Start the local brain. Binds 0.0.0.0 so both clients can reach it.
#
# Optional env (no defaults — server boots cleanly with none of these):
#   MAVIC_SOURCE=url:rtmp://...     # Mavic stream (file:, device:N also OK)
#   YOLO_WEIGHTS=/path/to/yolo.pt   # local weights; SLAM-only without
#   ANCHOR_TAG_SIZE_M=0.20          # AprilTag physical size for metric anchor
#   PERCEPTION_FPS=5                # how fast the perception loop runs
#   FOLLOW_TAG_SIZE_M=0.18          # soldier badge AprilTag size
#   FOLLOW_TAG_ID=42                # filter to a specific tag id
#   TELLO_RETRY_S=3                 # supervisor retry interval
#   BROADCAST_HZ=10                 # WS broadcast cadence
set -euo pipefail
cd "$(dirname "$0")"
exec uvicorn app.server:app --host 0.0.0.0 --port 8000 --reload
