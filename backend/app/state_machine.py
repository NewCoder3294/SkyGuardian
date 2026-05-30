"""Mission state machine + event log (skeleton).

The arbiter between client intent and Tello commands. The follow controller
(Track 1) will subscribe to the resulting stage to drive the Tello. stop/recall
are always-live: honored from ANY stage, highest priority.

Stages: idle -> following -> holding, with recall/stopped reachable from anywhere.
This is intentionally minimal for v1; per-stage timeouts and named failures land
on Day 2/3 as the real chain is wired.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .clock import Clock, RealClock
from .contracts import Command


class Stage(str, Enum):
    IDLE = "idle"
    FOLLOWING = "following"
    HOLDING = "holding"
    RECALL = "recall"
    STOPPED = "stopped"


@dataclass(frozen=True)
class MissionEvent:
    t: float
    from_stage: Stage
    to_stage: Stage
    cause: str  # the command or system reason that triggered the transition


# Allowed transitions for non-priority commands. Priority commands (stop/recall)
# bypass this table entirely.
_NORMAL_TRANSITIONS: dict[Command, dict[Stage, Stage]] = {
    Command.FOLLOW_ME: {
        Stage.IDLE: Stage.FOLLOWING,
        Stage.HOLDING: Stage.FOLLOWING,
        Stage.RECALL: Stage.FOLLOWING,
        Stage.STOPPED: Stage.FOLLOWING,
    },
    Command.HOLD: {
        Stage.FOLLOWING: Stage.HOLDING,
    },
}


class MissionStateMachine:
    def __init__(self, clock: Clock | None = None) -> None:
        self._clock = clock or RealClock()
        self._stage = Stage.IDLE
        self._last_error: str | None = None
        self._log: list[MissionEvent] = []

    @property
    def stage(self) -> Stage:
        return self._stage

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def events(self) -> list[MissionEvent]:
        return list(self._log)

    def _transition(self, to: Stage, cause: str) -> None:
        if to == self._stage:
            return
        self._log.append(
            MissionEvent(t=self._clock.now(), from_stage=self._stage, to_stage=to, cause=cause)
        )
        self._stage = to

    def apply(self, command: Command) -> Stage:
        """Apply an intent. Returns the resulting stage.

        stop/recall are always honored. Other commands only transition when the
        current stage allows it; otherwise they are ignored (no-op, no error).
        """
        if command is Command.STOP:
            self._transition(Stage.STOPPED, cause="stop")
            return self._stage
        if command is Command.RECALL:
            self._transition(Stage.RECALL, cause="recall")
            return self._stage

        target = _NORMAL_TRANSITIONS.get(command, {}).get(self._stage)
        if target is not None:
            self._transition(target, cause=command.value)
        return self._stage

    def fail(self, reason: str) -> None:
        """Record a named failure and drop to a safe stage (stopped)."""
        self._last_error = reason
        self._transition(Stage.STOPPED, cause=f"fail:{reason}")
