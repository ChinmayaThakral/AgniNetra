#!/usr/bin/env python3
"""Correct the M1 statistics for sampling contamination, and audit the flare class.

Two corrections, both to the same underlying problem.

Overpass thinning. Four satellites observe one cell within minutes on the same
pass, so raw inter arrival gaps have a dominant mode near 0.01 days that is
constellation geometry rather than fire recurrence. Every statistic derived from
those gaps inherits it, burstiness included. Gaps are therefore recomputed between
distinct observation days.

Window boundaries. The ingest covers three disjoint windows, so a gap spanning
2023-11-30 to 2024-10-01 is an artefact of what was ingested rather than a property
of the process. Gaps are computed within a window and pooled across windows.

The flare audit tests whether three inverted premises are label noise or
measurement contamination, by stratifying flare cells on distance to the nearest
EOG catalogue coordinate. If the statistics move with distance the label is
capturing adjacent activity; if they do not, the inversion is not about the label.

Usage:
    uv run python scripts/m1_corrected_gujarat.py
"""

import statistics
import sys
from collections import defaultdict
from itertools import pairwise
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import duckdb

from ml.features.recurrence import CELL_DEGREES
from ml.paths import DUCKDB_PATH, ROOT, ensure_dir
from ml.reference.geo import install_geo

STATE = "Gujarat"
OUT = ROOT / "docs" / "m1_corrected.md"
CLASS_ORDER = ("flare", "industrial", "agricultural", "unlabelled")

WINDOWS = {
    "s2023": ("2023-10-01", "2023-11-30"),
    "s2024": ("2024-10-01", "2024-11-30"),
    "m2026": ("2026-06-06", "2026-09-03"),
}

SQL = f"""
SELECT c.weak_label,
       floor(d.longitude / {CELL_DEGREES}) AS cx,
       floor(d.latitude  / {CELL_DEGREES}) AS cy,
       d.acq_ts_utc, d.acq_date_ist,
       (SELECT min(geo_distance_m(d.longitude, d.latitude, f.longitude, f.latitude))
          FROM ref_flares f
         WHERE f.longitude BETWEEN d.longitude - 0.02 AND d.longitude + 0.02
           AND f.latitude  BETWEEN d.latitude  - 0.02 AND d.latitude  + 0.02) AS flare_m
FROM detections d
JOIN detection_context c USING (detection_id)
WHERE c.state_name = ?
"""


def burstiness(gaps: list[float]) -> float | None:
    """(sd - mean) / (sd + mean). Zero for Poisson, positive bursty, negative regular."""
    if len(gaps) < 2:
        return None
    mean_gap = statistics.mean(gaps)
    sd_gap = statistics.pstdev(gaps)
    if mean_gap + sd_gap <= 0:
        return None
    return (sd_gap - mean_gap) / (mean_gap + sd_gap)


def window_of(day: str) -> str | None:
    for name, (start, end) in WINDOWS.items():
        if start <= day <= end:
            return name
    return None


def summarise(values: list[float]) -> str:
    if len(values) < 15:
        return "too few"
    return f"{statistics.median(values):.3f}"


def main() -> int:
    con = duckdb.connect(str(DUCKDB_PATH))
    install_geo(con)
    rows = con.execute(SQL, [STATE]).fetchall()
    print(f"{STATE}: {len(rows)} detections", flush=True)

    cells: dict[tuple[float, float], list] = defaultdict(list)
    for row in rows:
        cells[(row[1], row[2])].append(row)

    raw_burst: dict[str, list[float]] = {c: [] for c in CLASS_ORDER}
    day_burst: dict[str, list[float]] = {c: [] for c in CLASS_ORDER}
    per_cell_n: dict[str, list[float]] = {c: [] for c in CLASS_ORDER}
    day_gap_median: dict[str, list[float]] = {c: [] for c in CLASS_ORDER}
    flare_strata: dict[str, dict[str, list[float]]] = {
        "under_100m": defaultdict(list),
        "100_to_300m": defaultdict(list),
        "300_to_500m": defaultdict(list),
    }

    for events in cells.values():
        labels = [e[0] for e in events]
        cell_class = max(set(labels), key=labels.count)
        if cell_class not in raw_burst:
            continue

        raw_times = sorted(e[3] for e in events)
        raw_gaps = [(b - a).total_seconds() / 86400.0 for a, b in pairwise(raw_times)]
        raw_gaps = [g for g in raw_gaps if g > 0]

        # Distinct observation days, grouped by window so a gap never spans one.
        by_window: dict[str, set[str]] = defaultdict(set)
        for event in events:
            day = str(event[4])
            window = window_of(day)
            if window:
                by_window[window].add(day)
        day_gaps: list[float] = []
        from datetime import date as _date

        for days in by_window.values():
            ordered = sorted(_date.fromisoformat(d) for d in days)
            day_gaps.extend(float((b - a).days) for a, b in pairwise(ordered))
        day_gaps = [g for g in day_gaps if g > 0]

        if len(events) < 4:
            continue
        per_cell_n[cell_class].append(float(len(events)))
        raw_value = burstiness(raw_gaps)
        if raw_value is not None:
            raw_burst[cell_class].append(raw_value)
        day_value = burstiness(day_gaps)
        if day_value is not None:
            day_burst[cell_class].append(day_value)
        if day_gaps:
            day_gap_median[cell_class].append(statistics.median(day_gaps))

        if cell_class == "flare":
            distances = [e[5] for e in events if e[5] is not None]
            if distances:
                nearest = min(float(d) for d in distances)
                stratum = (
                    "under_100m"
                    if nearest < 100
                    else "100_to_300m"
                    if nearest < 300
                    else "300_to_500m"
                    if nearest <= 500
                    else None
                )
                if stratum:
                    bucket = flare_strata[stratum]
                    bucket["n"].append(float(len(events)))
                    if day_value is not None:
                        bucket["burstiness_day"].append(day_value)
                    if raw_value is not None:
                        bucket["burstiness_raw"].append(raw_value)
                    if day_gaps:
                        bucket["gap_days"].append(statistics.median(day_gaps))

    print("\n=== burstiness, raw gaps against distinct observation days ===")
    hdr = f"{'class':14s} {'raw':>9s} {'by day':>9s} {'det/cell':>10s}"
    print(f"{hdr} {'gap days':>10s} {'cells':>7s}")
    lines = [
        "# M1 corrected for sampling contamination",
        "",
        "Regenerate: `uv run python scripts/m1_corrected_gujarat.py`",
        "",
        "Generated by `scripts/m1_corrected_gujarat.py`.",
        "",
        "Raw burstiness is computed from every inter arrival gap, including gaps of",
        "minutes produced by several satellites observing one cell on one overpass.",
        "The corrected column uses gaps between distinct observation days, computed",
        "within an ingest window so no gap spans the holes between windows.",
        "",
        "| Class | Burst raw | Burst by day | Det per cell | Median day gap | Cells |",
        "|---|---|---|---|---|---|",
    ]
    for name in CLASS_ORDER:
        raw_text = summarise(raw_burst[name])
        day_text = summarise(day_burst[name])
        n_text = summarise(per_cell_n[name])
        gap_text = summarise(day_gap_median[name])
        count = len(day_burst[name])
        print(f"{name:14s} {raw_text:>9s} {day_text:>9s} {n_text:>10s} {gap_text:>10s} {count:7d}")
        lines.append(f"| {name} | {raw_text} | {day_text} | {n_text} | {gap_text} | {count} |")

    print("\n=== flare audit, stratified by distance to the nearest EOG coordinate ===")
    hdr2 = f"{'stratum':14s} {'cells':>6s} {'burst raw':>10s}"
    print(f"{hdr2} {'burst day':>10s} {'det/cell':>9s} {'gap days':>9s}")
    lines += [
        "",
        "## Flare audit, stratified by distance to the nearest EOG coordinate",
        "",
        "If the flare statistics move with distance from the catalogue coordinate, the",
        "label is capturing adjacent activity rather than the stack. If they do not,",
        "the inverted premises are not about label noise.",
        "",
        "| Stratum | Cells | Burst raw | Burst by day | Det per cell | Median day gap |",
        "|---|---|---|---|---|---|",
    ]
    for stratum in ("under_100m", "100_to_300m", "300_to_500m"):
        bucket = flare_strata[stratum]
        count = len(bucket["n"])
        row = (
            f"{stratum:14s} {count:6d} {summarise(bucket['burstiness_raw']):>10s} "
            f"{summarise(bucket['burstiness_day']):>10s} {summarise(bucket['n']):>9s} "
            f"{summarise(bucket['gap_days']):>9s}"
        )
        print(row)
        lines.append(
            f"| {stratum.replace('_', ' ')} | {count} | "
            f"{summarise(bucket['burstiness_raw'])} | {summarise(bucket['burstiness_day'])} | "
            f"{summarise(bucket['n'])} | {summarise(bucket['gap_days'])} |"
        )
    lines.append("")
    ensure_dir(OUT.parent)
    OUT.write_text("\n".join(lines) + "\n")
    print(f"\nwritten to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
