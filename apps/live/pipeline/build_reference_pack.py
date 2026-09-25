#!/usr/bin/env python3
"""Build the small reference pack the Live feed job reads instead of the database.

The scheduled job runs on a machine without the 490 MB analysis database, so the three
things classification needs are exported once, here, into one committed file:

- OpenStreetMap industrial features and `man_made=flare` features, as points, ODbL.
  Flares come only from OpenStreetMap. Nothing here derives from the EOG catalogue,
  which the app may not expose. D128.
- Global Energy Monitor assets that were built, as points with operating years, CC BY
  4.0. Names and owners are dropped: the app never names a company.
- The share of this project's own past detections that fell on cropland, per 0.1 degree
  cell, from the ESA WorldCover samples. A cell's agricultural confidence is read from
  it. 0.1 degrees is about 11 km, coarser than the 4 km floor the app allows.

Usage:
    uv run python apps/live/pipeline/build_reference_pack.py
"""

import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import duckdb

from ml.paths import DUCKDB_PATH, ROOT
from ml.population import analysis_predicate
from ml.reference.landcover import class_name

OUT = ROOT / "apps" / "live" / "pipeline" / "reference_pack.json"
CELL_DEG = 0.1
CROPLAND_CODE = 40
KEPT_STATUSES = ("operating", "retired", "mothballed")
# The eight persistent sources checked against imagery, D86. Answers are categories from
# the Heat Detective list and never a company name, the app's third rule.
HEATLE_SITES = (
    (84.8440, 23.8075, "Jharkhand", "coal mine"),
    (86.5445, 23.5482, "West Bengal", "steel or iron plant"),
    (78.2230, 17.1467, "Telangana", "steel or iron plant"),
    (84.9481, 23.8386, "Jharkhand", "coal mine"),
    (73.4678, 26.9272, "Rajasthan", "other industry"),
    (77.3627, 15.9160, "Andhra Pradesh", "steel or iron plant"),
    (84.9221, 23.8334, "Jharkhand", "coal mine"),
    (84.9362, 23.8278, "Jharkhand", "coal mine"),
)
# About a kilometre either way, the box a site's detections are counted in.
SITE_HALF_DEG = 0.009


def main() -> int:
    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    osm = con.execute(
        "SELECT round(longitude, 5), round(latitude, 5), tag_value = 'flare' "
        "FROM ref_osm_industrial ORDER BY osm_type, osm_id"
    ).fetchall()
    gem = con.execute(
        f"""
        SELECT round(longitude, 5), round(latitude, 5), sector, start_year, retired_year
        FROM ref_gem_assets
        WHERE split_part(lower(status), ' -', 1) IN {KEPT_STATUSES}
        ORDER BY asset_id
        """
    ).fetchall()
    cells = con.execute(
        f"""
        SELECT floor(d.longitude / {CELL_DEG})::INTEGER AS cx,
               floor(d.latitude / {CELL_DEG})::INTEGER AS cy,
               count(*) AS n,
               avg(CASE WHEN c.code = {CROPLAND_CODE} THEN 1.0 ELSE 0.0 END) AS cropland
        FROM detections d JOIN det_cover c USING (detection_id)
        WHERE {analysis_predicate("d")}
        GROUP BY 1, 2
        ORDER BY 1, 2
        """
    ).fetchall()
    heatle = []
    for lon, lat, state, answer in HEATLE_SITES:
        half_lon = SITE_HALF_DEG / math.cos(math.radians(lat))
        count, night, frp, code = con.execute(
            f"""
            SELECT count(*), avg(CASE WHEN d.daynight = 'N' THEN 1.0 ELSE 0.0 END),
                   median(d.frp), mode(c.code)
            FROM detections d LEFT JOIN det_cover c USING (detection_id)
            WHERE {analysis_predicate("d")}
              AND d.longitude BETWEEN ? AND ? AND d.latitude BETWEEN ? AND ?
            """,
            [lon - half_lon, lon + half_lon, lat - SITE_HALF_DEG, lat + SITE_HALF_DEG],
        ).fetchone()
        heatle.append(
            {
                "centre": [lon, lat],
                "state": state,
                "answer": answer,
                "detections": count,
                "night_share": round(night, 2),
                "median_frp_mw": round(frp, 2),
                "land_cover": class_name(None if code is None else int(code)),
            }
        )
    pack = {
        "cell_deg": CELL_DEG,
        "attribution": [
            "Industrial and flare features (c) OpenStreetMap contributors, ODbL 1.0",
            "Global Energy Monitor trackers, CC BY 4.0",
            "Land cover from ESA WorldCover 10 m 2021 v200, CC BY 4.0",
        ],
        "osm": {
            "industrial": [[lon, lat] for lon, lat, flare in osm if not flare],
            "flare": [[lon, lat] for lon, lat, flare in osm if flare],
        },
        "gem": [[lon, lat, sector, start, retired] for lon, lat, sector, start, retired in gem],
        "cropland": [[cx, cy, n, round(share, 3)] for cx, cy, n, share in cells],
        "heatle": heatle,
    }
    OUT.write_text(json.dumps(pack, separators=(",", ":")) + "\n")
    print(
        f"osm industrial {len(pack['osm']['industrial'])}, osm flare {len(pack['osm']['flare'])}, "
        f"gem {len(gem)}, cropland cells {len(cells)}, {OUT.stat().st_size} bytes"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
