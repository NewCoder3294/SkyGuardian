#!/usr/bin/env bash
# Indoor live demo: detect person, backpack, firearm — nothing else.
#
# Stack:
#   * COCO yolov8s for person + backpack (supervised, tight boxes).
#   * Threat yolov8n for "gun" only, at conf=0.40 to suppress the false
#     positives the model fires on cables / electronics at lower thresholds.
#   * YOLO-World is OFF — slow, weak on weapons, no longer carrying its weight
#     once the specialty model handles firearms.
#   * Depth OFF — no Z accuracy needed indoors; frees ~3 GB of MPS memory.
#   * imgsz 480 — ~1.7x faster than 640, no meaningful recall hit for these
#     classes at indoor distances.
#
# Expected: ~3-5 fps perception, boxes stay locked on objects across frames,
# detection log shows only person / backpack / gun.
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
  "$UVICORN" app.server:app --host 0.0.0.0 --port 8000
