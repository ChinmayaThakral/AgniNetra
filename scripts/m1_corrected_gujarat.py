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
from datetime import date
from itertools import pairwise
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import duckdb

from ml.documents import provenance_line
from ml.features.recurrence import CELL_DEGREES
from ml.labels.weak import weak_label_sql
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


def sql_for(with_gem: bool) -> str:
    return f"""
SELECT {weak_label_sql("c", "g", with_gem=with_gem)} AS weak_label,
       floor(d.longitude / {CELL_DEGREES}) AS cx,
       floor(d.latitude  / {CELL_DEGREES}) AS cy,
       d.acq_ts_utc, d.acq_date_ist,
       (SELECT min(geo_distance_m(d.longitude, d.latitude, f.longitude, f.latitude))
          FROM ref_flares f
         WHERE f.longitude BETWEEN d.longitude - 0.02 AND d.longitude + 0.02
           AND f.latitude  BETWEEN d.latitude  - 0.02 AND d.latitude  + 0.02) AS flare_m
FROM detections d
JOIN detection_context c USING (detection_id)
LEFT JOIN detection_gem g USING (detection_id)
WHERE c.state_name = ?
"""


# The owner decided on 2026-09-23 to report M1 under both industrial definitions,
# because its conclusion reverses between them. D121.
VARIANTS = (
    ("OSM and GEM, the label of record", True),
    ("OSM only, the narrower variant", False),
)


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


def measure(con: duckdb.DuckDBPyConnection, with_gem: bool) -> dict:
    """Per cell corrected statistics for one industrial definition."""
    rows = con.execute(sql_for(with_gem), [STATE]).fetchall()
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
        # A tie is broken by label name, not by set iteration order. `set()` iterates in an
        # order that varies between processes because Python randomises string hashing, so
        # `max(set(x), key=x.count)` returned a different winner run to run whenever the top
        # two counts were equal. Measured on Gujarat: 26 of 621 cells with four or more
        # detections tie, 4.2 percent, and each flipped class between runs. Same class of
        # defect as D66. D75.
        cell_class = max(sorted(set(labels)), key=labels.count)
        if cell_class not in raw_burst:
            continue

        raw_times = sorted(e[3] for e in events)
        raw_gaps = [(b - a).total_seconds() / 86400.0 for a, b in pairwise(raw_times)]
        raw_gaps = [g for g in raw_gaps if g > 0]

        by_window: dict[str, set[str]] = defaultdict(set)
        for event in events:
            day = str(event[4])
            window = window_of(day)
            if window:
                by_window[window].add(day)
        day_gaps: list[float] = []
        for days in by_window.values():
            ordered = sorted(date.fromisoformat(d) for d in days)
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

    flare_day = statistics.median(day_burst["flare"]) if day_burst["flare"] else None
    industrial_day = statistics.median(day_burst["industrial"]) if day_burst["industrial"] else None
    separation = (
        None if flare_day is None or industrial_day is None else abs(flare_day - industrial_day)
    )
    return {
        "rows": len(rows),
        "raw_burst": raw_burst,
        "day_burst": day_burst,
        "per_cell_n": per_cell_n,
        "day_gap_median": day_gap_median,
        "flare_strata": flare_strata,
        "separation": separation,
    }


def main() -> int:
    con = duckdb.connect(str(DUCKDB_PATH))
    install_geo(con)
    results = {title: measure(con, with_gem) for title, with_gem in VARIANTS}
    print(f"{STATE}: {results[VARIANTS[0][0]]['rows']} detections", flush=True)

    lines = [
        "# M1 corrected for sampling contamination",
        "",
        "Regenerate: `uv run python scripts/m1_corrected_gujarat.py`",
        provenance_line(__file__),
        "",
        "Generated by `scripts/m1_corrected_gujarat.py`.",
        "",
        "Raw burstiness is computed from every inter arrival gap, including gaps of",
        "minutes produced by several satellites observing one cell on one overpass.",
        "The corrected column uses gaps between distinct observation days, computed",
        "within an ingest window so no gap spans the holes between windows.",
        "",
        "Reported under two industrial definitions, because the conclusion reverses",
        "between them. The label of record adds GEM assets to OpenStreetMap industrial",
        "features; the narrower variant uses OpenStreetMap alone. Flare is identical in",
        "both, since the flare rule does not involve either source.",
    ]
    for title, _ in VARIANTS:
        result = results[title]
        print(f"\n=== {title} ===")
        lines += [
            "",
            f"## {title}",
            "",
            "| Class | Burst raw | Burst by day | Det per cell | Median day gap | Cells |",
            "|---|---|---|---|---|---|",
        ]
        for name in CLASS_ORDER:
            raw_text = summarise(result["raw_burst"][name])
            day_text = summarise(result["day_burst"][name])
            n_text = summarise(result["per_cell_n"][name])
            gap_text = summarise(result["day_gap_median"][name])
            count = len(result["day_burst"][name])
            print(
                f"{name:14s} {raw_text:>9s} {day_text:>9s} {n_text:>10s} {gap_text:>10s} {count:7d}"
            )
            lines.append(f"| {name} | {raw_text} | {day_text} | {n_text} | {gap_text} | {count} |")
        # Emitted as its own quantity rather than left as a subtraction of two
        # rounded cells, which is how 0.0075 was once published as 0.007. D104.
        separation = result["separation"]
        separation_text = "not measured" if separation is None else f"{separation:.4f}"
        print(f"corrected burstiness separation, flare against industrial: {separation_text}")
        lines += [
            "",
            f"Corrected burstiness separation between flare and industrial: **{separation_text}**.",
        ]

    canonical = results[VARIANTS[0][0]]["separation"]
    narrow = results[VARIANTS[1][0]]["separation"]
    if canonical is not None and narrow is not None:
        ratio = canonical / narrow if narrow else None
        lines += [
            "",
            "## Sensitivity",
            "",
            f"The separation is {canonical:.4f} under the label of record and "
            f"{narrow:.4f} under the narrower variant"
            + (f", a factor of {ratio:.1f}." if ratio else ".")
            + " A conclusion about the excitation term that holds under one industrial",
            "definition and not the other is not a conclusion about the excitation term.",
            "What this measures is how far a per cell summary over weak labels can be",
            "moved by the definition of one class.",
        ]

    flare_strata = results[VARIANTS[0][0]]["flare_strata"]
    print("\n=== flare audit, stratified by distance to the nearest EOG coordinate ===")
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
        print(f"{stratum:14s} {count:6d} {summarise(bucket['burstiness_day']):>10s}")
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
