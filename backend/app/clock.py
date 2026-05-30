"""Injectable clock so time-dependent logic (entity TTL, broadcast loop) is
deterministic under test. Production code uses RealClock; tests use FakeClock.
"""
from __future__ import annotations

import time
from typing import Protocol


class Clock(Protocol):
    def now(self) -> float:
        """Unix seconds as a float."""
        ...


class RealClock:
    def now(self) -> float:
        return time.time()


class FakeClock:
    """Manually advanced clock for deterministic tests."""

    def __init__(self, start: float = 0.0) -> None:
        self._t = start

    def now(self) -> float:
        return self._t

    def advance(self, seconds: float) -> None:
        self._t += seconds
