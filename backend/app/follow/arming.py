"""Software arming interlock for the Tello.

Only one laptop-side controller (follow OR approach) may command the drone at a
time. Every controller must hold the lock before it drives the Tello; the lock
is exclusive. This is the code interlock that was previously only an operating
rule. (The phone commands the Tello directly over its own AP and is represented
here as the owner "phone" — arming "phone" disarms every laptop controller.)
"""
from __future__ import annotations

import threading
from typing import Optional


class ArmingLock:
    def __init__(self) -> None:
        self._holder: Optional[str] = None
        self._mu = threading.Lock()

    @property
    def holder(self) -> Optional[str]:
        return self._holder

    def acquire(self, owner: str) -> bool:
        with self._mu:
            if self._holder is None or self._holder == owner:
                self._holder = owner
                return True
            return False

    def release(self, owner: str) -> bool:
        with self._mu:
            if self._holder == owner:
                self._holder = None
                return True
            return False

    def can_command(self, owner: str) -> bool:
        return self._holder == owner
