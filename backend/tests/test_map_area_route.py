import asyncio
import json
from pathlib import Path

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app import server
from app.contracts import BuildingsUpdated, MapAreaRequest


class FakeHub:
    def __init__(self):
        self.sent = []

    async def broadcast(self, message):
        self.sent.append(message)


def _payload():
    return {"origin": {"lat": 1.0, "lng": 2.0}, "radius_m": 300, "count": 1,
            "buildings": [{"id": 1, "name": None, "height_m": 6.0, "polygon": [[0, 0], [1, 0], [1, 1]]}]}


def test_map_area_request_rejects_out_of_range():
    with pytest.raises(ValidationError):
        MapAreaRequest(lat=999.0, lng=0.0, radius_m=400)
    with pytest.raises(ValidationError):
        MapAreaRequest(lat=0.0, lng=0.0, radius_m=5)  # below 50 m floor


def test_map_area_success_writes_and_broadcasts(tmp_path: Path, monkeypatch):
    target = tmp_path / "buildings.json"
    fake_hub = FakeHub()
    monkeypatch.setattr(server, "_BUILDINGS_PATH", target)
    monkeypatch.setattr(server, "hub", fake_hub)
    monkeypatch.setattr(server.map_area, "fetch_and_project", lambda lat, lng, r: _payload())
    # Deterministic non-fatal basemap path: force extraction to fail so the test
    # never depends on network access.
    import app.basemap as basemap

    def _no_basemap(*a, **k):
        raise RuntimeError("no network in test")

    monkeypatch.setattr(basemap, "extract_basemap", _no_basemap)

    req = MapAreaRequest(lat=1.0, lng=2.0, radius_m=300)
    result = asyncio.run(server.post_map_area(req, None))

    assert result["origin"] == {"lat": 1.0, "lng": 2.0}
    assert result["radius_m"] == 300 and result["count"] == 1
    # Basemap staging is best-effort and folded into the response; with no
    # network it fails non-fatally (None meta + an error string), and the
    # buildings write/broadcast below still succeed.
    assert "basemap" in result and result["basemap"] is None
    assert result["basemap_error"]
    assert json.loads(target.read_text())["count"] == 1
    assert len(fake_hub.sent) == 1
    msg = fake_hub.sent[0]
    assert isinstance(msg, BuildingsUpdated)
    assert msg.origin.lat == 1.0 and msg.count == 1


def test_map_area_offline_leaves_file_untouched(tmp_path: Path, monkeypatch):
    target = tmp_path / "buildings.json"
    target.write_text(json.dumps({"count": 99, "sentinel": True}))
    fake_hub = FakeHub()
    monkeypatch.setattr(server, "_BUILDINGS_PATH", target)
    monkeypatch.setattr(server, "hub", fake_hub)

    def boom(lat, lng, r):
        raise RuntimeError("All Overpass endpoints failed")

    monkeypatch.setattr(server.map_area, "fetch_and_project", boom)

    req = MapAreaRequest(lat=1.0, lng=2.0, radius_m=300)
    with pytest.raises(HTTPException) as ei:
        asyncio.run(server.post_map_area(req, None))
    assert ei.value.status_code == 503
    assert json.loads(target.read_text())["sentinel"] is True  # unchanged
    assert fake_hub.sent == []


def test_require_operator_rejects_when_key_set(monkeypatch):
    monkeypatch.setattr(server, "_OPERATOR_KEY", "secret")
    with pytest.raises(HTTPException) as ei:
        server._require_operator(x_operator_key="wrong")
    assert ei.value.status_code == 401
