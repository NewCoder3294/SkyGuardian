#!/usr/bin/env bash
# One-process backend that handles BOTH demo paths simultaneously:
#
#   * Live RTMP perception (indoor, judge demo) — uses the light stack:
#     yolov8s for person + backpack, threat yolov8n for gun at conf=0.40, no
#     YOLO-World, imgsz=480, no depth. Smooth, low false-positive rate.
#
#   * Uploaded clip processing (outdoor, pre-recorded demo) — uses the heavy
#     stack via the UPLOAD_* overrides: yolov8l-worldv2 with the full
#     defense vocab + yolov8l COCO + threat detector, imgsz=640. Loaded
#     on-demand inside the upload worker thread and freed when processing
#     completes, so live perception keeps the lightweight stack the whole
#     time.
#
# Operator workflow:
#   1. ./run-indoor.sh                              # this script — that's it.
#   2. Live demo via DJI Fly → rtmp://laptop-ip:1935/live.
#   3. Pre-record outdoor flight → upload via the dashboard UPLOAD button →
#      heavy processing runs once → dashboard plays back the clip.
set -euo pipefail
cd "$(dirname "$0")"
MODELS="$(cd .. && pwd)/models/yolo"
UVICORN="${UVICORN:-./.venv/bin/uvicorn}"
exec env \
  TELLO_DISABLE="${TELLO_DISABLE:-1}" \
  MAVIC_SOURCE="${MAVIC_SOURCE:-url:rtmp://127.0.0.1:1935/live}" \
  YOLO_WEIGHTS=off \
  YOLO_COCO_WEIGHTS="$MODELS/yolov8s.pt" \
  YOLO_COCO_KEEP="person,backpack" \
  YOLO_SPECIALTY_WEIGHTS="$MODELS/threat-yolov8n.pt" \
  YOLO_SPECIALTY_KEEP="gun" \
  YOLO_SPECIALTY_CONF="0.40" \
  YOLO_CONF="0.30" \
  YOLO_IMGSZ="480" \
  DEPTH_MODEL="off" \
  PERCEPTION_FPS="5" \
  UPLOAD_YOLO_WEIGHTS="$MODELS/yolov8l-worldv2.pt" \
  UPLOAD_YOLO_CLASSES="soldier,rifle,handgun,pistol,AK-47,AR-15,assault rifle,firearm,shotgun,knife,machete,helmet,tactical vest,vehicle,ship,vessel,ied,drone,weapon" \
  UPLOAD_YOLO_COCO_WEIGHTS="$MODELS/yolov8l.pt" \
  UPLOAD_YOLO_COCO_KEEP="person,car,truck,motorcycle,bicycle,bus,backpack,boat" \
  UPLOAD_YOLO_SPECIALTY_WEIGHTS="$MODELS/threat-yolov8n.pt" \
  UPLOAD_YOLO_SPECIALTY_KEEP="gun,knife,grenade" \
  UPLOAD_YOLO_SPECIALTY_CONF="0.35" \
  UPLOAD_YOLO_IMGSZ="640" \
  UPLOAD_YOLO_CONF="0.20" \
  ANCHOR_TAG_SIZE_M="${ANCHOR_TAG_SIZE_M:-0.20}" \
  "$UVICORN" app.server:app --host 0.0.0.0 --port 8000
