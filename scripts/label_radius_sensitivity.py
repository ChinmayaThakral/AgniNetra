#!/usr/bin/env python3
"""Radius sensitivity for the weak label rules, measured before any detection exists.

The two radii in ml/labels/weak.py are the only tuned numbers in the labelling
path, and a tuned number that has never had its sensitivity reported is the shape
of the 2 km clip threshold that hid 11 orphan features. This measures them now,
against the real reference layers, rather than after the labels are built.

What this is not. The probe points are drawn uniformly inside Indian state
polygons. Detections are not uniform, they cluster in burning and industrial
areas, so the labelled shares here are a background rate and are a lower bound on
the real labelled share. This measures the spatial reach of the reference layers,
not the expected label distribution. That distribution needs phase 1b.

Usage:
    uv run python scripts/label_radius_sensitivity.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import duckdb

from ml.documents import provenance_line
from ml.labels.weak import FLARE_RADIUS_M, INDUSTRIAL_RADIUS_M
from ml.paths import ARTIFACT_DIR, DUCKDB_PATH, ROOT, ensure_dir
from ml.reference.geo import install_geo

OUT = ROOT / "docs" / "label_radius_sensitivity.md"
SEED = 20260904
PROBE_COUNT = 4000

# Candidate window for the nearest neighbour search. 0.06 degrees is about 6.6 km
# at Indian latitudes, comfortably wider than the largest radius tested, so no
# candidate inside a tested radius is missed by the prefilter.
WINDOW_DEG = 0.06

ARTIFACT = ARTIFACT_DIR / "label_background.json"
RADII_M = (100.0, 250.0, 500.0, 1000.0, 2000.0, 5000.0)

# Ordered by the generation index for the reason recorded in
# scripts/landcover_background.py: the LIMIT sits over a filtered result and the
# ordering makes reproducibility a guarantee rather than a property of the current
# planner. Verified to select the identical sample. D77.
PROBES_SQL = f"""
CREATE OR REPLACE TEMP TABLE probes AS
WITH box AS (
    SELECT 68.0 AS w, 6.5 AS s, 97.5 AS e, 37.5 AS n
),
candidates AS (
    SELECT r.range AS i,
           w + (e - w) * random() AS lon,
           s + (n - s) * random() AS lat
    FROM box, range(0, {PROBE_COUNT * 6}) r
)
SELECT c.lon, c.lat
FROM candidates c
WHERE EXISTS (
    SELECT 1 FROM ref_osm_admin a
    WHERE a.admin_level = '4' AND ST_Contains(a.geom, ST_Point(c.lon, c.lat))
)
ORDER BY c.i
LIMIT {PROBE_COUNT};
"""

NEAREST_SQL = """
SELECT p.lon, p.lat,
       (SELECT min(geo_distance_m(p.lon, p.lat, f.longitude, f.latitude))
          FROM ref_flares f
         WHERE f.longitude BETWEEN p.lon - {w} AND p.lon + {w}
           AND f.latitude  BETWEEN p.lat - {w} AND p.lat + {w}) AS flare_m,
       (SELECT min(geo_distance_m(p.lon, p.lat, i.longitude, i.latitude))
          FROM ref_osm_industrial i
         WHERE i.longitude BETWEEN p.lon - {w} AND p.lon + {w}
           AND i.latitude  BETWEEN p.lat - {w} AND p.lat + {w}) AS industrial_m
FROM probes p
"""

# The industrial rule of record includes GEM assets, gated by whether the asset was
# operating in the detection's year. The background the lift divides by has to include
# them too. It did not: every with GEM lift divided a GEM inclusive share by an
# OpenStreetMap only background, which inflates the lift. Probes carry no date, so the
# background is measured once per window year. D122.
WINDOW_YEARS = (2023, 2024, 2026)
GEM_SQL = """
SELECT (SELECT min(geo_distance_m(p.lon, p.lat, g.longitude, g.latitude))
          FROM ref_gem_assets g
         WHERE g.longitude BETWEEN p.lon - {w} AND p.lon + {w}
           AND g.latitude  BETWEEN p.lat - {w} AND p.lat + {w}
           AND (g.start_year IS NULL OR g.start_year <= {year})
           AND (g.retired_year IS NULL OR g.retired_year >= {year})) AS gem_m
FROM probes p
"""


def main() -> int:
    con = duckdb.connect(str(DUCKDB_PATH))
    install_geo(con)
    con.execute(f"SELECT setseed({(SEED % 1000) / 1000.0})")
    con.execute(PROBES_SQL)
    rows = con.execute(NEAREST_SQL.format(w=WINDOW_DEG)).fetchall()
    total = len(rows)
    if total == 0:
        print("no probe points generated", file=sys.stderr)
        return 1

    flare_d = [r[2] for r in rows]
    industrial_d = [r[3] for r in rows]
    gem_by_year = {
        year: [r[0] for r in con.execute(GEM_SQL.format(w=WINDOW_DEG, year=year)).fetchall()]
        for year in WINDOW_YEARS
    }

    def share(distances: list[float | None], radius: float) -> float:
        return sum(1 for d in distances if d is not None and d <= radius) / total

    print(f"probe points inside Indian state polygons: {total}")
    print(f"seed {SEED}, candidate window {WINDOW_DEG} degrees\n")
    print(f"{'radius m':>10} {'flare share':>13} {'industrial share':>18}")
    for radius in RADII_M:
        print(f"{radius:10.0f} {share(flare_d, radius):12.4%} {share(industrial_d, radius):17.2%}")

    print(
        f"\nat the rules in force, flare {FLARE_RADIUS_M:.0f} m and industrial "
        f"{INDUSTRIAL_RADIUS_M:.0f} m:"
    )
    print(f"  background flare share:      {share(flare_d, FLARE_RADIUS_M):.4%}")
    print(f"  background industrial share: {share(industrial_d, INDUSTRIAL_RADIUS_M):.2%}")
    with_gem = {}
    for year, gem_d in gem_by_year.items():
        either = [
            min(d for d in (a, b) if d is not None) if (a is not None or b is not None) else None
            for a, b in zip(industrial_d, gem_d, strict=True)
        ]
        with_gem[year] = share(either, INDUSTRIAL_RADIUS_M)
        print(f"  background industrial share with GEM, {year}: {with_gem[year]:.2%}")
    backgrounds = {
        "probe_points": total,
        "seed": SEED,
        "flare": share(flare_d, FLARE_RADIUS_M),
        "industrial_osm": share(industrial_d, INDUSTRIAL_RADIUS_M),
        "industrial_with_gem_by_year": {str(y): v for y, v in with_gem.items()},
    }
    ARTIFACT.write_text(json.dumps(backgrounds, indent=2, sort_keys=True) + "\n")

    lines = [
        "# Weak label radius sensitivity",
        "",
        "Regenerate: `uv run python scripts/label_radius_sensitivity.py`",
        provenance_line(__file__),
        "",
        "Generated by `scripts/label_radius_sensitivity.py`.",
        "",
        f"{total} probe points drawn uniformly inside Indian state polygons, seed {SEED}.",
        "",
        "**These are not detections.** Detections cluster in burning and industrial",
        "areas, so these shares are a background rate and a lower bound on the real",
        "labelled share. This measures the spatial reach of the reference layers, not",
        "the expected label distribution. That needs phase 1b.",
        "",
        "| Radius m | Within a flare site | Within an OSM industrial feature |",
        "|---|---|---|",
    ]
    for radius in RADII_M:
        lines.append(
            f"| {radius:.0f} | {share(flare_d, radius):.4%} | {share(industrial_d, radius):.2%} |"
        )
    lines += [
        "",
        f"Rules in force: flare {FLARE_RADIUS_M:.0f} m, industrial {INDUSTRIAL_RADIUS_M:.0f} m.",
        "",
        "Industrial background at the rule in force, including GEM assets operating in",
        "the window year, which is what the label of record matches against:",
        "",
        "| Window year | Within OSM industrial or an operating GEM asset |",
        "|---|---|",
        *[f"| {y} | {v:.2%} |" for y, v in with_gem.items()],
        "",
        "Reading it: the background industrial share is what a detection placed at",
        "random would pick up. If that number were already near the 60 percent",
        "dominance ceiling, the radius would be labelling geography rather than",
        "source type before any real detection arrived.",
        "",
    ]
    ensure_dir(OUT.parent)
    OUT.write_text("\n".join(lines) + "\n")
    print(f"\nwritten to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
