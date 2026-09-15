#!/usr/bin/env python3
"""The INSAT-3DS diurnal profile split by state.

The overall profile says half the activity sits in a window the polar record never
samples. That is a national average, and an average over a country this size can be
produced two ways: every region shifting its burning into the evening, or one region
dominating the count. Those imply different things about whether a geostationary
sensor is needed everywhere or only over the Indo Gangetic plain, so the split is
worth measuring rather than assuming.

Counts are normalised to detections per granule per hour, because the run has 6
granules in most hours and 2 in the 23:00 hour, and a raw count would read that
coverage gap as a drop in activity.

Usage:
    uv run python scripts/diurnal_by_region.py
"""

import sys
from collections import defaultdict
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt

from ml.paths import DATA_DIR, FIGURE_DIR, ROOT, ensure_dir

# These must match scripts/diurnal_profile.py. tests/test_diurnal_windows.py fails if
# they drift, because two scripts quoting different evening windows in the same report
# is the kind of disagreement a reader cannot see and cannot check.
POLAR_HOURS: tuple[int, ...] = (1, 2, 13, 14)
EVENING_START, EVENING_END = 15, 20

# Below this a state's profile is noise, and a percentage computed on four detections
# invites a reader to compare it with one computed on nine hundred.
MIN_DETECTIONS = 25


def main() -> int:
    source = DATA_DIR / "derived" / "insat"
    files = sorted(source.glob("*.npz"))
    if not files:
        print(f"BLOCKED: no reduced granules in {source}", file=sys.stderr)
        return 2

    lons, lats, hours = [], [], []
    granules_per_hour: dict[int, int] = defaultdict(int)
    for path in files:
        with np.load(path, allow_pickle=False) as data:
            hour = int(data["hour_ist"])
            granules_per_hour[hour] += 1
            n = int(data["longitude"].size)
            if n:
                lons.append(data["longitude"].copy())
                lats.append(data["latitude"].copy())
                hours.append(np.full(n, hour, dtype=np.int16))

    frame = pd.DataFrame(
        {
            "lon": np.concatenate(lons).astype(np.float64),
            "lat": np.concatenate(lats).astype(np.float64),
            "hour": np.concatenate(hours),
        }
    )
    print(f"granules {len(files)}, detections {len(frame)}")

    con = duckdb.connect(str(DATA_DIR / "agninetra.duckdb"), read_only=True)
    con.execute("install spatial; load spatial;")
    con.register("insat", frame)
    rows = con.execute(
        """
        select p.hour,
               (select coalesce(s.name_en, s.name)
                  from ref_osm_admin s
                 where s.admin_level = '4'
                   and ST_Contains(s.geom, ST_Point(p.lon, p.lat))
                 limit 1) as state
        from insat p
        """
    ).fetchall()
    con.close()

    per_state: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    offshore = 0
    for hour, state in rows:
        if state is None:
            offshore += 1
            continue
        per_state[state][int(hour)] += 1
    print(f"detections outside any state polygon: {offshore}")
    print()

    def shares(counts: dict[int, int]) -> tuple[float, float, float, int]:
        """Total, evening share, polar share, peak hour, all per granule normalised."""
        rate = {
            h: counts.get(h, 0) / granules_per_hour[h]
            for h in granules_per_hour
            if granules_per_hour[h]
        }
        total = sum(rate.values())
        if total <= 0.0:
            return 0.0, float("nan"), float("nan"), -1
        evening = sum(v for h, v in rate.items() if EVENING_START <= h < EVENING_END)
        polar = sum(v for h, v in rate.items() if h in POLAR_HOURS)
        peak = max(rate, key=lambda h: rate[h])
        return total, 100.0 * evening / total, 100.0 * polar / total, peak

    ranked = sorted(per_state.items(), key=lambda kv: -sum(kv[1].values()))
    lines = [
        "| State | detections | per granule | evening 15 to 20 IST | polar hours | peak IST |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    print("  state                    det   per gran   evening   polar   peak IST")
    reported = []
    for state, counts in ranked:
        raw = sum(counts.values())
        if raw < MIN_DETECTIONS:
            continue
        total, evening, polar, peak = shares(counts)
        reported.append((state, counts, raw, total, evening, polar, peak))
        print(
            f"  {state:22s} {raw:6d}   {total:8.1f}   {evening:6.1f}%  {polar:5.1f}%   {peak:02d}h"
        )
        lines.append(
            f"| {state} | {raw} | {total:.1f} | {evening:.1f}% | {polar:.1f}% | {peak:02d}h |"
        )

    dropped = sum(sum(c.values()) for s, c in ranked if sum(c.values()) < MIN_DETECTIONS)
    n_dropped = sum(1 for s, c in ranked if sum(c.values()) < MIN_DETECTIONS)
    print()
    print(f"states with at least {MIN_DETECTIONS} detections: {len(reported)}")
    print(f"states below the floor: {n_dropped}, holding {dropped} detections")

    if not reported:
        print("BLOCKED: no state clears the floor", file=sys.stderr)
        return 2

    top = reported[:6]
    fig, axes = plt.subplots(2, 3, figsize=(13, 6), sharex=True)
    for ax, (state, counts, raw, _total, evening, _polar, _peak) in zip(
        axes.ravel(), top, strict=False
    ):
        rate = [counts.get(h, 0) / granules_per_hour.get(h, 1) for h in range(24)]
        colours = ["#b3122b" if EVENING_START <= h < EVENING_END else "#3b3b3b" for h in range(24)]
        ax.bar(range(24), rate, color=colours)
        ax.set_title(f"{state}, {raw} detections, {evening:.0f}% evening", fontsize=10)
        ax.set_xticks(range(0, 24, 6))
    for ax in axes[1]:
        ax.set_xlabel("hour, IST")
    for ax in axes[:, 0]:
        ax.set_ylabel("detections per granule")
    fig.suptitle(
        "INSAT-3DS diurnal activity by state, 1 to 3 November 2024\n"
        "red is the 15:00 to 20:00 IST window the polar record never samples",
        fontsize=11,
    )
    fig.tight_layout()
    ensure_dir(FIGURE_DIR)
    fig.savefig(FIGURE_DIR / "insat_diurnal_by_state.png", dpi=150)
    plt.close(fig)

    out = ROOT / "docs" / "insat_diurnal_by_state.md"
    out.write_text(
        "# INSAT-3DS diurnal activity by state\n\n"
        "Produced by `uv run python scripts/diurnal_by_region.py` over "
        f"{len(files)} granules, 1 to 3 November 2024. Counts are normalised to "
        "detections per granule per hour. States below "
        f"{MIN_DETECTIONS} detections are omitted.\n\n" + "\n".join(lines) + "\n"
    )
    print()
    print(f"wrote {FIGURE_DIR / 'insat_diurnal_by_state.png'} and {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
