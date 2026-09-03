#!/usr/bin/env python3
"""Phase 3b: attach reference context to every detection and apply the weak labels.

Adds a detection_context table holding, per detection: the state it falls in, the
distance to the nearest catalogued flare, the distance to the nearest OSM
industrial feature, the ESA WorldCover class, and the weak label with its
provenance.

Distances go through the geo macros. Land cover is sampled over the network by
block ordered range reads rather than by downloading 6.6 GB of tiles. D20.

Usage:
    uv run python scripts/build_features_3b.py
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import duckdb

from ml.labels.weak import label_from_distances
from ml.paths import DUCKDB_PATH
from ml.reference.geo import install_geo
from ml.reference.landcover import class_name, group_by_tile, sample_tile_remote

CONTEXT_DDL = """
CREATE OR REPLACE TABLE detection_context (
    detection_id     VARCHAR PRIMARY KEY,
    state_name       VARCHAR,
    flare_m          DOUBLE,
    industrial_m     DOUBLE,
    landcover_code   SMALLINT,
    landcover_class  VARCHAR,
    weak_label       VARCHAR NOT NULL,
    label_source     VARCHAR NOT NULL,
    label_rule       VARCHAR NOT NULL,
    label_confidence DOUBLE NOT NULL
);
"""

# Candidate window for the nearest neighbour prefilter. 0.06 degrees is about
# 6.6 km, wider than any label radius, so no candidate inside a radius is missed.
WINDOW_DEG = 0.06

STATE_SQL = """
CREATE OR REPLACE TEMP TABLE det_state AS
SELECT d.detection_id,
       (SELECT coalesce(nullif(s.name_en, ''), s.name)
          FROM ref_osm_admin s
         WHERE s.admin_level = '4'
           AND ST_Contains(s.geom, ST_Point(d.longitude, d.latitude))
         LIMIT 1) AS state_name
FROM detections d;
"""

DISTANCE_SQL = f"""
CREATE OR REPLACE TEMP TABLE det_dist AS
SELECT d.detection_id, d.longitude, d.latitude,
       (SELECT min(geo_distance_m(d.longitude, d.latitude, f.longitude, f.latitude))
          FROM ref_flares f
         WHERE f.longitude BETWEEN d.longitude - {WINDOW_DEG} AND d.longitude + {WINDOW_DEG}
           AND f.latitude  BETWEEN d.latitude  - {WINDOW_DEG} AND d.latitude  + {WINDOW_DEG}
       ) AS flare_m,
       (SELECT min(geo_distance_m(d.longitude, d.latitude, i.longitude, i.latitude))
          FROM ref_osm_industrial i
         WHERE i.longitude BETWEEN d.longitude - {WINDOW_DEG} AND d.longitude + {WINDOW_DEG}
           AND i.latitude  BETWEEN d.latitude  - {WINDOW_DEG} AND d.latitude  + {WINDOW_DEG}
       ) AS industrial_m
FROM detections d;
"""


def main() -> int:
    con = duckdb.connect(str(DUCKDB_PATH))
    install_geo(con)

    total = int(con.execute("SELECT count(*) FROM detections").fetchone()[0])
    if total == 0:
        print("no detections. Run scripts/backfill_firms.py first.", file=sys.stderr)
        return 2
    print(f"detections: {total}", flush=True)

    print("assigning states by point in polygon", flush=True)
    con.execute(STATE_SQL)
    print("computing nearest flare and nearest industrial distances", flush=True)
    con.execute(DISTANCE_SQL)

    print("sampling ESA WorldCover over the network, block ordered", flush=True)
    rows = con.execute(
        "SELECT detection_id, longitude, latitude FROM detections ORDER BY detection_id"
    ).fetchall()
    ids = [r[0] for r in rows]
    points = [(float(r[1]), float(r[2])) for r in rows]

    # Persisted, not temp, and written one tile at a time. The network sampling is
    # the long pole, so an interruption must not throw away the tiles already done.
    con.execute(
        "CREATE TABLE IF NOT EXISTS det_cover ("
        "detection_id VARCHAR PRIMARY KEY, code SMALLINT, tile VARCHAR NOT NULL)"
    )
    done_tiles = {r[0] for r in con.execute("SELECT DISTINCT tile FROM det_cover").fetchall()}
    if done_tiles:
        print(f"  resuming, {len(done_tiles)} tiles already sampled", flush=True)

    grouped = group_by_tile(points)
    for position, (name, indexes) in enumerate(sorted(grouped.items()), start=1):
        if name in done_tiles:
            print(f"  [{position:3d}/{len(grouped)}] {name} skipped, already done", flush=True)
            continue
        started = time.time()
        subset = [points[i] for i in indexes]
        sampled = sample_tile_remote(name, subset)
        con.executemany(
            "INSERT OR IGNORE INTO det_cover VALUES (?, ?, ?)",
            [(ids[i], code, name) for i, code in zip(indexes, sampled, strict=True)],
        )
        print(
            f"  [{position:3d}/{len(grouped)}] {name} {len(subset):6d} points "
            f"{time.time() - started:5.1f}s",
            flush=True,
        )

    print("applying weak label rules", flush=True)
    joined = con.execute(
        "SELECT d.detection_id, s.state_name, d.flare_m, d.industrial_m, c.code "
        "FROM det_dist d "
        "LEFT JOIN det_state s USING (detection_id) "
        "LEFT JOIN det_cover c USING (detection_id)"
    ).fetchall()

    con.execute(CONTEXT_DDL)
    payload = []
    for detection_id, state_name, flare_m, industrial_m, code in joined:
        cover = class_name(None if code is None else int(code))
        weak = label_from_distances(
            None if flare_m is None else float(flare_m),
            None if industrial_m is None else float(industrial_m),
            cover,
        )
        payload.append(
            (
                detection_id,
                state_name,
                flare_m,
                industrial_m,
                code,
                cover,
                weak.label,
                weak.source,
                weak.rule,
                weak.confidence,
            )
        )
    con.executemany("INSERT INTO detection_context VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", payload)

    written = int(con.execute("SELECT count(*) FROM detection_context").fetchone()[0])
    print(f"\ndetection_context rows: {written}")
    if written != total:
        print(f"MISMATCH: {total} detections but {written} context rows", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
