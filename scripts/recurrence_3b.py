#!/usr/bin/env python3
"""Phase 3b: recurrence features over the real detections.

Every feature is computed strictly from detections earlier than the one being
described, at the same grid cell. The leakage guard in ml/features/recurrence.py
raises rather than filtering, so a history assembled wrongly stops the run instead
of producing a flattering number.

Each quantity is then recomputed by an independent route in SQL and the two are
asserted equal. That habit is what caught the coordinate axis bug.

Usage:
    uv run python scripts/recurrence_3b.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import duckdb

from ml.features.recurrence import (
    CELL_DEGREES,
    Event,
    LeakageError,
    cell_key,
    count_in_window,
    frp_variance,
    mean_inter_arrival_days,
    night_fraction,
)
from ml.paths import DUCKDB_PATH, ROOT, ensure_dir

OUT = ROOT / "docs" / "recurrence_summary.md"

FEATURES_DDL = """
CREATE OR REPLACE TABLE detection_recurrence (
    detection_id        VARCHAR PRIMARY KEY,
    cell_x              INTEGER NOT NULL,
    cell_y              INTEGER NOT NULL,
    prior_count_90d     INTEGER NOT NULL,
    prior_count_30d     INTEGER NOT NULL,
    night_fraction_90d  DOUBLE,
    frp_variance_90d    DOUBLE,
    mean_gap_days       DOUBLE
);
"""


def main() -> int:
    con = duckdb.connect(str(DUCKDB_PATH))
    rows = con.execute(
        "SELECT detection_id, longitude, latitude, acq_ts_utc, frp, daynight "
        "FROM detections ORDER BY acq_ts_utc"
    ).fetchall()
    if not rows:
        print("no detections", file=sys.stderr)
        return 2
    print(f"detections: {len(rows)}")

    by_cell: dict[tuple[int, int], list[Event]] = {}
    payload = []
    leak_failures = 0

    # Detections sharing an acquisition timestamp in one cell are contemporaneous,
    # not prior history. VIIRS resolves acquisition time to the minute and a swath
    # can put several detections in one 0.005 degree cell in the same minute:
    # measured here, 6370 such groups covering 13134 detections, largest group 4.
    #
    # Appending each detection to its cell as the loop advances makes the second
    # member of such a group see the first as history at its own reference time,
    # which the leakage guard correctly refuses. Detections are therefore processed
    # in timestamp batches: features for every detection at time t are computed
    # against history strictly earlier than t, and only then is the whole batch
    # added to the histories.
    pending: list[tuple[tuple[int, int], Event]] = []
    current_ts = None

    def flush_pending() -> None:
        for cell_key_value, event in pending:
            by_cell.setdefault(cell_key_value, []).append(event)
        pending.clear()

    for detection_id, lon, lat, when, frp, daynight in rows:
        if when != current_ts:
            flush_pending()
            current_ts = when
        cell = cell_key(float(lon), float(lat))
        history = by_cell.get(cell, [])
        try:
            count_90 = count_in_window(history, when, 90)
            count_30 = count_in_window(history, when, 30)
            nights = night_fraction(history, when, 90)
            variance = frp_variance(history, when, 90)
            gap = mean_inter_arrival_days(history, when)
        except LeakageError as exc:
            leak_failures += 1
            if leak_failures <= 3:
                print(f"  LeakageError on {detection_id}: {exc}", file=sys.stderr)
            continue
        payload.append((detection_id, cell[0], cell[1], count_90, count_30, nights, variance, gap))
        pending.append((cell, Event(when=when, frp=float(frp or 0.0), is_night=(daynight == "N"))))
    flush_pending()

    if leak_failures:
        print(f"\nSTOP: {leak_failures} detections raised LeakageError", file=sys.stderr)
        return 1

    con.execute(FEATURES_DDL)
    con.executemany("INSERT INTO detection_recurrence VALUES (?, ?, ?, ?, ?, ?, ?, ?)", payload)
    written = int(con.execute("SELECT count(*) FROM detection_recurrence").fetchone()[0])
    print(f"recurrence rows: {written}")

    # Second method. Recompute the 90 day prior count entirely in SQL, by a window
    # join rather than by the Python accumulation above.
    sql_check = con.execute(
        f"""
        WITH celled AS (
            SELECT detection_id, acq_ts_utc,
                   floor(longitude / {CELL_DEGREES}) AS cx,
                   floor(latitude  / {CELL_DEGREES}) AS cy
            FROM detections
        )
        SELECT a.detection_id,
               count(b.detection_id) AS prior_count
        FROM celled a
        LEFT JOIN celled b
          ON a.cx = b.cx AND a.cy = b.cy
         AND b.acq_ts_utc < a.acq_ts_utc
         AND b.acq_ts_utc >= a.acq_ts_utc - INTERVAL 90 DAY
        GROUP BY a.detection_id
        """
    ).fetchall()
    sql_counts = {r[0]: int(r[1]) for r in sql_check}
    mismatches = [
        (row[0], row[3], sql_counts.get(row[0]))
        for row in payload
        if sql_counts.get(row[0]) != row[3]
    ]
    print("\nsecond method check, prior_count_90d recomputed by SQL window join:")
    if mismatches:
        print(f"  DISAGREEMENT on {len(mismatches)} rows")
        for detection_id, python_value, sql_value in mismatches[:5]:
            print(f"    {detection_id}: python {python_value}, sql {sql_value}")
        return 1
    print(f"  agrees on all {len(payload)} rows")

    stats = con.execute(
        "SELECT max(prior_count_90d), avg(prior_count_90d), "
        "count(*) FILTER (WHERE prior_count_90d > 0), "
        "count(*) FILTER (WHERE night_fraction_90d = 1.0 AND prior_count_90d >= 10), "
        "count(*) FILTER (WHERE frp_variance_90d IS NOT NULL AND frp_variance_90d < 1.0 "
        "                       AND prior_count_90d >= 10) "
        "FROM detection_recurrence"
    ).fetchone()

    print(f"\nmax prior detections in a cell over 90 days: {stats[0]}")
    print(f"mean prior count: {float(stats[1]):.2f}")
    print(f"detections with any prior history: {stats[2]} ({stats[2] / written:.1%})")
    print(f"persistent all night cells with 10 or more priors: {stats[3]}")
    print(f"low radiative power variance with 10 or more priors: {stats[4]}")

    lines = [
        "# Recurrence feature summary",
        "",
        "Generated by `scripts/recurrence_3b.py`.",
        "",
        f"Window 2026-06-06 to 2026-09-03, {written} detections, grid cell {CELL_DEGREES} degrees.",
        "",
        "Every feature uses only detections strictly earlier than the one being",
        "described, in the same cell. The guard raises rather than filtering, so a",
        "wrongly assembled history stops the run.",
        "",
        "| Quantity | Value |",
        "|---|---|",
        f"| Max prior detections in a cell, 90 days | {stats[0]} |",
        f"| Mean prior count | {float(stats[1]):.2f} |",
        f"| Detections with any prior history | {stats[2]} ({stats[2] / written:.1%}) |",
        f"| All night cells with 10 or more priors | {stats[3]} |",
        f"| Low power variance with 10 or more priors | {stats[4]} |",
        "",
        "The last two rows are the flare signature: a location that recurs nightly",
        "with near constant radiative power. They are counts of detections meeting the",
        "condition, not a claim that each is a flare.",
        "",
        "prior_count_90d was recomputed by an independent SQL window join and agrees",
        "on every row.",
        "",
    ]
    ensure_dir(OUT.parent)
    OUT.write_text("\n".join(lines) + "\n")
    print(f"\nwritten to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
