"""Compare two directories of reduced INSAT-3DS granules, hour by hour.

A change to the detector makes every previously reduced granule stale. This states
what the change did across a whole run rather than on the handful of granules a
threshold was swept on, which is the difference between a measured effect and an
extrapolated one.

Granules are matched by filename, so a slot present in one directory and missing
from the other is reported rather than quietly dropped.
"""

import argparse
import sys
from pathlib import Path

import numpy as np

BOX = (73.5, 77.5, 28.5, 32.5)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    return parser.parse_args()


def _load(path: Path) -> tuple[int, int, int]:
    """Detections, detections inside the stubble box, and the IST hour."""
    with np.load(path, allow_pickle=False) as data:
        lon, lat = data["longitude"], data["latitude"]
        inside = (lon > BOX[0]) & (lon < BOX[1]) & (lat > BOX[2]) & (lat < BOX[3])
        return len(lon), int(inside.sum()), int(data["hour_ist"])


def main() -> int:
    args = parse_args()
    before = {p.name: p for p in args.before.glob("*.npz")}
    after = {p.name: p for p in args.after.glob("*.npz")}
    if not before or not after:
        print("BLOCKED: one of the directories holds no npz files", file=sys.stderr)
        return 2

    only_before = sorted(set(before) - set(after))
    only_after = sorted(set(after) - set(before))
    for name in only_before:
        print(f"  present before, missing after: {name}", file=sys.stderr)
    for name in only_after:
        print(f"  new after: {name}", file=sys.stderr)

    hours: dict[int, list[int]] = {}
    for name in sorted(set(before) & set(after)):
        b_total, b_box, hour = _load(before[name])
        a_total, a_box, _ = _load(after[name])
        row = hours.setdefault(hour, [0, 0, 0, 0, 0])
        row[0] += b_total
        row[1] += a_total
        row[2] += b_box
        row[3] += a_box
        row[4] += 1

    print(f"{len(set(before) & set(after))} granules in both directories")
    print()
    print("  IST   granules    before     after    change     box before   box after")
    totals = [0, 0, 0, 0]
    for hour in sorted(hours):
        b_total, a_total, b_box, a_box, n = hours[hour]
        totals[0] += b_total
        totals[1] += a_total
        totals[2] += b_box
        totals[3] += a_box
        pct = f"{100.0 * (a_total - b_total) / b_total:+6.1f}%" if b_total else "     ."
        print(
            f"  {hour:02d}h   {n:6d}   {b_total:7d}   {a_total:7d}   {pct}   "
            f"{b_box:9d}   {a_box:9d}"
        )
    print(
        f"  total          {totals[0]:7d}   {totals[1]:7d}             "
        f"{totals[2]:9d}   {totals[3]:9d}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
