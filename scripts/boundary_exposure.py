#!/usr/bin/env python3
"""How many held out rows sit near a state that belongs to a different split.

The three held out groups carry no boundary buffer. Punjab is held out while Haryana
trains, and the detector work in this repository treats the two as one airshed. D92
measured the exposure by hand, on the stored label column that D120 later found stale,
and nothing could regenerate it. This measures it on the label of record so the owner's
decision A, whether to apply a buffer, rests on a number that has a command.

A held out row is exposed at distance r if a state polygon outside its own group lies
within r of it. Distances are in EPSG:7755, a projection designed for India.

Usage:
    uv run python scripts/boundary_exposure.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import duckdb

from ml.documents import provenance_line
from ml.labels.splits import HELD_OUT_GROUPS, assign_fold
from ml.labels.weak import weak_label_sql
from ml.paths import ARTIFACT_DIR, DUCKDB_PATH, ROOT, ensure_dir

BUFFERS_M = (1000, 2000, 5000, 10000)
OUT = ROOT / "docs" / "boundary_exposure.md"
ARTIFACT = ARTIFACT_DIR / "boundary_exposure.json"
PROJECTED = "EPSG:7755"


def main() -> int:
    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    con.execute("LOAD spatial")
    con.execute("CREATE TEMP TABLE state_group (state VARCHAR, grp VARCHAR)")
    con.executemany(
        "INSERT INTO state_group VALUES (?, ?)",
        [(s, g) for g, states in HELD_OUT_GROUPS.items() for s in states],
    )
    # Each state polygon is classified by the split's own definition. assign_fold
    # returns None for a state in no held out group, which the split defines as
    # always trained, so that is a classification rather than a default for missing
    # data. Either name field may carry the state's name. D122.
    polygons = con.execute(
        "SELECT rowid, name_en, name FROM ref_osm_admin WHERE admin_level = '4'"
    ).fetchall()
    labels = []
    for rowid, name_en, name in polygons:
        fold = assign_fold(name_en) if name_en else None
        if fold is None and name:
            fold = assign_fold(name)
        labels.append((rowid, "train" if fold is None else fold))
    con.execute("CREATE TEMP TABLE polygon_group (rid BIGINT, grp VARCHAR)")
    con.executemany("INSERT INTO polygon_group VALUES (?, ?)", labels)
    con.execute(
        f"""
        CREATE TEMP TABLE states AS
        SELECT pg.grp,
               ST_Transform(a.geom, 'EPSG:4326', '{PROJECTED}', always_xy := true) AS g
        FROM ref_osm_admin a JOIN polygon_group pg ON pg.rid = a.rowid
        """
    )
    con.execute(
        f"""
        CREATE TEMP TABLE held AS
        SELECT sg.grp,
               ST_Transform(ST_Point(d.longitude, d.latitude), 'EPSG:4326', '{PROJECTED}',
                            always_xy := true) AS p
        FROM detections d
        JOIN detection_context c USING (detection_id)
        LEFT JOIN detection_gem g USING (detection_id)
        JOIN state_group sg ON sg.state = c.state_name
        WHERE {weak_label_sql("c", "g")} IN ('flare', 'industrial', 'agricultural')
        """
    )
    total = int(con.execute("SELECT count(*) FROM held").fetchone()[0])
    exposed = {}
    for radius in BUFFERS_M:
        n = int(
            con.execute(
                f"""
                SELECT count(*) FROM held h
                WHERE EXISTS (SELECT 1 FROM states s
                              WHERE s.grp <> h.grp AND ST_DWithin(h.p, s.g, {radius}))
                """
            ).fetchone()[0]
        )
        exposed[radius] = n
        print(f"  within {radius:6d} m of a state outside the group: {n} ({n / total:.2%})")

    ARTIFACT.write_text(
        json.dumps(
            {
                "held_out_labelled_rows": total,
                "exposed_by_buffer_m": {str(r): n for r, n in exposed.items()},
                "share_by_buffer_m": {str(r): n / total for r, n in exposed.items()},
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    lines = [
        "# Boundary exposure of the held out groups",
        "",
        "Regenerate: `uv run python scripts/boundary_exposure.py`",
        provenance_line(__file__),
        "",
        f"Held out labelled rows on the label of record: {total}. A row is exposed at a",
        "distance if a state outside its own group lies within that distance of it.",
        "",
        "| Buffer | Exposed rows | Share of held out labelled rows |",
        "|---|---|---|",
        *[f"| {r / 1000:.0f} km | {n} | {n / total:.2%} |" for r, n in exposed.items()],
        "",
        "No buffer is applied. Applying one removes these rows from evaluation and",
        "requires a refit, which moves every published figure, so it is the owner's",
        "decision A. VIIRS geolocation error is commonly quoted near 150 m at nadir and",
        "grows off nadir, so 1 to 2 km is the physically motivated range.",
        "",
    ]
    ensure_dir(OUT.parent)
    OUT.write_text("\n".join(lines))
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
