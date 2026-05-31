#!/usr/bin/env bash
# Start the local RTMP relay (MediaMTX) for the Mavic feed.
#
# Publishers (DJI HDMI capture / DJI app / ffmpeg) push to:
#     rtmp://<laptop-lan-ip>:1935/live
# The backend brain reads the loopback side (rtmp://127.0.0.1:1935/live) and
# re-serves JPEG to the dashboard. Everything stays on the local network.
set -euo pipefail
cd "$(dirname "$0")"
exec mediamtx "$(pwd)/mediamtx.yml"
