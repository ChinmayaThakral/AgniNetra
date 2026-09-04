#!/usr/bin/env python3
"""M1 prototype: are the four class conditional recurrence signatures separable?

This is not KAALCHAKRA. It fits nothing and it estimates no intensity function. It
measures the empirical recurrence statistics that the four class conditional
intensity families in PHASE_6 are supposed to differ in, per weak label class, at
one state. If the classes are not separable in these statistics then a latent class
point process has nothing to find and phase 6 needs rethinking before it is built,
not after.

The precondition being tested, stated as the dossier states it:

  flare         near homogeneous Poisson, high rate, tight mark, nightly, year round
  industrial    periodic with campaign structure, moderate rate
  agricultural  sharp seasonal envelope, strong diurnal concentration, zero out of
                season, self exciting within a season
  wildfire      bursty, rapid decay, short lifetime, no inter annual recurrence

Wildfire has no weak label any more, D33, so it is examined through the unlabelled
residue, which is where the wildfire population now sits.

Gujarat is used because it is the only state carrying all regimes at volume: 838
flare, 5847 industrial and 3713 agricultural labelled detections over 2156 cells.

Usage:
    uv run python scripts/m1_prototype_gujarat.py
"""

import statistics
import sys
from collections import defaultdict
from itertools import pairwise
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from ml.features.recurrence import CELL_DEGREES
from ml.paths import DUCKDB_PATH, ROOT, ensure_dir

STATE = "Gujarat"
OUT_FIG = ROOT / "docs" / "figures" / "m1_intensity_signatures.png"
OUT_DOC = ROOT / "docs" / "m1_prototype.md"

CLASS_ORDER = ("flare", "industrial", "agricultural", "unlabelled")
COLOURS = {
    "flare": "#b00020",
    "industrial": "#c46210",
    "agricultural": "#3f7f4f",
    "unlabelled": "#2b6cb0",
}

SEASON_2023 = ("2023-10-01", "2023-11-30")
SEASON_2024 = ("2024-10-01", "2024-11-30")
MONSOON = ("2026-06-06", "2026-09-03")

SQL = f"""
SELECT c.weak_label,
       floor(d.longitude / {CELL_DEGREES}) AS cx,
       floor(d.latitude  / {CELL_DEGREES}) AS cy,
       d.acq_ts_utc,
       d.acq_hour_ist,
       d.daynight,
       d.frp,
       d.acq_date_ist
FROM detections d
JOIN detection_context c USING (detection_id)
WHERE c.state_name = ?
ORDER BY cx, cy, d.acq_ts_utc
"""


def main() -> int:
    con = duckdb.connect(str(DUCKDB_PATH))
    rows = con.execute(SQL, [STATE]).fetchall()
    print(f"{STATE}: {len(rows)} detections")

    # Group by cell. A cell's class is the majority weak label of its detections,
    # because the signature belongs to the location rather than to one detection.
    cells: dict[tuple[float, float], list] = defaultdict(list)
    for row in rows:
        cells[(row[1], row[2])].append(row)
    print(f"cells: {len(cells)}")

    stats: dict[str, dict[str, list[float]]] = {
        name: {
            "gap_days": [],
            "rate_per_active_day": [],
            "night_fraction": [],
            "season_share": [],
            "frp_cv": [],
            "burstiness": [],
        }
        for name in CLASS_ORDER
    }
    interannual: dict[str, list[int]] = {name: [] for name in CLASS_ORDER}

    for events in cells.values():
        if len(events) < 4:
            continue
        labels = [e[0] for e in events]
        cell_class = max(set(labels), key=labels.count)
        if cell_class not in stats:
            continue
        bucket = stats[cell_class]

        times = sorted(e[3] for e in events)
        gaps = [(later - earlier).total_seconds() / 86400.0 for earlier, later in pairwise(times)]
        gaps = [g for g in gaps if g > 0]
        if gaps:
            bucket["gap_days"].extend(gaps)
            # Burstiness coefficient: (sd - mean) / (sd + mean). Zero for a Poisson
            # process, positive for bursty, negative for regular.
            if len(gaps) > 1:
                mean_gap = statistics.mean(gaps)
                sd_gap = statistics.pstdev(gaps)
                if mean_gap + sd_gap > 0:
                    bucket["burstiness"].append((sd_gap - mean_gap) / (sd_gap + mean_gap))

        active_days = len({e[7] for e in events})
        bucket["rate_per_active_day"].append(len(events) / active_days)

        nights = sum(1 for e in events if e[5] == "N")
        bucket["night_fraction"].append(nights / len(events))

        in_season = sum(
            1
            for e in events
            if SEASON_2023[0] <= str(e[7]) <= SEASON_2023[1]
            or SEASON_2024[0] <= str(e[7]) <= SEASON_2024[1]
        )
        bucket["season_share"].append(in_season / len(events))

        frps = [float(e[6]) for e in events if e[6] is not None and float(e[6]) > 0]
        if len(frps) > 2:
            mean_frp = statistics.mean(frps)
            if mean_frp > 0:
                bucket["frp_cv"].append(statistics.pstdev(frps) / mean_frp)

        in_2023 = any(SEASON_2023[0] <= str(e[7]) <= SEASON_2023[1] for e in events)
        in_2024 = any(SEASON_2024[0] <= str(e[7]) <= SEASON_2024[1] for e in events)
        interannual[cell_class].append(1 if (in_2023 and in_2024) else 0)

    print("\ncells per class with at least 4 detections:")
    for name in CLASS_ORDER:
        print(f"  {name:14s} {len(stats[name]['rate_per_active_day']):5d}")

    panels = [
        ("gap_days", "Inter arrival gap, days (log)", True),
        ("burstiness", "Burstiness, 0 is Poisson", False),
        ("rate_per_active_day", "Detections per active day", False),
        ("night_fraction", "Night fraction", False),
        ("season_share", "Share in burning season", False),
        ("frp_cv", "Radiative power variability, CV", False),
    ]

    fig, axes = plt.subplots(2, 3, figsize=(15, 8.5))
    for axis, (key, title, log_x) in zip(axes.flat, panels, strict=True):
        for name in CLASS_ORDER:
            values = [v for v in stats[name][key] if v is not None]
            if len(values) < 20:
                continue
            if log_x:
                values = [v for v in values if v > 0]
                bins = [10 ** (i / 6 - 2) for i in range(0, 30)]
                axis.set_xscale("log")
            else:
                bins = 30
            axis.hist(
                values,
                bins=bins,
                density=True,
                histtype="step",
                linewidth=1.9,
                color=COLOURS[name],
                label=f"{name} (n={len(values)})",
            )
        axis.set_title(title, fontsize=10, loc="left")
        axis.tick_params(labelsize=8)
        for spine in ("top", "right"):
            axis.spines[spine].set_visible(False)
    axes.flat[0].legend(fontsize=7.5, frameon=False)

    fig.suptitle(
        f"Empirical recurrence signatures by weak label class, {STATE}",
        fontsize=13,
        x=0.01,
        ha="left",
    )
    caption = (
        f"{STATE}, {len(rows)} detections over {len(cells)} cells of "
        f"{CELL_DEGREES} degrees. Cells with at least 4 detections only; a cell takes "
        "the majority weak label of its detections.\n"
        "Windows: 2023-10-01 to 2023-11-30, 2024-10-01 to 2024-11-30, 2026-06-06 to "
        "2026-09-03. Wildfire has no weak label (D33) and its population sits inside "
        "unlabelled.\n"
        "This measures whether the class conditional signatures are separable. It "
        "fits nothing and is not KAALCHAKRA."
    )
    fig.text(0.01, 0.005, caption, fontsize=7.6, color="#444444", va="bottom")
    fig.tight_layout(rect=(0, 0.075, 1, 0.96))
    ensure_dir(OUT_FIG.parent)
    fig.savefig(OUT_FIG, dpi=170)
    print(f"\nfigure written to {OUT_FIG}")

    lines = [
        "# M1 prototype: are the recurrence signatures separable?",
        "",
        "Regenerate: `uv run python scripts/m1_prototype_gujarat.py`",
        "",
        "Generated by `scripts/m1_prototype_gujarat.py`. Figure at",
        "`docs/figures/m1_intensity_signatures.png`.",
        "",
        "This fits nothing. It measures the empirical recurrence statistics the four",
        "class conditional intensity families are supposed to differ in, to find out",
        "whether a latent class point process has anything to separate before phase 6",
        "is built.",
        "",
        f"{STATE}, {len(rows)} detections, {len(cells)} cells.",
        "",
        "| Statistic | " + " | ".join(CLASS_ORDER) + " |",
        "|---|" + "---|" * len(CLASS_ORDER),
    ]
    summary: dict[str, dict[str, float]] = {}
    for key, title, _ in panels:
        cells_row = []
        for name in CLASS_ORDER:
            values = stats[name][key]
            if len(values) < 20:
                cells_row.append("too few")
                continue
            median = statistics.median(values)
            summary.setdefault(key, {})[name] = median
            cells_row.append(f"{median:.3g}")
        lines.append(f"| {title} (median) | " + " | ".join(cells_row) + " |")
    inter_row = []
    for name in CLASS_ORDER:
        values = interannual[name]
        inter_row.append(f"{sum(values) / len(values):.1%}" if len(values) >= 20 else "too few")
    lines.append("| Active in both burning seasons | " + " | ".join(inter_row) + " |")
    lines.append("")

    print("\nmedian by class:")
    for key, title, _ in panels:
        if key in summary:
            values = " ".join(
                f"{n}={summary[key].get(n, float('nan')):.3g}"
                for n in CLASS_ORDER
                if n in summary[key]
            )
            print(f"  {title:36s} {values}")
    print("\ninter annual return, active in both burning seasons:")
    for name in CLASS_ORDER:
        values = interannual[name]
        if len(values) >= 20:
            print(f"  {name:14s} {sum(values) / len(values):.1%}  (n={len(values)})")

    OUT_DOC.write_text("\n".join(lines) + "\n")
    print(f"\nwritten to {OUT_DOC}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
