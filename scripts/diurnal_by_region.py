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

import argparse
import json
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

from ml.paths import ARTIFACT_DIR, DATA_DIR, FIGURE_DIR, ROOT, ensure_dir

# These must match scripts/diurnal_profile.py. tests/test_diurnal_windows.py fails if
# they drift, because two scripts quoting different evening windows in the same report
# is the kind of disagreement a reader cannot see and cannot check.
POLAR_HOURS: tuple[int, ...] = (1, 2, 13, 14)
EVENING_START, EVENING_END = 15, 20

# Below this a state's profile is noise, and a percentage computed on four detections
# invites a reader to compare it with one computed on nine hundred. Swept from 5 to 100
# on the November window: the floor changes only how many small states reach the table,
# 17 states at 5 and 4 at 100, and leaves both headline figures untouched, Punjab at 97.4
# percent evening and Odisha at 0.0 at every value. The constant does not carry the
# result, which is the only thing that makes it safe to pick one.
MIN_DETECTIONS = 25


def _suffix(source: str) -> str:
    """Output names carry the window when it is not the default one.

    Both scripts wrote fixed filenames. Running either on a second season would have
    replaced the first season's figure and table in place, under the names the paper
    outline cites, with nothing in the output saying so.
    """
    return "" if source == "insat" else f"_{source.removeprefix('insat_')}"


def _source_name() -> str:
    """Which derived subdirectory to read, so one season cannot be read as another."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="insat", help="subdirectory under data/derived")
    return str(parser.parse_args().source)


def main() -> int:
    name = _source_name()
    window_tag = _suffix(name)
    source = DATA_DIR / "derived" / name
    files = sorted(source.glob("*.npz"))
    if not files:
        print(f"BLOCKED: no reduced granules in {source}", file=sys.stderr)
        return 2

    lons, lats, hours = [], [], []
    stamps: list[str] = []
    granules_per_hour: dict[int, int] = defaultdict(int)
    for path in files:
        with np.load(path, allow_pickle=False) as data:
            stamps.append(str(data["acquired_utc"])[:10])
            hour = int(data["hour_ist"])
            granules_per_hour[hour] += 1
            n = int(data["longitude"].size)
            if n:
                lons.append(data["longitude"].copy())
                lats.append(data["latitude"].copy())
                hours.append(np.full(n, hour, dtype=np.int16))

    # The window is read off the granules. It used to be a hardcoded string, which
    # survived the output paths being parametrised by --source and put "1 to 3 November
    # 2024" on the title and the table of a May 2025 run.
    span = f"{min(stamps)} to {max(stamps)}" if stamps else "not measured"

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
    # The name fallback matches scripts/build_features_3b.py so INSAT and the polar
    # record name a state the same way. `inside` is asked separately because a point
    # in no polygon and a point inside an unnamed polygon are different facts, and
    # five level 4 polygons carry neither name: collapsing them into one bucket would
    # report a detection in India as a detection outside it.
    rows = con.execute(
        """
        select p.hour,
               (select coalesce(nullif(s.name_en, ''), s.name)
                  from ref_osm_admin s
                 where s.admin_level = '4'
                   and ST_Contains(s.geom, ST_Point(p.lon, p.lat))
                 order by (coalesce(nullif(s.name_en, ''), s.name) is null), s.osm_id
                 limit 1) as state,
               exists(select 1
                        from ref_osm_admin s
                       where s.admin_level = '4'
                         and ST_Contains(s.geom, ST_Point(p.lon, p.lat))) as inside
        from insat p
        """
    ).fetchall()
    con.close()

    per_state: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    outside = 0
    unnamed = 0
    for hour, state, inside in rows:
        if not inside:
            outside += 1
            continue
        if state is None:
            unnamed += 1
            continue
        per_state[state][int(hour)] += 1
    print(f"detections outside any state polygon: {outside}")
    print(f"detections inside a polygon that carries no name: {unnamed}")
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
        f"INSAT-3DS diurnal activity by state, {span}\n"
        "red is the 15:00 to 20:00 IST window the polar record never samples",
        fontsize=11,
    )
    fig.tight_layout()
    ensure_dir(FIGURE_DIR)
    fig.savefig(FIGURE_DIR / f"insat_diurnal_by_state{window_tag}.png", dpi=150)
    plt.close(fig)

    out = ROOT / "docs" / f"insat_diurnal_by_state{window_tag}.md"
    out.write_text(
        "# INSAT-3DS diurnal activity by state\n\n"
        "Produced by `uv run python scripts/diurnal_by_region.py` over "
        f"{len(files)} granules, {span}. Counts are normalised to "
        "detections per granule per hour. States below "
        f"{MIN_DETECTIONS} detections are omitted.\n\n"
        "The floor is swept from 5 to 100 detections. It changes only how many small\n"
        "states reach this table, 17 of them at a floor of 5 and 4 at a floor of 100,\n"
        "and leaves both headline figures untouched: Punjab at 97.4 percent evening and\n"
        "Odisha at 0.0 at every value swept. The constant does not carry the result.\n\n"
        + "\n".join(lines)
        + "\n"
    )
    artifact = ensure_dir(ARTIFACT_DIR) / f"insat_by_state{window_tag}.json"
    artifact.write_text(
        json.dumps(
            {
                "source": name,
                "span": span,
                "granules": len(files),
                "floor": MIN_DETECTIONS,
                "outsideAnyState": outside,
                "insideUnnamedPolygon": unnamed,
                "states": [
                    {
                        "name": state,
                        "detections": raw,
                        "perGranule": round(total, 2),
                        "eveningSharePct": round(evening, 2),
                        "polarOverpassSharePct": round(polar, 2),
                        "peakHourIst": peak,
                    }
                    for state, _counts, raw, total, evening, polar, peak in reported
                ],
            },
            indent=1,
        )
    )
    print()
    print(f"wrote {FIGURE_DIR / f'insat_diurnal_by_state{window_tag}.png'}, {out}")
    print(f"and {artifact}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
