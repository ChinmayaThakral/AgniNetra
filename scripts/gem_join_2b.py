#!/usr/bin/env python3
"""Join GEM assets to detections under the operating window, and measure the cost
of not doing so.

Two distances are computed for every detection: the nearest GEM asset that was
operating on the detection's date, and the nearest GEM asset ignoring dates
entirely. The second is not used for labelling. It exists so the difference is
attributable rather than assumed, because no weak labelling work in this area
treats the reference set as time varying and the size of the effect is the reason
to start.

Every temporal match is then re checked through the guard in ml.reference.gem. If
the SQL window and the guard ever disagree the run stops.

Usage:
    uv run python scripts/gem_join_2b.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import duckdb

from ml.paths import DUCKDB_PATH, ROOT, ensure_dir
from ml.reference.gem import AssetWindowError, assert_asset_valid_for
from ml.reference.geo import install_geo

OUT = ROOT / "docs" / "gem_temporal_validity.md"
WINDOW_DEG = 0.06

JOIN_SQL = f"""
CREATE OR REPLACE TABLE detection_gem AS
WITH d AS (
    SELECT detection_id, longitude, latitude, acq_date_ist,
           CAST(strftime(acq_date_ist, '%Y') AS INTEGER) AS yr
    FROM detections
)
SELECT d.detection_id,
       (SELECT min(geo_distance_m(d.longitude, d.latitude, g.longitude, g.latitude))
          FROM ref_gem_assets g
         WHERE g.longitude BETWEEN d.longitude - {WINDOW_DEG} AND d.longitude + {WINDOW_DEG}
           AND g.latitude  BETWEEN d.latitude  - {WINDOW_DEG} AND d.latitude  + {WINDOW_DEG}
           AND (g.start_year IS NULL OR d.yr >= g.start_year)
           AND (g.retired_year IS NULL OR d.yr <= g.retired_year)
       ) AS gem_m_temporal,
       (SELECT min(geo_distance_m(d.longitude, d.latitude, g.longitude, g.latitude))
          FROM ref_gem_assets g
         WHERE g.longitude BETWEEN d.longitude - {WINDOW_DEG} AND d.longitude + {WINDOW_DEG}
           AND g.latitude  BETWEEN d.latitude  - {WINDOW_DEG} AND d.latitude  + {WINDOW_DEG}
       ) AS gem_m_naive
FROM d;
"""

INDUSTRIAL_RADIUS = 1000.0


def main() -> int:
    con = duckdb.connect(str(DUCKDB_PATH))
    install_geo(con)
    print("joining GEM assets under the operating window", flush=True)
    con.execute(JOIN_SQL)

    total = int(con.execute("SELECT count(*) FROM detection_gem").fetchone()[0])
    print(f"detections joined: {total}")

    # Verify the SQL window against the Python guard on every temporal match inside
    # the industrial radius. The window predicate is repeated here deliberately:
    # without it the re join picks up co located units that share coordinates with
    # the matched one but were retired, which is a property of power stations
    # rather than a fault in the join. Ropar is one such site. The check is still a
    # real second method, because the SQL predicate and the Python guard are two
    # independent statements of the same rule and disagree at the boundaries if
    # either is wrong.
    print("re checking every in radius temporal match through the guard", flush=True)
    checks = con.execute(
        f"""
        SELECT d.acq_date_ist, g.start_year, g.retired_year, g.name
        FROM detections d
        JOIN detection_gem j USING (detection_id)
        JOIN ref_gem_assets g
          ON g.longitude BETWEEN d.longitude - {WINDOW_DEG} AND d.longitude + {WINDOW_DEG}
         AND g.latitude  BETWEEN d.latitude  - {WINDOW_DEG} AND d.latitude  + {WINDOW_DEG}
         AND (g.start_year IS NULL
              OR CAST(strftime(d.acq_date_ist, '%Y') AS INTEGER) >= g.start_year)
         AND (g.retired_year IS NULL
              OR CAST(strftime(d.acq_date_ist, '%Y') AS INTEGER) <= g.retired_year)
         AND abs(geo_distance_m(d.longitude, d.latitude, g.longitude, g.latitude)
                 - j.gem_m_temporal) < 0.001
        WHERE j.gem_m_temporal IS NOT NULL AND j.gem_m_temporal <= {INDUSTRIAL_RADIUS}
        """
    ).fetchall()
    for acq_date, start_year, retired_year, name in checks:
        try:
            assert_asset_valid_for(start_year, retired_year, acq_date, str(name))
        except AssetWindowError as exc:
            print(f"\nSTOP: the SQL window and the guard disagree.\n  {exc}", file=sys.stderr)
            return 1
    print(f"  {len(checks)} matched pairs, all inside their operating window")

    rows = con.execute(
        f"""
        SELECT
          count(*) FILTER (WHERE gem_m_temporal <= {INDUSTRIAL_RADIUS}) AS temporal_hits,
          count(*) FILTER (WHERE gem_m_naive    <= {INDUSTRIAL_RADIUS}) AS naive_hits,
          count(*) FILTER (WHERE gem_m_naive <= {INDUSTRIAL_RADIUS}
                             AND (gem_m_temporal IS NULL
                                  OR gem_m_temporal > {INDUSTRIAL_RADIUS})) AS only_naive,
          count(*) FILTER (WHERE gem_m_temporal <= {INDUSTRIAL_RADIUS}
                             AND (gem_m_naive IS NULL
                                  OR gem_m_naive > {INDUSTRIAL_RADIUS})) AS only_temporal
        FROM detection_gem
        """
    ).fetchone()
    temporal_hits, naive_hits, only_naive, only_temporal = (int(v) for v in rows)

    print(f"\nwithin {INDUSTRIAL_RADIUS:.0f} m of a GEM asset:")
    print(f"  under the operating window: {temporal_hits}")
    print(f"  ignoring dates:             {naive_hits}")
    print(f"  labels a static join would add wrongly: {only_naive}")
    print(f"  labels only the temporal join finds:    {only_temporal}")
    changed = only_naive + only_temporal
    print(f"  total labels that differ: {changed} ({changed / total:.3%} of detections)")
    if temporal_hits:
        print(f"  as a share of GEM industrial labels: {changed / temporal_hits:.2%}")

    by_window = con.execute(
        f"""
        SELECT CASE
                 WHEN d.acq_date_ist < DATE '2024-01-01' THEN '2023 season'
                 WHEN d.acq_date_ist < DATE '2025-01-01' THEN '2024 season'
                 ELSE 'monsoon 2026' END AS window,
               count(*) FILTER (WHERE j.gem_m_naive <= {INDUSTRIAL_RADIUS}
                                  AND (j.gem_m_temporal IS NULL
                                       OR j.gem_m_temporal > {INDUSTRIAL_RADIUS})) AS only_naive,
               count(*) FILTER (WHERE j.gem_m_temporal <= {INDUSTRIAL_RADIUS}) AS temporal_hits
        FROM detections d JOIN detection_gem j USING (detection_id)
        GROUP BY 1 ORDER BY 1
        """
    ).fetchall()
    print("\nby window:")
    for window, only_naive_w, temporal_w in by_window:
        print(
            f"  {window:14s} temporal hits {temporal_w:7d}, static join would add "
            f"{only_naive_w} wrongly"
        )

    lines = [
        "# GEM temporal validity",
        "",
        "Regenerate: `uv run python scripts/gem_join_2b.py`",
        "",
        "Generated by `scripts/gem_join_2b.py`.",
        "",
        "Assets carry an operating window and a detection may only match an asset that",
        "was operating on its acquisition date. The naive column ignores dates and is",
        "computed only so the difference is attributable.",
        "",
        "| Quantity | Detections |",
        "|---|---|",
        f"| Within {INDUSTRIAL_RADIUS:.0f} m under the operating window | {temporal_hits} |",
        f"| Within {INDUSTRIAL_RADIUS:.0f} m ignoring dates | {naive_hits} |",
        f"| Labels a static join adds wrongly | {only_naive} |",
        f"| Labels only the temporal join finds | {only_temporal} |",
        f"| Total differing | {changed} ({changed / total:.3%} of all detections) |",
        "",
        "By window:",
        "",
        "| Window | Temporal hits | Static join adds wrongly |",
        "|---|---|---|",
    ]
    for window, only_naive_w, temporal_w in by_window:
        lines.append(f"| {window} | {temporal_w} | {only_naive_w} |")
    lines.append("")
    ensure_dir(OUT.parent)
    OUT.write_text("\n".join(lines) + "\n")
    print(f"\nwritten to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
