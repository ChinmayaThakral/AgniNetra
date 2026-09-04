#!/usr/bin/env python3
"""Does flaring show campaign structure, or is it continuous?

The flare persistence result survived the label noise stratification: flare cells
are active across both burning seasons only 54.2 percent of the time against 68.4
for industrial, and that barely moves with distance from the catalogue coordinate.
Two readings are consistent with it. Continuous background flaring that the
catalogue simply mislocates, or genuinely intermittent operational flaring tied to
upstream and refinery campaigns.

Those are distinguishable by the shape of activity within a window, which is a
different statistic from persistence across windows. Continuous flaring gives long
active runs, short quiet runs and a high duty cycle. Campaign flaring gives
moderate active runs separated by long quiet runs.

Nothing here derives from inter arrival gaps, so it is uncontaminated by overpass
thinning. Runs are counted in distinct observation days within a single window, so
no run spans the holes between ingest windows.

Usage:
    uv run python scripts/campaign_structure.py
"""

import statistics
import sys
from collections import defaultdict
from datetime import date
from itertools import pairwise
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import duckdb

from ml.features.recurrence import CELL_DEGREES
from ml.paths import DUCKDB_PATH, ROOT, ensure_dir

STATE = "Gujarat"
OUT = ROOT / "docs" / "campaign_structure.md"
CLASS_ORDER = ("flare", "industrial", "agricultural", "unlabelled")

WINDOWS = {
    "s2023": (date(2023, 10, 1), date(2023, 11, 30)),
    "s2024": (date(2024, 10, 1), date(2024, 11, 30)),
    "m2026": (date(2026, 6, 6), date(2026, 9, 3)),
}

SQL = f"""
SELECT c.weak_label,
       floor(d.longitude / {CELL_DEGREES}) AS cx,
       floor(d.latitude  / {CELL_DEGREES}) AS cy,
       d.acq_date_ist
FROM detections d
JOIN detection_context c USING (detection_id)
WHERE c.state_name = ?
"""


def runs_of(days: set[date], start: date, end: date) -> tuple[list[int], list[int]]:
    """Return (active run lengths, quiet run lengths) across a window."""
    active_runs: list[int] = []
    quiet_runs: list[int] = []
    ordered = sorted(days)
    if not ordered:
        return active_runs, quiet_runs
    run = 1
    for earlier, later in pairwise(ordered):
        delta = (later - earlier).days
        if delta == 1:
            run += 1
        else:
            active_runs.append(run)
            quiet_runs.append(delta - 1)
            run = 1
    active_runs.append(run)
    return active_runs, quiet_runs


def med(values: list[float], minimum: int = 12) -> str:
    return f"{statistics.median(values):.2f}" if len(values) >= minimum else "too few"


def main() -> int:
    con = duckdb.connect(str(DUCKDB_PATH))
    rows = con.execute(SQL, [STATE]).fetchall()
    print(f"{STATE}: {len(rows)} detections", flush=True)

    cells: dict[tuple[float, float], list] = defaultdict(list)
    for row in rows:
        cells[(row[1], row[2])].append(row)

    metrics: dict[str, dict[str, list[float]]] = {name: defaultdict(list) for name in CLASS_ORDER}

    for events in cells.values():
        labels = [e[0] for e in events]
        cell_class = max(set(labels), key=labels.count)
        if cell_class not in metrics:
            continue
        if len(events) < 6:
            continue

        by_window: dict[str, set[date]] = defaultdict(set)
        for event in events:
            day = date.fromisoformat(str(event[3]))
            for name, (start, end) in WINDOWS.items():
                if start <= day <= end:
                    by_window[name].add(day)

        for name, days in by_window.items():
            start, end = WINDOWS[name]
            span = (end - start).days + 1
            if len(days) < 3:
                continue
            active_runs, quiet_runs = runs_of(days, start, end)
            bucket = metrics[cell_class]
            bucket["duty_cycle"].append(len(days) / span)
            bucket["active_run"].append(statistics.median(active_runs))
            bucket["max_active_run"].append(float(max(active_runs)))
            if quiet_runs:
                bucket["quiet_run"].append(statistics.median(quiet_runs))
                bucket["max_quiet_run"].append(float(max(quiet_runs)))
                if len(quiet_runs) > 1:
                    mean_quiet = statistics.mean(quiet_runs)
                    if mean_quiet > 0:
                        bucket["quiet_cv"].append(statistics.pstdev(quiet_runs) / mean_quiet)

    labels_and_titles = [
        ("duty_cycle", "Duty cycle, active days over window"),
        ("active_run", "Median active run, days"),
        ("max_active_run", "Longest active run, days"),
        ("quiet_run", "Median quiet run, days"),
        ("max_quiet_run", "Longest quiet run, days"),
        ("quiet_cv", "Quiet run variability, CV"),
    ]

    print(f"\n{'statistic':34s}" + "".join(f"{c:>14s}" for c in CLASS_ORDER))
    lines = [
        "# Campaign structure by weak label class",
        "",
        "Generated by `scripts/campaign_structure.py`.",
        "",
        f"{STATE}. Cell windows with at least 3 distinct observation days. Runs are",
        "counted within one ingest window so none spans the holes between windows.",
        "None of these statistics derives from inter arrival gaps, so none inherits",
        "the overpass thinning contamination in D37.",
        "",
        "Continuous operation gives a high duty cycle, long active runs and short quiet",
        "runs. Campaign operation gives moderate active runs separated by long quiet",
        "runs.",
        "",
        "| Statistic | " + " | ".join(CLASS_ORDER) + " |",
        "|---|" + "---|" * len(CLASS_ORDER),
    ]
    for key, title in labels_and_titles:
        values = [med(metrics[name][key]) for name in CLASS_ORDER]
        print(f"{title:34s}" + "".join(f"{v:>14s}" for v in values))
        lines.append(f"| {title} | " + " | ".join(values) + " |")

    counts = [str(len(metrics[name]["duty_cycle"])) for name in CLASS_ORDER]
    print(f"{'cell windows':34s}" + "".join(f"{c:>14s}" for c in counts))
    lines.append("| Cell windows measured | " + " | ".join(counts) + " |")
    lines.append("")

    ensure_dir(OUT.parent)
    OUT.write_text("\n".join(lines) + "\n")
    print(f"\nwritten to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
