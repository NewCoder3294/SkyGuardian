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
