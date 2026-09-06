#!/usr/bin/env python3
"""Aggregate persistent thermal sources by spatial clustering, not coordinate rounding.

The first version grouped by rounding coordinates to three decimal places, about
110 m. A VIIRS pixel is 375 m, so one physical source split across several rows and
the count of unregistered sources was inflated by fragmentation. The number reached
docs/results.md before it was checked.

Clustering radius is reported as a sensitivity across a range rather than as one
tuned value, the way the orphan feature threshold was handled in D14.

Usage:
    uv run python scripts/persistent_sources.py
"""

import os

# Pinned before any estimator library loads. Thread count changes the floating
# point reduction order inside sklearn's histogram builders, and random_state does
# not constrain it, so a fixed seed alone does not reproduce a fit. D59.
os.environ.setdefault("OMP_NUM_THREADS", "4")


import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import duckdb
import numpy as np
from sklearn.cluster import DBSCAN

from ml.paths import DUCKDB_PATH, ROOT, ensure_dir

OUT_DOC = ROOT / "docs" / "persistent_sources.md"
EARTH_RADIUS_M = 6_371_000.0
MIN_PRIORS = 20
MIN_DETECTIONS = 5
REGISTERED_M = 1000.0

# Chosen radius. A VIIRS detection is 375 m across, so two detections of one source
# can sit that far apart before either is wrong. 500 m allows a little more than one
# pixel of positional spread without merging genuinely separate sites.
CHOSEN_RADIUS_M = 500.0
SWEEP_M = (110.0, 250.0, 375.0, 500.0, 750.0, 1000.0, 1500.0)

# Ordered because DBSCAN assigns border points according to the order it sees them,
# so an unordered result gives different cluster centroids run to run. Three
# consecutive runs returned three different sets of centroids before this, at a
# stable count of 263. Same defect as D66, in a script the D66 fix did not reach.
# D75.
CANDIDATES_SQL = f"""
SELECT d.longitude, d.latitude, c.state_name,
       r.prior_count_90d,
       CASE WHEN d.daynight = 'N' THEN 1 ELSE 0 END AS is_night,
       least(
         coalesce(c.industrial_m, 1e12),
         coalesce(g.gem_m_temporal, 1e12),
         coalesce(c.flare_m, 1e12)
       ) AS nearest_m
FROM detections d
JOIN detection_context c USING (detection_id)
JOIN detection_recurrence r USING (detection_id)
LEFT JOIN detection_gem g USING (detection_id)
WHERE c.state_name IS NOT NULL AND r.prior_count_90d >= {MIN_PRIORS}
ORDER BY d.detection_id
"""


def cluster(rows: list, radius_m: float) -> list[dict]:
    """Cluster candidate detections by great circle distance and summarise each."""
    coords = np.radians(np.array([[r[1], r[0]] for r in rows]))
    labels = DBSCAN(
        eps=radius_m / EARTH_RADIUS_M, min_samples=1, metric="haversine", algorithm="ball_tree"
    ).fit_predict(coords)

    sources: list[dict] = []
    # Sorted because the insertion order decides the tie break in the final sort by
    # detection count. Integer sets happen to iterate deterministically, since small
    # integers hash to themselves, but relying on that is the same bet that failed
    # for strings in D75. Made explicit rather than assumed.
    for label in sorted(set(labels)):
        members = [rows[i] for i in range(len(rows)) if labels[i] == label]
        if len(members) < MIN_DETECTIONS:
            continue
        nearest = min(float(m[5]) for m in members)
        states = [m[2] for m in members if m[2]]
        sources.append(
            {
                "lon": round(float(np.mean([m[0] for m in members])), 5),
                "lat": round(float(np.mean([m[1] for m in members])), 5),
                "state": max(sorted(set(states)), key=states.count) if states else None,
                "detections": len(members),
                "maxPriors": int(max(int(m[3]) for m in members)),
                "nightFraction": round(float(np.mean([int(m[4]) for m in members])), 3),
                "nearestAssetM": None if nearest > 1e11 else round(nearest),
                "registered": bool(nearest <= REGISTERED_M),
                "spreadM": round(
                    float(
                        EARTH_RADIUS_M
                        * np.max(
                            np.sqrt(
                                np.sum(
                                    (
                                        np.radians(np.array([[m[1], m[0]] for m in members]))
                                        - np.radians(
                                            [
                                                float(np.mean([m[1] for m in members])),
                                                float(np.mean([m[0] for m in members])),
                                            ]
                                        )
                                    )
                                    ** 2,
                                    axis=1,
                                )
                            )
                        )
                    )
                ),
            }
        )
    return sorted(sources, key=lambda s: -s["detections"])


def main() -> int:
    con = duckdb.connect(str(DUCKDB_PATH))
    rows = con.execute(CANDIDATES_SQL).fetchall()
    print(f"candidate detections with {MIN_PRIORS} or more priors: {len(rows)}", flush=True)

    print(f"\n{'radius m':>9} {'sources':>8} {'unregistered':>13} {'largest spread m':>17}")
    sweep = []
    for radius in SWEEP_M:
        sources = cluster(rows, radius)
        unregistered = sum(1 for s in sources if not s["registered"])
        spread = max((s["spreadM"] for s in sources), default=0)
        sweep.append((radius, len(sources), unregistered, spread))
        print(f"{radius:9.0f} {len(sources):8d} {unregistered:13d} {spread:17.0f}")

    chosen = cluster(rows, CHOSEN_RADIUS_M)
    unregistered = [s for s in chosen if not s["registered"]]
    print(
        f"\nchosen radius {CHOSEN_RADIUS_M:.0f} m: {len(chosen)} sources, "
        f"{len(unregistered)} unregistered"
    )
    print("\ntop unregistered sources:")
    for s in unregistered[:8]:
        print(
            f"  {s['state']!s:14s} {s['lat']:.4f}, {s['lon']:.4f}  "
            f"{s['detections']:4d} det, spread {s['spreadM']:.0f} m, "
            f"nearest {s['nearestAssetM']} m"
        )

    lines = [
        "# Persistent thermal sources",
        "",
        "Regenerate: `uv run python scripts/persistent_sources.py`",
        "",
        "Generated by `scripts/persistent_sources.py`.",
        "",
        "A persistent source is a location with at least "
        f"{MIN_PRIORS} prior detections in a trailing 90 days and at least "
        f"{MIN_DETECTIONS} detections in the record.",
        "",
        "## Why clustering rather than coordinate rounding",
        "",
        "The first version grouped by rounding coordinates to three decimal places,",
        "about 110 m. A VIIRS detection is 375 m across, so a single physical source",
        "split across several rows and the unregistered count was inflated by",
        "fragmentation. Detections are now clustered by great circle distance.",
        "",
        "## Radius sensitivity",
        "",
        "| Radius m | Sources | Unregistered | Largest cluster spread m |",
        "|---|---|---|---|",
    ]
    for radius, total, unreg, spread in sweep:
        mark = " (chosen)" if radius == CHOSEN_RADIUS_M else ""
        lines.append(f"| {radius:.0f}{mark} | {total} | {unreg} | {spread:.0f} |")
    lines += [
        "",
        f"{CHOSEN_RADIUS_M:.0f} m is chosen because a VIIRS detection is 375 m across,",
        "so two detections of one source can sit that far apart before either is",
        "mislocated. 500 m allows slightly more than one pixel of positional spread",
        "without merging genuinely separate sites.",
        "",
        "## Unregistered sources at the chosen radius",
        "",
        f"{len(unregistered)} of {len(chosen)} sources have no registry match within "
        f"{REGISTERED_M:.0f} m of an OSM industrial feature, a GEM asset operating on",
        "the detection date, or a catalogued flare.",
        "",
        "| State | Latitude | Longitude | Detections | Cluster spread m | Nearest asset m |",
        "|---|---|---|---|---|---|",
    ]
    for s in unregistered[:25]:
        lines.append(
            f"| {s['state']} | {s['lat']:.4f} | {s['lon']:.4f} | {s['detections']} | "
            f"{s['spreadM']:.0f} | {s['nearestAssetM']} |"
        )
    lines.append("")

    ensure_dir(OUT_DOC.parent)
    OUT_DOC.write_text("\n".join(lines) + "\n")
    ensure_dir(ROOT / "ml" / "artifacts")
    (ROOT / "ml" / "artifacts" / "persistent_sources.json").write_text(
        json.dumps(
            {"chosen_radius_m": CHOSEN_RADIUS_M, "sweep": sweep, "sources": chosen}, indent=1
        )
    )
    print(f"\nwritten to {OUT_DOC}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
