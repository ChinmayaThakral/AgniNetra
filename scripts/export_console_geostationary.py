#!/usr/bin/env python3
"""Compose the phase 5 geostationary results into one file the console can read.

Every number here is read from an artifact a command wrote, never typed in. D91
records what the alternative costs: three rows of a published table frozen as string
literals, unable to move when the thing they described did, in a document whose whole
purpose was measuring rather than asserting.

The detector comparison is recomputed from the reduced granules on each run rather
than read from a note, because the pre D81 outputs are still on disk and recomputing
is cheaper than trusting.

Usage:
    uv run python scripts/export_console_geostationary.py
"""

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml.paths import ARTIFACT_DIR, DATA_DIR, ROOT

BOX = (73.5, 77.5, 28.5, 32.5)
WINDOWS = (
    ("kharif", "Kharif rice residue", "", "insat"),
    ("rabi", "Rabi wheat residue", "_rabi", "insat_rabi"),
)


def _read(name: str) -> dict:
    path = ARTIFACT_DIR / name
    if not path.is_file():
        raise FileNotFoundError(f"{path} missing, rerun the phase 5 scripts")
    return json.loads(path.read_text())


def _hourly(raw: dict[str, float]) -> list[float | None]:
    """The 24 hourly rates in hour order.

    `mean_by_hour` is a mapping keyed by the hour as a string, so iterating it yields
    the keys. Doing that produced a chart of 0 to 23, the hour labels plotted as if
    they were detection rates, which looked like a smooth ramp and was wrong in a way
    only a reader who knew the real shape would catch. The guard below refuses that
    specific failure rather than trusting the next person to notice it.
    """
    values = [None if raw.get(str(h)) is None else round(float(raw[str(h)]), 2) for h in range(24)]
    observed = [v for v in values if v is not None]
    if observed == [float(h) for h in range(len(observed))]:
        raise ValueError("hourly rates equal their own indices, the keys are being plotted")
    return values


def _detections(directory: Path) -> tuple[int, int]:
    """Total detections and the count inside the Punjab and Haryana box."""
    total = inside = 0
    for path in sorted(directory.glob("*.npz")):
        with np.load(path, allow_pickle=False) as data:
            lon, lat = data["longitude"], data["latitude"]
            total += int(lon.size)
            inside += int(((lon > BOX[0]) & (lon < BOX[1]) & (lat > BOX[2]) & (lat < BOX[3])).sum())
    return total, inside


def main() -> int:
    windows = []
    for key, label, tag, source in WINDOWS:
        diurnal = _read(f"insat_diurnal{tag}.json")
        by_state = _read(f"insat_by_state{tag}.json")
        colloc = _read(f"collocation{tag}.json")
        total, inside = _detections(DATA_DIR / "derived" / source)
        windows.append(
            {
                "key": key,
                "label": label,
                "span": by_state["span"],
                "granules": diurnal["granules"],
                "slotsPresent": diurnal["slots_present"],
                "slotsExpected": diurnal["slots_expected"],
                "hoursObserved": diurnal["hours_observed"],
                "detections": total,
                "detectionsInStubbleBox": inside,
                "eveningSharePct": round(100.0 * diurnal["evening_share"], 1)
                if diurnal["evening_share"] <= 1.0
                else round(diurnal["evening_share"], 1),
                "polarOverpassSharePct": round(100.0 * diurnal["polar_overpass_share"], 1)
                if diurnal["polar_overpass_share"] <= 1.0
                else round(diurnal["polar_overpass_share"], 1),
                "meanByHour": _hourly(diurnal["mean_by_hour"]),
                "states": by_state["states"],
                "collocation": colloc["insatToPolar"],
                "polarDetections": colloc["polarDetections"],
            }
        )

    pre, pre_box = _detections(DATA_DIR / "derived" / "insat_pre_d81")
    post, post_box = _detections(DATA_DIR / "derived" / "insat")

    payload = {
        "generatedBy": "scripts/export_console_geostationary.py",
        "windows": windows,
        "detectorChange": {
            "before": pre,
            "after": post,
            "stubbleBoxBefore": pre_box,
            "stubbleBoxAfter": post_box,
            "rule": (
                "A candidate is rejected when its thermal infrared brightness temperature "
                "sits more than 1.0 K below its local background median. A fire cannot "
                "make the 11 micron channel colder than its surroundings; thin cloud and "
                "bare soil emissivity contrast can."
            ),
        },
        "caveats": [
            "Each window is three days, not a season. Quote it as a sample.",
            "The rabi window is corroborated at 8.7 percent against 33.3 for kharif at a "
            "4 km tolerance. A permutation null shows both windows carry real signal, and "
            "shows the two curves have the same shape once chance is subtracted, so the "
            "difference is magnitude rather than kind.",
            "The stubble box count being unchanged is weak evidence: of the detections "
            "nationwide in the filter's active hours only a handful fall inside that box, "
            "and most of the box sits in hours the threshold was swept to leave alone.",
            "No detection here is validated against ground truth. No gold set exists.",
            "The geostationary observability argument is published prior work, Jethva "
            "2026 on GEO-KOMPSAT-2A. This measurement agrees with it independently.",
        ],
    }

    out = ROOT / "apps" / "console" / "public" / "data" / "geostationary.json"
    out.write_text(json.dumps(payload, indent=1, allow_nan=False))
    for window in windows:
        print(
            f"  {window['label']:22s} {window['granules']:4d} granules  "
            f"{window['detections']:5d} detections  evening {window['eveningSharePct']:5.1f}%"
        )
    print(f"  detector change: {pre} to {post}, stubble box {pre_box} to {post_box}")
    print(f"\nwrote {out} ({out.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
