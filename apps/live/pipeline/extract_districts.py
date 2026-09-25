#!/usr/bin/env python3
"""Draw the Live app's map from state and district boundaries, with no tile provider.

The map is the boundaries and nothing else. No street layer means no account, no quota
and no zoom level at which a single field could be found, which is the first rule of
the app enforced by what the map contains rather than by a setting.

OpenStreetMap tags Indian districts as admin_level 5 and sub districts as 6. The report
pipeline extracted 4 and 6 only, so districts are read here from the same snapshot.
Geometry is simplified to about 0.01 degrees, a kilometre, which is far coarser than a
field and fine for a district outline. ODbL, attributed inside the output.

Usage:
    uv run python apps/live/pipeline/extract_districts.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import duckdb
import osmium

from ml.paths import ROOT

PBF = ROOT / "data" / "raw" / "osm" / "india-latest.osm.pbf"
OUT = ROOT / "apps" / "live" / "web" / "public" / "data" / "boundaries.json"
LEVELS = {"4": "state", "5": "district"}
TOLERANCE_DEG = 0.01
ATTRIBUTION = "Boundaries (c) OpenStreetMap contributors, ODbL 1.0, snapshot 2026-09-02"

WKT = osmium.geom.WKTFactory()


def read_areas() -> list[tuple[str, str, str]]:
    areas = []
    processor = osmium.FileProcessor(str(PBF)).with_areas().with_locations()
    for obj in processor:
        if not isinstance(obj, osmium.osm.Area):
            continue
        tags = obj.tags
        if tags.get("boundary") != "administrative" or tags.get("admin_level") not in LEVELS:
            continue
        try:
            geometry = WKT.create_multipolygon(obj)
        except (RuntimeError, osmium.InvalidLocationError):
            continue
        name = tags.get("name:en") or tags.get("name") or ""
        if geometry and name:
            areas.append((LEVELS[tags.get("admin_level")], name, geometry))
    return areas


def main() -> int:
    if not PBF.is_file():
        print(f"BLOCKED: missing extract {PBF}", file=sys.stderr)
        return 2
    areas = read_areas()
    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial;")
    con.execute("CREATE TABLE areas (kind VARCHAR, name VARCHAR, wkt VARCHAR)")
    con.executemany("INSERT INTO areas VALUES (?, ?, ?)", areas)
    rows = con.execute(
        f"""
        SELECT kind, name,
               ST_AsGeoJSON(ST_SimplifyPreserveTopology(ST_GeomFromText(wkt), {TOLERANCE_DEG}))
        FROM areas
        ORDER BY kind, name
        """
    ).fetchall()
    features = [
        {"type": "Feature", "properties": {"kind": kind, "name": name}, "geometry": json.loads(g)}
        for kind, name, g in rows
        if g
    ]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {"type": "FeatureCollection", "attribution": ATTRIBUTION, "features": features},
            separators=(",", ":"),
        )
    )
    counts = {k: sum(1 for f in features if f["properties"]["kind"] == k) for k in LEVELS.values()}
    print(f"{counts}, {OUT.stat().st_size} bytes, written to {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
