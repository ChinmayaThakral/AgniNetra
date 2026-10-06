#!/usr/bin/env python3
"""Add India's national outline, as India draws it, to the Live app's boundary file.

OpenStreetMap draws its boundaries where control runs, so the state outlines stop short in
Jammu and Kashmir and Ladakh, and this extract holds no Arunachal Pradesh at all. Natural
Earth publishes each country's outline from that country's own point of view; India's
covers the whole of Jammu and Kashmir and Ladakh, and Arunachal Pradesh. It is public
domain. The outline is drawn over the state lines, simplified like them to about 0.01
degrees, and it changes no feed: fires are still placed in states from the OSM outlines.

Usage, from the repository root, after extract_districts.py:
    uv run python -m apps.live.pipeline.add_india_outline
"""

import json
import sys
import urllib.request

import duckdb

from ml.paths import DATA_DIR, ROOT

SOURCE_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/"
    "geojson/ne_10m_admin_0_countries_ind.geojson"
)
CACHE = DATA_DIR / "raw" / "naturalearth" / "ne_10m_admin_0_countries_ind.geojson"
OUT = ROOT / "apps" / "live" / "web" / "public" / "data" / "boundaries.json"
TOLERANCE_DEG = 0.01
CREDIT = "National outline: Natural Earth, public domain, India's point of view"


def india_geometry() -> dict:
    if not CACHE.exists():
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(SOURCE_URL, timeout=120) as response:
            CACHE.write_bytes(response.read())
    countries = json.loads(CACHE.read_text())["features"]
    india = [f for f in countries if f["properties"].get("ADM0_A3") == "IND"]
    if len(india) != 1:
        raise ValueError(f"expected one India feature, found {len(india)}")
    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial;")
    simplified = con.execute(
        "SELECT ST_AsGeoJSON(ST_SimplifyPreserveTopology(ST_GeomFromGeoJSON(?), ?))",
        [json.dumps(india[0]["geometry"]), TOLERANCE_DEG],
    ).fetchone()[0]
    geometry = json.loads(simplified)
    rounded = json.loads(json.dumps(geometry), parse_float=lambda v: round(float(v), 4))
    return rounded


def main() -> int:
    data = json.loads(OUT.read_text())
    features = [f for f in data["features"] if f["properties"]["kind"] != "country"]
    features.append(
        {
            "type": "Feature",
            "properties": {"kind": "country", "name": "India"},
            "geometry": india_geometry(),
        }
    )
    attribution = data["attribution"].split(". National outline")[0]
    data["attribution"] = f"{attribution}. {CREDIT}"
    data["features"] = features
    OUT.write_text(json.dumps(data, separators=(",", ":")))
    print(f"{len(features)} features, outline added, {OUT.stat().st_size / 1e6:.2f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
