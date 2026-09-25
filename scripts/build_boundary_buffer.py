#!/usr/bin/env python3
"""Flag, for each detection, whether it lies near each held out group's states.

Owner decision A, taken on 2026-09-25: the spatially blocked evaluation gets a
boundary buffer. For each held out group, training rows within BUFFER_M of that
group's states are excluded, so the model cannot learn from fires sitting just
across the border from the states it is tested on. This is the standard buffered
leave region out design. The test sets themselves are unchanged.

Writes table `detection_buffer` with one boolean per group. Distances are measured in
EPSG:7755, a projection designed for India.

Usage:
    uv run python scripts/build_boundary_buffer.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import duckdb

from ml.labels.splits import BUFFER_M, HELD_OUT_GROUPS, assign_fold
from ml.paths import ARTIFACT_DIR, DUCKDB_PATH
from ml.population import analysis_predicate

PROJECTED = "EPSG:7755"
ARTIFACT = ARTIFACT_DIR / "boundary_buffer.json"


def main() -> int:
    con = duckdb.connect(str(DUCKDB_PATH))
    con.execute("LOAD spatial")
    polygons = con.execute(
        "SELECT rowid, name_en, name FROM ref_osm_admin WHERE admin_level = '4'"
    ).fetchall()
    labels = []
    for rowid, name_en, name in polygons:
        fold = assign_fold(name_en) if name_en else None
        if fold is None and name:
            fold = assign_fold(name)
        if fold is not None:
            labels.append((rowid, fold))
    con.execute("CREATE OR REPLACE TEMP TABLE held_polygon (rid BIGINT, grp VARCHAR)")
    con.executemany("INSERT INTO held_polygon VALUES (?, ?)", labels)
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE group_geom AS
        SELECT hp.grp,
               ST_Transform(a.geom, 'EPSG:4326', '{PROJECTED}', always_xy := true) AS g
        FROM ref_osm_admin a JOIN held_polygon hp ON hp.rid = a.rowid
        """
    )
    columns = []
    for group in HELD_OUT_GROUPS:
        states = ", ".join("'" + s.replace("'", "''") + "'" for s in HELD_OUT_GROUPS[group])
        columns.append(
            f"""(c.state_name NOT IN ({states}) AND EXISTS (
                   SELECT 1 FROM group_geom gg
                   WHERE gg.grp = '{group}'
                     AND ST_DWithin(p.pt, gg.g, {BUFFER_M}))) AS near_{group}"""
        )
    con.execute(
        f"""
        CREATE OR REPLACE TABLE detection_buffer AS
        WITH p AS (
            SELECT d.detection_id,
                   ST_Transform(ST_Point(d.longitude, d.latitude), 'EPSG:4326',
                                '{PROJECTED}', always_xy := true) AS pt
            FROM detections d
            WHERE {analysis_predicate("d")}
        )
        SELECT p.detection_id, {", ".join(columns)}
        FROM p JOIN detection_context c USING (detection_id)
        WHERE c.state_name IS NOT NULL
        """
    )
    counts = {
        group: int(
            con.execute(f"SELECT count(*) FROM detection_buffer WHERE near_{group}").fetchone()[0]
        )
        for group in HELD_OUT_GROUPS
    }
    total = int(con.execute("SELECT count(*) FROM detection_buffer").fetchone()[0])
    for group, n in counts.items():
        print(f"  training rows within {BUFFER_M} m of {group}: {n}")
    ARTIFACT.write_text(
        json.dumps({"buffer_m": BUFFER_M, "rows": total, "near": counts}, indent=2) + "\n"
    )
    print(f"detection_buffer: {total} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
