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
from pydantic import ValidationError

from .clock import RealClock
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


@app.on_event("startup")
async def _startup() -> None:
    app.state.broadcast_task = asyncio.create_task(_broadcast_loop())


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
