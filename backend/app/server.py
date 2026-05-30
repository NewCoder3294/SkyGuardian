"""FastAPI app: the local server that is the single source of truth.

Binds 0.0.0.0. Serves one WebSocket endpoint that:
  - broadcasts world_snapshot + mission_state + health at BROADCAST_HZ
  - accepts client intent / device_location, validated against Contract B

Run: uvicorn app.server:app --host 0.0.0.0 --port 8000
(or ./run.sh)
"""
from __future__ import annotations

import asyncio
import contextlib
import os

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from .clock import RealClock
from .video import MJPEG_MEDIA_TYPE, make_source, mjpeg_stream
from .contracts import (
    Command,
    DeviceLocation,
    Health,
    IntentMessage,
    MissionState,
    WorldSnapshot,
    parse_client_message,
)
from .mock_source import MockSource
from .state_machine import MissionStateMachine
from .world_model import WorldModel
from .ws_hub import Hub

BROADCAST_HZ = float(os.environ.get("BROADCAST_HZ", "10"))
USE_MOCK = os.environ.get("USE_MOCK", "1") == "1"

clock = RealClock()
world = WorldModel(clock=clock)
mission = MissionStateMachine(clock=clock)
hub = Hub()
mock = MockSource(world, clock=clock) if USE_MOCK else None

# Video relay sources, selected by env. Real by default — no mock in the path:
#   TELLO_SOURCE=tello (default) | url:<stream> | mock
#   MAVIC_SOURCE=url:<rtsp/http stream> | tello | mock   (unset -> disabled, empty feed)
# phone reads /video/tello (companion view); dashboard reads /video/mavic (recon view).
tello_camera = make_source(os.environ.get("TELLO_SOURCE", "tello"), "TELLO", clock=clock)
mavic_camera = make_source(os.environ.get("MAVIC_SOURCE", ""), "MAVIC", clock=clock)

app = FastAPI(title="Recon & Companion — local brain")


async def _broadcast_loop() -> None:
    interval = 1.0 / BROADCAST_HZ
    while True:
        if mock is not None:
            mock.step()
        now = clock.now()
        await hub.broadcast(WorldSnapshot(entities=world.snapshot(), t=now))
        await hub.broadcast(MissionState(stage=mission.stage.value, last_error=mission.last_error, t=now))
        await hub.broadcast(Health(
            tello="mock" if USE_MOCK else "unknown",
            mavic="mock" if USE_MOCK else "unknown",
            perception="mock" if USE_MOCK else "unknown",
            t=now,
        ))
        await asyncio.sleep(interval)


async def _start_camera(cam, name: str) -> None:
    start = getattr(cam, "start", None)
    if start is None:
        return
    try:
        await asyncio.to_thread(start)  # blocking connect/open off the event loop
        print(f"[video] {name} source connected")
    except Exception as exc:  # honest: log and leave the feed empty until it's up
        print(f"[video] {name} source not available: {exc}")


@app.on_event("startup")
async def _startup() -> None:
    app.state.broadcast_task = asyncio.create_task(_broadcast_loop())
    asyncio.create_task(_start_camera(tello_camera, "tello"))
    asyncio.create_task(_start_camera(mavic_camera, "mavic"))


@app.on_event("shutdown")
async def _shutdown() -> None:
    task = getattr(app.state, "broadcast_task", None)
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "clients": hub.client_count, "stage": mission.stage.value}


@app.get("/video/tello")
async def video_tello() -> StreamingResponse:
    """Tello companion feed, relayed to the phone (MJPEG)."""
    return StreamingResponse(mjpeg_stream(tello_camera), media_type=MJPEG_MEDIA_TYPE)


@app.get("/video/mavic")
async def video_mavic() -> StreamingResponse:
    """Mavic recon feed, relayed to the dashboard (MJPEG)."""
    return StreamingResponse(mjpeg_stream(mavic_camera), media_type=MJPEG_MEDIA_TYPE)


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    await hub.add(ws)
    try:
        while True:
            raw = await ws.receive_json()
            try:
                msg = parse_client_message(raw)
            except (ValidationError, ValueError):
                # Unknown/malformed intent is rejected, never guessed.
                continue
            if isinstance(msg, IntentMessage):
                mission.apply(msg.command)
            elif isinstance(msg, DeviceLocation):
                # Advisory input for follow-me context (wired to follow ctrl later).
                pass
    except WebSocketDisconnect:
        pass
    finally:
        await hub.remove(ws)
