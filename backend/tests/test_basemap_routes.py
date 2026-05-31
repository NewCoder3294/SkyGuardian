"""Routes that serve / stage the offline basemap (PMTiles, meta, glyphs).

These exercise the basemap HTTP surface added to backend/app/server.py: the
range-capable PMTiles file route, the metadata sidecar route, the traversal-safe
glyph route, and the best-effort basemap staging folded into POST /map/area.
"""
from fastapi.testclient import TestClient

from app.server import app


def test_meta_unstaged():
    c = TestClient(app)
    r = c.get("/map/basemap/meta")
    assert r.status_code == 200 and r.json()["staged"] in (False, True)


def test_pmtiles_404_when_absent(tmp_path, monkeypatch):
    import app.server as srv

    monkeypatch.setattr(srv, "_BASEMAP_PATH", tmp_path / "nope.pmtiles")
    c = TestClient(app)
    assert c.get("/map/basemap.pmtiles").status_code == 404


def test_pmtiles_range_returns_206(tmp_path, monkeypatch):
    import app.server as srv

    staged = tmp_path / "basemap.pmtiles"
    staged.write_bytes(b"PMTILESDATA0123456789")
    monkeypatch.setattr(srv, "_BASEMAP_PATH", staged)
    c = TestClient(app)
    r = c.get("/map/basemap.pmtiles", headers={"Range": "bytes=0-9"})
    assert r.status_code == 206
    assert r.content == b"PMTILESDAT"


def test_glyph_traversal_blocked():
    c = TestClient(app)
    assert c.get("/map/fonts/..%2f..%2fetc/0-255.pbf").status_code in (404, 400)


def test_map_area_returns_basemap_key(tmp_path, monkeypatch):
    """POST /map/area stages the basemap best-effort: it returns a `basemap`
    key (None when extraction can't reach the network) and still 200s because
    the buildings layer is already saved."""
    import app.server as srv

    payload = {
        "origin": {"lat": 1.0, "lng": 2.0},
        "radius_m": 400,
        "count": 0,
        "buildings": [],
    }
    monkeypatch.setattr(srv, "_OPERATOR_KEY", "")  # gate is a no-op when unset
    monkeypatch.setattr(srv.map_area, "fetch_and_project", lambda lat, lng, r: payload)
    monkeypatch.setattr(srv.map_area, "write_buildings", lambda *a, **k: None)
    monkeypatch.setattr(srv, "_BASEMAP_PATH", tmp_path / "basemap.pmtiles")

    async def _noop_broadcast(_msg):
        return None

    monkeypatch.setattr(srv.hub, "broadcast", _noop_broadcast)
    # Force basemap extraction to fail so the request exercises the non-fatal path
    # without any network access.
    import app.basemap as bm

    def _boom(*a, **k):
        raise RuntimeError("no network in test")

    monkeypatch.setattr(bm, "extract_basemap", _boom)

    c = TestClient(app)
    r = c.post("/map/area", json={"lat": 1.0, "lng": 2.0, "radius_m": 400})
    assert r.status_code == 200
    body = r.json()
    assert "basemap" in body
    assert body["basemap"] is None
    assert body["basemap_error"]
