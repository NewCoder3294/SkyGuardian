"""Best-effort, opt-in capture of field data (collect phase).

Called from the perception loop. Writes sampled frames + an observations JSONL
under captures/<mission_id>/. Pure local disk; no network. Every disk operation
is wrapped so a failure is logged and swallowed — capture must NEVER crash or
block the live perception loop.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import cv2

from ..contracts import DetectionBox, Vec3
from .schema import Detection, Event, Observation


class CaptureRecorder:
    def __init__(
        self,
        *,
        root: Path,
        mission_id: str,
        max_mb: float = 2000.0,
        cadence_s: float = 2.0,
        low_conf: float = 0.4,
        enabled: bool = True,
    ) -> None:
        self._dir = Path(root) / mission_id
        self._mission_id = mission_id
        self._max_bytes = int(max_mb * 1_000_000)
        self._cadence_s = cadence_s
        self._low_conf = low_conf
        self._enabled = enabled
        self._seq = 0
        self._bytes = 0
        self._last_save_t: Optional[float] = None
        self._seen_classes: set[str] = set()
        self._budget_warned = False
        self._dir_ready = False

    @property
    def mission_id(self) -> str:
        return self._mission_id

    def _ensure_dir(self) -> None:
        if not self._dir_ready:
            (self._dir / "frames").mkdir(parents=True, exist_ok=True)
            self._dir_ready = True

    def _reason(self, boxes: list[DetectionBox], t: float) -> Optional[str]:
        """Sampling policy -> why we'd save this frame, or None to skip."""
        if any(b.confidence < self._low_conf for b in boxes):
            return "low_conf"
        if any(b.label not in self._seen_classes for b in boxes):
            return "novel_class"
        if self._last_save_t is None or (t - self._last_save_t) >= self._cadence_s:
            return "cadence"
        return None

    def observe(self, frame_bgr, boxes: list[DetectionBox], pose: Optional[Vec3],
                t: float, *, source: str, image_w: int, image_h: int) -> bool:
        if not self._enabled:
            return False
        try:
            reason = self._reason(boxes, t)
            if reason is None:
                return False
            if self._bytes >= self._max_bytes:
                if not self._budget_warned:
                    print(f"[capture] max_mb reached ({self._max_bytes} B); pausing frame writes")
                    self._budget_warned = True
                return False

            self._ensure_dir()
            rel = f"frames/{self._seq:06d}.jpg"
            ok, buf = cv2.imencode(".jpg", frame_bgr)
            if not ok:
                return False
            (self._dir / rel).write_bytes(buf.tobytes())
            # Advance seq right after the frame lands so a later failure can never
            # reuse this filename and silently overwrite the frame on disk.
            self._seq += 1
            self._bytes += len(buf)

            obs = Observation(
                t=t, mission_id=self._mission_id, frame_path=rel, source=source,
                image_w=image_w, image_h=image_h, pose=pose,
                detections=[
                    Detection(label=b.label, conf=b.confidence,
                              box=[b.cx, b.cy, b.w, b.h]) for b in boxes
                ],
                sampled_reason=reason,
            )
            with (self._dir / "observations.jsonl").open("a") as fh:
                fh.write(json.dumps(obs.model_dump(mode="json")) + "\n")

            self._last_save_t = t
            for b in boxes:
                self._seen_classes.add(b.label)
            return True
        except Exception as exc:  # noqa: BLE001 - capture is best-effort, never fatal
            print(f"[capture] observe failed (ignored): {exc!r}")
            return False

    def record_event(self, event: Event) -> None:
        if not self._enabled:
            return
        try:
            self._ensure_dir()
            with (self._dir / "events.jsonl").open("a") as fh:
                fh.write(json.dumps(event.model_dump(mode="json")) + "\n")
        except Exception as exc:  # noqa: BLE001
            print(f"[capture] record_event failed (ignored): {exc!r}")
