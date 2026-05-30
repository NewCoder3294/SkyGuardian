"""WebSocket fan-out hub. Tracks connected clients and broadcasts server
messages to all of them. Transport-agnostic boundary so it can be tested
without a real socket.
"""
from __future__ import annotations

import asyncio
from typing import Protocol

from .contracts import ServerMessage


class Connection(Protocol):
    async def send_json(self, data: dict) -> None: ...


class Hub:
    def __init__(self) -> None:
        self._clients: set[Connection] = set()
        self._lock = asyncio.Lock()

    async def add(self, conn: Connection) -> None:
        async with self._lock:
            self._clients.add(conn)

    async def remove(self, conn: Connection) -> None:
        async with self._lock:
            self._clients.discard(conn)

    @property
    def client_count(self) -> int:
        return len(self._clients)

    async def broadcast(self, message: ServerMessage) -> None:
        """Send to every client concurrently. Drops clients that error on send.

        Fan out with asyncio.gather so one slow/stalled client cannot head-of-line
        block delivery to everyone else (the phone on a lossy link, etc.).
        """
        payload = message.model_dump(mode="json")
        async with self._lock:
            targets = list(self._clients)
        if not targets:
            return
        results = await asyncio.gather(
            *(conn.send_json(payload) for conn in targets),
            return_exceptions=True,
        )
        dead = [conn for conn, res in zip(targets, results) if isinstance(res, Exception)]
        if dead:
            async with self._lock:
                for conn in dead:
                    self._clients.discard(conn)
