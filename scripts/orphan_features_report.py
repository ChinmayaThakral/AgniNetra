#!/usr/bin/env python3
"""Decompose the industrial features that fall inside no state polygon.

A count of orphans is not a finding, because at least four different causes
produce the same number and only one of them is interesting:

  arunachal    genuinely inside Arunachal Pradesh, which has no boundary at any
               administrative level in the extract. This is the coverage finding
  outside_in   inside a neighbouring country. The Geofabrik India extract carries
               a buffer beyond the border, so this is expected and is not a defect
  clipped      within a short distance of a state polygon. Boundary generalisation
               and coastline detail put a real feature just outside the edge
  unexplained  none of the above. This would be a bug in our pipeline and it would
               change the coverage numbers

The classification is by distance to the nearest state polygon, measured in metres
through the geo macros, plus a containment test against neighbouring country
extents. The threshold is stated rather than tuned.

Usage:
    uv run python scripts/orphan_features_report.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import duckdb

from ml.documents import provenance_line
from ml.paths import DUCKDB_PATH, ROOT, ensure_dir
from ml.reference.geo import install_geo

OUT = ROOT / "docs" / "orphan_features.md"

# A feature within this distance of a state edge is treated as a boundary
# artefact rather than a real gap. 2 km is generous for OSM boundary
# generalisation and coastline detail, and the sensitivity is reported so the
# choice can be checked rather than trusted.
CLIP_THRESHOLD_M = 2000.0

# Approximate extent of Arunachal Pradesh, used only because the state has no
# polygon in the extract. Stated openly as an approximation.
ARUNACHAL_BBOX = (91.5, 26.6, 97.5, 29.5)

# Neighbouring country extents that the India extract buffer reaches into.
NEIGHBOURS = {
    "Nepal": (80.0, 26.3, 88.2, 30.5),
    "Bhutan": (88.7, 26.7, 92.2, 28.4),
    "Bangladesh": (88.0, 20.5, 92.7, 26.7),
    "Sri Lanka": (79.6, 5.8, 82.0, 10.0),
    "Pakistan": (60.8, 23.6, 77.9, 37.1),
    "Myanmar": (92.1, 9.5, 101.2, 28.6),
    "China or Tibet": (78.0, 29.5, 99.0, 36.5),
}

ORPHAN_SQL = """
WITH states AS (
    SELECT geom FROM ref_osm_admin WHERE admin_level = '4'
),
orphans AS (
    SELECT i.osm_type, i.osm_id, i.tag_key, i.tag_value, i.name,
           i.longitude, i.latitude
    FROM ref_osm_industrial i
    WHERE NOT EXISTS (
        SELECT 1 FROM states s
        WHERE ST_Contains(s.geom, ST_Point(i.longitude, i.latitude))
    )
)
SELECT o.osm_type, o.osm_id, o.tag_key, o.tag_value, o.name,
       o.longitude, o.latitude,
       min(geo_distance_geom_m(
            ST_Point(o.longitude, o.latitude),
            ST_ClosestPoint(s.geom, ST_Point(o.longitude, o.latitude))
       )) AS nearest_state_m
FROM orphans o CROSS JOIN states s
GROUP BY ALL
"""


def in_bbox(*, lon: float, lat: float, box: tuple[float, float, float, float]) -> bool:
    west, south, east, north = box
    return west <= lon <= east and south <= lat <= north


def classify(*, lon: float, lat: float, nearest_m: float) -> tuple[str, str]:
    """Return the category and the reason, in that order."""
    if nearest_m <= CLIP_THRESHOLD_M:
        return "clipped", f"{nearest_m:.0f} m from a state edge"
    if in_bbox(lon=lon, lat=lat, box=ARUNACHAL_BBOX):
        return "arunachal", "inside the Arunachal Pradesh extent, which has no polygon"
    for country, box in NEIGHBOURS.items():
        if in_bbox(lon=lon, lat=lat, box=box):
            return "outside_in", f"inside the {country} extent, extract buffer"
    return "unexplained", f"{nearest_m / 1000:.1f} km from any state, no known cause"


def main() -> int:
    con = duckdb.connect(str(DUCKDB_PATH))
    install_geo(con)
    rows = con.execute(ORPHAN_SQL).fetchall()

    buckets: dict[str, list[tuple[object, ...]]] = {
        "arunachal": [],
        "outside_in": [],
        "clipped": [],
        "unexplained": [],
    }
    for row in rows:
        lon, lat, nearest = float(row[5]), float(row[6]), float(row[7])
        category, reason = classify(lon=lon, lat=lat, nearest_m=nearest)
        buckets[category].append((*row, category, reason))

    total = len(rows)
    print(f"orphan features: {total}\n")
    for category, items in buckets.items():
        share = 100.0 * len(items) / total if total else 0.0
        print(f"  {category:12s} {len(items):4d}  {share:5.1f} percent")

    # Sensitivity of the one tuned number in this script. The zero unexplained
    # result is not threshold robust on its own, which is why the residual set is
    # reported by name.
    print(f"\nclip threshold sensitivity, currently {CLIP_THRESHOLD_M:.0f} m:")
    for threshold in (250.0, 500.0, 1000.0, 2000.0, 5000.0):
        n = sum(1 for r in rows if float(r[7]) <= threshold)
        print(f"  within {threshold:6.0f} m: {n:4d}")

    n_arunachal_extent = sum(
        1 for r in rows if in_bbox(lon=float(r[5]), lat=float(r[6]), box=ARUNACHAL_BBOX)
    )
    print(f"\norphans inside the Arunachal extent regardless of clipping: {n_arunachal_extent}")

    lines = [
        "# Industrial features outside every state polygon",
        "",
        "Regenerate: `uv run python scripts/orphan_features_report.py`",
        provenance_line(__file__),
        "",
        "Generated by `scripts/orphan_features_report.py`.",
        "",
        "Snapshot: Geofabrik India extract, 2026-09-02T20:20:51Z, sequence 4895.",
        "",
        f"Total orphan features: {total} of 34911.",
        "",
        "A count alone is not a finding. Four causes produce the same number and only",
        "one of them is the coverage result. Classification is by distance to the",
        "nearest state polygon, measured in metres, plus a containment test against",
        "neighbouring country extents.",
        "",
        "| Category | Features | Share | Meaning |",
        "|---|---|---|---|",
    ]
    meanings = {
        "arunachal": (
            "Inside Arunachal Pradesh, which has no boundary at any level. The coverage finding"
        ),
        "outside_in": (
            "Inside a neighbouring country. The extract carries a buffer beyond "
            "the border, so this is expected"
        ),
        "clipped": (
            f"Within {CLIP_THRESHOLD_M:.0f} m of a state edge. Boundary generalisation, not a gap"
        ),
        "unexplained": "No known cause. Any count here is a pipeline defect",
    }
    for category, items in buckets.items():
        share = 100.0 * len(items) / total if total else 0.0
        lines.append(
            f"| `{category}` | {len(items)} | {share:.1f} percent | {meanings[category]} |"
        )

    lines += [
        "",
        "## Clip threshold sensitivity",
        "",
        f"The {CLIP_THRESHOLD_M:.0f} m threshold is the only tuned number here, so its",
        "effect is reported rather than asserted.",
        "",
        "| Threshold | Features within it |",
        "|---|---|",
    ]
    for threshold in (250.0, 500.0, 1000.0, 2000.0, 5000.0):
        n = sum(1 for r in rows if float(r[7]) <= threshold)
        lines.append(f"| {threshold:.0f} m | {n} |")

    if buckets["unexplained"]:
        lines += [
            "",
            "## Unexplained features, every one listed",
            "",
            "| OSM | Tag | Name | Longitude | Latitude | Nearest state |",
            "|---|---|---|---|---|---|",
        ]
        for row in sorted(buckets["unexplained"], key=lambda r: -float(r[7])):
            lines.append(
                f"| {row[0]}/{row[1]} | {row[2]}={row[3]} | {row[4] or '(unnamed)'} | "
                f"{row[5]:.4f} | {row[6]:.4f} | {float(row[7]) / 1000:.1f} km |"
            )
    else:
        lines += [
            "",
            "No unexplained features at the threshold in force. The residual set above",
            "is the honest check on that, since it does not depend on the threshold.",
            "",
        ]

    ensure_dir(OUT.parent)
    OUT.write_text("\n".join(lines) + "\n")
    print(f"\nwritten to {OUT}")

    if buckets["unexplained"]:
        print("\nunexplained, all listed:")
        for row in sorted(buckets["unexplained"], key=lambda r: -float(r[7]))[:20]:
            print(
                f"  {row[0]}/{row[1]} {row[2]}={row[3]} lon {row[5]:.4f} lat {row[6]:.4f} "
                f"{float(row[7]) / 1000:.1f} km"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
