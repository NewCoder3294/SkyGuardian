import json
from pathlib import Path

import pytest

from app.map_area import (
    collect_buildings,
    fetch_and_project,
    project_enu,
    write_buildings,
)


def test_project_enu_origin_is_zero():
    assert project_enu(10.0, 20.0, 10.0, 20.0) == (0.0, 0.0)


def test_project_enu_known_offset_at_equator():
    # 0.001 deg east/north at the equator is ~111.32 m for both axes.
    east, north = project_enu(0.001, 0.001, 0.0, 0.0)
    assert abs(east - 111.32) < 0.1
    assert abs(north - 111.32) < 0.1


def test_collect_buildings_projects_one_way():
    overpass = {
        "elements": [
            {
                "type": "way",
                "id": 42,
                "tags": {"building": "yes", "name": "HQ", "building:levels": "2"},
                "geometry": [
                    {"lat": 0.0, "lon": 0.0},
                    {"lat": 0.0, "lon": 0.001},
                    {"lat": 0.001, "lon": 0.001},
                ],
            }
        ]
    }
    out = collect_buildings(overpass, origin_lat=0.0, origin_lng=0.0)
    assert len(out) == 1
    b = out[0]
    assert b["id"] == 42
    assert b["name"] == "HQ"
    assert b["height_m"] == pytest.approx(6.4, abs=0.1)  # 2 levels * 3.2
    assert b["polygon"][0] == [0.0, 0.0]
    assert b["polygon"][1][0] == pytest.approx(111.32, abs=0.1)  # east


def test_write_buildings_backs_up_then_overwrites(tmp_path: Path):
    target = tmp_path / "buildings.json"
    target.write_text(json.dumps({"count": 1, "old": True}))
    write_buildings({"count": 2, "new": True}, target, backup=True)
    assert json.loads(target.read_text())["new"] is True
    bak = target.with_suffix(".json.bak")
    assert json.loads(bak.read_text())["old"] is True


def test_write_buildings_no_backup_when_absent(tmp_path: Path):
    target = tmp_path / "buildings.json"
    write_buildings({"count": 0}, target, backup=True)
    assert json.loads(target.read_text())["count"] == 0
    assert not target.with_suffix(".json.bak").exists()


def test_fetch_and_project_uses_injected_fetcher():
    overpass = {"elements": [{"type": "way", "id": 1, "tags": {"building": "yes"},
                              "geometry": [{"lat": 0.0, "lon": 0.0},
                                           {"lat": 0.0, "lon": 0.001},
                                           {"lat": 0.001, "lon": 0.0}]}]}
    payload = fetch_and_project(1.0, 2.0, 300, _fetcher=lambda q: overpass)
    assert payload["origin"] == {"lat": 1.0, "lng": 2.0}
    assert payload["radius_m"] == 300
    assert payload["count"] == 1
    assert len(payload["buildings"]) == 1
