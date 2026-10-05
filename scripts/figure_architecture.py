#!/usr/bin/env python3
"""Draw the pipeline architecture, with every count queried rather than typed.

A hand drawn architecture diagram is a claim with no source, and it goes stale the
first time a stage changes. This one reads its row counts from the database and its
artifact list from disk, so a stage that grows, shrinks or disappears changes the
figure. The layout is the only part that is authored.

Usage:
    uv run python scripts/figure_architecture.py
"""

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import duckdb

from ml.paths import ARTIFACT_DIR, DUCKDB_PATH, ROOT

FIG = ROOT / "docs" / "figures"
OUT = FIG / "architecture.png"
SUMMARY = ARTIFACT_DIR / "architecture.json"

INK = "#1b1b1b"
MUTED = "#6b6b6b"
FILL = "#f4f1ea"
EDGE = "#b9b2a4"


def counts(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    wanted = (
        "detections",
        "detection_context",
        "detection_recurrence",
        "detection_gem",
        "ref_flares",
        "ref_osm_industrial",
        "ref_gem_assets",
        "ref_osm_admin",
    )
    present = {
        row[0] for row in con.execute("SELECT table_name FROM information_schema.tables").fetchall()
    }
    return {
        name: int(con.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0])
        for name in wanted
        if name in present
    }


def granule_count() -> dict[str, int]:
    derived = ROOT / "data" / "derived"
    if not derived.is_dir():
        return {}
    # A `_pre_` folder is a superseded run kept for comparison, the same granules reduced
    # before a fix; counting it would count those granules twice, as 400 against 270 did.
    return {
        d.name: len(list(d.glob("*.npz")))
        for d in sorted(derived.iterdir())
        if d.is_dir() and "_pre_" not in d.name
    }


def main() -> int:
    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    rows = counts(con)
    granules = granule_count()
    artifacts = sorted(p.name for p in ARTIFACT_DIR.glob("*.json"))
    figures = sorted(p.name for p in FIG.glob("*.png"))

    stages = [
        (
            "Ingest",
            [
                f"FIRMS detections {rows.get('detections', 0):,}",
                f"INSAT granules {sum(granules.values())}",
            ],
        ),
        (
            "Reference",
            [
                f"EOG flares {rows.get('ref_flares', 0):,}",
                f"OSM industrial {rows.get('ref_osm_industrial', 0):,}",
                f"GEM assets {rows.get('ref_gem_assets', 0):,}",
                f"State polygons {rows.get('ref_osm_admin', 0):,}",
            ],
        ),
        (
            "Context and labels",
            [
                f"Joined rows {rows.get('detection_context', 0):,}",
                "Weak label by spatial rule",
                "flare, industrial, agricultural",
            ],
        ),
        (
            "Features",
            [
                f"Recurrence rows {rows.get('detection_recurrence', 0):,}",
                "18 columns, 4 time derived",
            ],
        ),
        (
            "Models and evaluation",
            [
                "B1 gradient boosted trees",
                "Spatially blocked, 3 groups",
                "Conformal and applicability",
            ],
        ),
        (
            "Outputs",
            [
                f"Artifacts {len(artifacts)}",
                f"Figures {len(figures)}",
                "Console, precomputed only",
            ],
        ),
    ]

    fig, ax = plt.subplots(figsize=(14.5, 3.5))
    ax.set_xlim(0, len(stages) * 10)
    ax.set_ylim(0, 10)
    ax.axis("off")

    for index, (title, lines) in enumerate(stages):
        x = index * 10 + 0.6
        box = mpatches.FancyBboxPatch(
            (x, 2.6),
            8.8,
            5.2,
            boxstyle="round,pad=0.25,rounding_size=0.35",
            linewidth=1.1,
            edgecolor=EDGE,
            facecolor=FILL,
        )
        ax.add_patch(box)
        # Sized from the label's own length so a longer stage name cannot overrun
        # its box, which is what happened to "Models and evaluation" at a fixed size.
        ax.text(
            x + 4.4,
            7.05,
            title,
            ha="center",
            va="center",
            fontsize=10.0 if len(title) <= 18 else 8.9,
            color=INK,
            fontweight="bold",
        )
        for line_index, line in enumerate(lines):
            ax.text(
                x + 4.4,
                6.05 - line_index * 0.78,
                line,
                ha="center",
                va="center",
                fontsize=8.0,
                color=MUTED,
            )
        if index < len(stages) - 1:
            ax.annotate(
                "",
                xy=(x + 9.9, 5.2),
                xytext=(x + 9.5, 5.2),
                arrowprops={"arrowstyle": "-|>", "color": EDGE, "linewidth": 1.2},
            )

    ax.text(
        0.6,
        1.3,
        "Every count queried at draw time from the database and from disk. "
        "Regenerate: uv run python scripts/figure_architecture.py",
        ha="left",
        va="center",
        fontsize=7.6,
        color=MUTED,
    )
    SUMMARY.write_text(
        json.dumps(
            {
                "table_rows": rows,
                "granules_by_source": granules,
                "artifact_count": len(artifacts),
                "figure_count": len(figures),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    fig.tight_layout()
    fig.savefig(OUT, dpi=170)
    plt.close(fig)

    print(f"wrote {OUT.relative_to(ROOT)} and {SUMMARY.relative_to(ROOT)}")
    for name, value in rows.items():
        print(f"  {name}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
