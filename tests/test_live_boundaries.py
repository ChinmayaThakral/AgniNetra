"""The Live map carries India's whole outline, as India draws it, beside the OSM lines."""

import json

from ml.paths import ROOT

BOUNDARIES = ROOT / "apps" / "live" / "web" / "public" / "data" / "boundaries.json"


def points(geometry: dict) -> list[list[float]]:
    polygons = (
        [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
    )
    return [p for polygon in polygons for ring in polygon for p in ring]


def test_the_outline_reaches_all_of_jammu_kashmir_ladakh_and_arunachal() -> None:
    data = json.loads(BOUNDARIES.read_text())
    outlines = [f for f in data["features"] if f["properties"]["kind"] == "country"]
    assert len(outlines) == 1
    lons, lats = zip(*points(outlines[0]["geometry"]), strict=True)
    assert max(lats) > 36.9
    assert max(lons) > 97.0
    assert "Natural Earth" in data["attribution"]
