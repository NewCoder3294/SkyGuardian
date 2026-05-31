#!/usr/bin/env bash
# Outdoor recon: full model set for processing a pre-recorded Mavic clip.
#
# Trade-offs vs run-indoor.sh:
#   * YOLO-World back ON with a defense-relevant vocab. Heavier but covers
#     soldier / vehicle / drone / ship — the long tail you want on a recon
#     overflight.
#   * COCO yolov8l for higher recall on small/far people + vehicles + boats.
#   * Threat detector kept at conf=0.35 — slightly looser than indoor since
#     outdoor scenes have fewer cable-shaped false-positive sources.
#   * imgsz 640 — better recall for distant targets.
#
# Intended workflow: start this backend, upload the recorded outdoor clip via
# the dashboard's UPLOAD button (or POST /video/upload), wait for processing
# to complete, then stop this backend and switch back to run-indoor.sh for
# the live judge demo.
set -euo pipefail
cd "$(dirname "$0")"
MODELS="$(cd .. && pwd)/models/yolo"
UVICORN="${UVICORN:-./.venv/bin/uvicorn}"
exec env \
  TELLO_DISABLE="${TELLO_DISABLE:-1}" \
  MAVIC_SOURCE="${MAVIC_SOURCE:-url:rtmp://127.0.0.1:1935/live}" \
  YOLO_WEIGHTS="$MODELS/yolov8l-worldv2.pt" \
  YOLO_CLASSES="soldier,rifle,handgun,pistol,AK-47,AR-15,assault rifle,firearm,shotgun,knife,machete,helmet,tactical vest,vehicle,ship,vessel,ied,drone,weapon" \
  YOLO_COCO_WEIGHTS="$MODELS/yolov8l.pt" \
  YOLO_COCO_KEEP="person,car,truck,motorcycle,bicycle,bus,backpack,boat" \
  YOLO_SPECIALTY_WEIGHTS="$MODELS/threat-yolov8n.pt" \
  YOLO_SPECIALTY_KEEP="gun,knife,grenade" \
  YOLO_SPECIALTY_CONF="0.35" \
  YOLO_CONF="0.20" \
  YOLO_IMGSZ="640" \
  DEPTH_MODEL="off" \
  PERCEPTION_FPS="5" \
  "$UVICORN" app.server:app --host 0.0.0.0 --port 8000
