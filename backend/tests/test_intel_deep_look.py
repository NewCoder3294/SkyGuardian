"""TDD tests for _run_deep_look helper and POST /intel/deep-look endpoint.

Task A covers the pure helper; Task B covers the FastAPI route exercised via
TestClient without the lifespan startup (so no Ollama, no camera, no YOLO).
"""
import asyncio

import pytest
from app.reasoning.intel import IntelSummary
from app import server


class _StubReasoner:
    def __init__(self): self.calls = []

    async def summarise(self, jpeg, labels):
        self.calls.append((jpeg, list(labels)))
        return IntelSummary(
            text="vehicle approaching from the north",
            threat_level="med",
            labels_seen=sorted(set(labels)),
            t=123.0,
            model="gemma3:4b",
            latency_ms=42.0,
        )


# ---------------------------------------------------------------------------
# Task A — pure helper _run_deep_look
# ---------------------------------------------------------------------------

def test_deep_look_runs_one_vision_summary_over_current_frame():
    reasoner = _StubReasoner()
    jpeg = b"\xff\xd8fakejpeg\xff\xd9"
    summary = asyncio.run(server._run_deep_look(reasoner, jpeg, ["vehicle", "person"]))
    assert summary.threat_level == "med"
    assert reasoner.calls == [(jpeg, ["vehicle", "person"])]


def test_deep_look_without_a_frame_returns_an_error_summary():
    reasoner = _StubReasoner()
    summary = asyncio.run(server._run_deep_look(reasoner, None, ["person"]))
    assert "no frame" in summary.text.lower()
    assert reasoner.calls == []


# ---------------------------------------------------------------------------
# Task B — POST /intel/deep-look endpoint
# ---------------------------------------------------------------------------

from fastapi.testclient import TestClient


def test_deep_look_endpoint_returns_summary(monkeypatch):
    reasoner = _StubReasoner()
    monkeypatch.setattr(server, "_deep_look_reasoner", reasoner, raising=False)
    monkeypatch.setattr(server.mavic_camera, "read_jpeg", lambda: b"\xff\xd8x\xff\xd9")
    monkeypatch.setattr(
        server.perception,
        "latest_boxes",
        lambda: ([type("B", (), {"label": "person"})()], 640, 480, 1.0),
    )
    client = TestClient(server.app)
    res = client.post("/intel/deep-look")
    assert res.status_code == 200
    assert res.json()["summary"]["threat_level"] == "med"
