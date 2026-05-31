import math
from app.basemap import bbox_from_radius

def test_bbox_from_radius_centered():
    w, s, e, n = bbox_from_radius(32.8791, -117.2322, 400)
    assert n > 32.8791 and s < 32.8791
    assert e > -117.2322 and w < -117.2322
    half_lat = (n - s) / 2
    assert math.isclose(half_lat, 400 / 111320, rel_tol=0.05)
    half_lng = (e - w) / 2
    assert half_lng > half_lat


from pathlib import Path
from app.basemap import extract_basemap, read_meta

def test_extract_basemap_writes_meta(tmp_path, monkeypatch):
    import app.basemap as bm
    monkeypatch.setattr(bm, "pmtiles_available", lambda: True)
    out = tmp_path / "basemap.pmtiles"
    class P:
        returncode = 0
        stderr = ""
        stdout = ""
    def fake_run(cmd, **kw):
        Path(cmd[3]).write_bytes(b"PMTilesfake")
        return P()
    meta = extract_basemap(32.87, -117.23, 400, out_path=out, runner=fake_run)
    assert out.exists() and meta.staged and meta.bytes > 0
    assert read_meta(out.with_suffix(".meta.json")).origin["lat"] == 32.87
