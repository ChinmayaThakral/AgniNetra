#!/usr/bin/env python3
"""Figure: OSM industrial feature density by state.

The figure carries the snapshot date and sequence number in its caption because
OpenStreetMap is a moving target and the numbers mean nothing without them.

Arunachal Pradesh is drawn as an explicit absent bar rather than omitted. A state
missing from a coverage chart reads as zero coverage; this one has no boundary in
the extract at all, which is a different fact and the one that matters.

Usage:
    uv run python scripts/figure_coverage_density.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from ml.paths import DUCKDB_PATH, ROOT, ensure_dir
from ml.reference.geo import install_geo

OUT = ROOT / "docs" / "figures" / "osm_coverage_density.png"
SNAPSHOT = "OSM snapshot 2026-09-02T20:20:51Z, Geofabrik sequence 4895"

# Border artefacts and enclaves, not states. Excluded from the figure and the
# exclusion is stated in the caption rather than left silent.
NOT_STATES = {
    "Karnataka - Maharashtra border",
    "Maghval - Nagar Haveli border",
    "Kaduvanur (Puducherry)",
    "Nettapakkam (Puducherry)",
}

SQL = """
SELECT coalesce(nullif(s.name_en, ''), s.name) AS state_name,
       count(i.osm_id) AS features,
       geo_area_km2(s.geom) AS area_km2
FROM ref_osm_admin s
LEFT JOIN ref_osm_industrial i
  ON ST_Contains(s.geom, ST_Point(i.longitude, i.latitude))
WHERE s.admin_level = '4'
  AND coalesce(nullif(s.name_en, ''), s.name) IS NOT NULL
GROUP BY 1, s.geom
"""


def ascii_only(value: str) -> str:
    return value.translate({0x2013: "-", 0x2014: "-", 0x2018: "'", 0x2019: "'"})


def main() -> int:
    con = duckdb.connect(str(DUCKDB_PATH))
    install_geo(con)
    rows = [
        (ascii_only(str(r[0])), int(r[1]), float(r[2]))
        for r in con.execute(SQL).fetchall()
        if ascii_only(str(r[0])) not in NOT_STATES and r[2] and float(r[2]) > 0
    ]
    data = sorted(
        ((name, 1000.0 * features / area, features) for name, features, area in rows),
        key=lambda item: item[1],
    )

    names = [d[0] for d in data]
    density = [d[1] for d in data]
    counts = [d[2] for d in data]

    # Arunachal Pradesh has no polygon, so it has no density. It is drawn at the
    # bottom as a distinct absent bar.
    names = ["Arunachal Pradesh", *names]
    density = [0.0, *density]
    counts = [0, *counts]

    median = sorted(d for d in density[1:])[len(density[1:]) // 2]
    colours = ["#b00020"] + [
        "#c46210" if value < 2.0 else "#2b6cb0" if value < median else "#3f7f4f"
        for value in density[1:]
    ]

    fig, ax = plt.subplots(figsize=(9, 11))
    bars = ax.barh(range(len(names)), density, color=colours, height=0.72)
    ax.set_yticks(range(len(names)))
    ax.set_yticklabels(names, fontsize=8.5)
    ax.set_xscale("symlog", linthresh=0.1)
    ax.set_xlabel("OSM industrial features per 1000 square kilometres, log scale")
    ax.set_title(
        "Industrial reference coverage is uneven across India",
        fontsize=13,
        pad=14,
        loc="left",
    )
    ax.axvline(median, color="#666666", linestyle=":", linewidth=1)
    ax.text(median, len(names) - 0.2, f" median {median:.1f}", fontsize=8, color="#666666")

    for index, (bar, value, count) in enumerate(zip(bars, density, counts, strict=True)):
        if index == 0:
            ax.text(
                0.02,
                bar.get_y() + bar.get_height() / 2,
                "  no boundary in the extract, density undefined",
                va="center",
                fontsize=8,
                color="#b00020",
            )
        else:
            ax.text(
                value * 1.12,
                bar.get_y() + bar.get_height() / 2,
                f"{value:.1f}  ({count})",
                va="center",
                fontsize=7.5,
                color="#333333",
            )

    ax.set_xlim(left=0)
    ax.margins(y=0.01)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)

    caption = (
        f"{SNAPSHOT}. Tags: landuse=industrial, man_made=works, man_made=flare, "
        "power=plant.\n"
        "34911 features, 207 outside every state polygon. Bar label is density, "
        "with the raw feature count in brackets.\n"
        "Four border artefacts and enclaves excluded. Arunachal Pradesh has no "
        "boundary at any administrative level, so its\ndensity is undefined rather "
        "than zero. Density is two measured quantities, not a smoothed value."
    )
    fig.text(0.01, 0.005, caption, fontsize=7.4, color="#444444", va="bottom")
    fig.tight_layout(rect=(0, 0.058, 1, 1))

    ensure_dir(OUT.parent)
    fig.savefig(OUT, dpi=200)
    print(f"written to {OUT}")
    print(f"states plotted: {len(names) - 1}, plus Arunachal Pradesh as absent")
    print(f"median density: {median:.2f} per 1000 km2")
    print(f"range: {density[1]:.2f} to {density[-1]:.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
