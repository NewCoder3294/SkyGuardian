#!/usr/bin/env bash
# Start the local brain. Binds 0.0.0.0 so both clients can reach it.
# USE_MOCK=1 (default) injects fake entities so the UI works with no hardware.
set -euo pipefail
cd "$(dirname "$0")"
export USE_MOCK="${USE_MOCK:-1}"
export BROADCAST_HZ="${BROADCAST_HZ:-10}"
exec uvicorn app.server:app --host 0.0.0.0 --port 8000 --reload
