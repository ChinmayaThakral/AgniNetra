#!/usr/bin/env python3
"""Compare this project's INSAT-3DS detector with ISRO's operational fire product.

3SIMG_L2P_FIR is the fire product MOSDAC publishes for INSAT-3DS, one KML file per
acquisition. It is the operational form of the ISRO detection paper this project
cannot read, so it is the nearest available statement of what the agency's own
algorithm reports. Both are compared on 1 to 3 November 2024, granule by granule,
inside the India bounding box the ingest uses, and by hour of day in IST.

The product's KML is partly corrupted. Every `address` field carries the text of all
earlier placemarks in the file concatenated together, and roughly half the `when`
fields are truncated to a time without a date or to a date without a time. Only the
coordinates are used, and the acquisition time is taken from the file name, which is
the half hour slot in UTC.

A detection is matched when the other record has one within MATCH_RADIUS_M in the same
granule. 4 km is one INSAT pixel, the radius D82 uses against the polar record.

Usage:
    uv run python scripts/official_fir_compare.py --fetch
    uv run python scripts/official_fir_compare.py
"""

import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
from sklearn.neighbors import BallTree

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

from ml.documents import provenance_line
from ml.fusion.mosdac import TokenSource, download, search
from ml.ingest.parse import INDIA_BBOX
from ml.paths import ARTIFACT_DIR, DATA_DIR, ENV_PATH, ROOT, ensure_dir

DATASET = "3SIMG_L2P_FIR"
DAYS = ("2024-11-01", "2024-11-02", "2024-11-03")
OFFICIAL_DIR = DATA_DIR / "raw" / "insat_fir"
OURS_DIR = DATA_DIR / "derived" / "insat"
ARTIFACT = ARTIFACT_DIR / "official_fir_comparison.json"
DOC = ROOT / "docs" / "official_fir_comparison.md"
MATCH_RADIUS_M = 4000.0
EARTH_RADIUS_M = 6371008.8
IST = timedelta(hours=5, minutes=30)
# The three hours the polar record leaves empty, chapter 6.3.
EVENING_HOURS_IST = (15, 16, 17)
# The Punjab and Haryana stubble burning box used by the detector comparison.
BOX = (73.5, 77.5, 28.5, 32.5)

SLOT = re.compile(r"3SIMG_(\d{2}[A-Z]{3}\d{4})_(\d{4})_")
COORDINATES = re.compile(r"<coordinates>\s*([-0-9.]+),([-0-9.]+)", re.DOTALL)


def slot_of(name: str) -> datetime:
    """The UTC acquisition slot a granule file name encodes."""
    found = SLOT.search(name)
    if not found:
        raise ValueError(f"no acquisition slot in {name}")
    return datetime.strptime(found.group(1) + found.group(2), "%d%b%Y%H%M").replace(tzinfo=UTC)


def parse_kml(text: str) -> tuple[np.ndarray, np.ndarray]:
    """Longitudes and latitudes of every placemark, ignoring the corrupted fields."""
    pairs = [(float(a), float(b)) for a, b in COORDINATES.findall(text)]
    if not pairs:
        return np.empty(0), np.empty(0)
    array = np.array(pairs)
    return array[:, 0], array[:, 1]


def inside(*, longitudes: np.ndarray, latitudes: np.ndarray, box: tuple) -> np.ndarray:
    west, east, south, north = box
    return (longitudes > west) & (longitudes < east) & (latitudes > south) & (latitudes < north)


def india_box() -> tuple[float, float, float, float]:
    west, south, east, north = INDIA_BBOX
    return (west, east, south, north)


def matched(
    *,
    query_longitudes: np.ndarray,
    query_latitudes: np.ndarray,
    reference_longitudes: np.ndarray,
    reference_latitudes: np.ndarray,
) -> np.ndarray:
    """For each query point, whether a reference point lies within MATCH_RADIUS_M."""
    if len(query_longitudes) == 0:
        return np.zeros(0, dtype=bool)
    if len(reference_longitudes) == 0:
        return np.zeros(len(query_longitudes), dtype=bool)
    tree = BallTree(
        np.radians(np.column_stack([reference_latitudes, reference_longitudes])),
        metric="haversine",
    )
    distances, _ = tree.query(np.radians(np.column_stack([query_latitudes, query_longitudes])), k=1)
    return distances[:, 0] * EARTH_RADIUS_M <= MATCH_RADIUS_M


def fetch() -> int:
    load_dotenv(ENV_PATH)
    tokens = TokenSource(os.environ.get("MOSDAC_USERNAME"), os.environ.get("MOSDAC_PASSWORD"))
    granules = {}
    for day in DAYS:
        for granule in search(DATASET, day, day):
            granules[granule.identifier] = granule.granule_id
    wanted = sorted(name for name in granules if slot_of(name).strftime("%Y-%m-%d") in DAYS)
    fetched = 0
    for name in wanted:
        destination = OFFICIAL_DIR / name
        if destination.exists():
            continue
        download(granules[name], tokens, destination)
        fetched += 1
    print(f"{len(wanted)} granules in the window, {fetched} fetched this run")
    return 0


def load_ours() -> dict[datetime, tuple[np.ndarray, np.ndarray]]:
    ours = {}
    for path in sorted(OURS_DIR.glob("*.npz")):
        with np.load(path, allow_pickle=False) as data:
            when = datetime.fromisoformat(str(data["acquired_utc"]))
            ours[when] = (data["longitude"].copy(), data["latitude"].copy())
    return ours


def main() -> int:
    arguments = argparse.ArgumentParser(description=__doc__)
    arguments.add_argument("--fetch", action="store_true", help="download missing granules")
    if arguments.parse_args().fetch:
        return fetch()

    official = {}
    for path in sorted(OFFICIAL_DIR.glob("*.kml")):
        official[slot_of(path.name)] = parse_kml(path.read_text(errors="replace"))
    ours = load_ours()
    if not official or not ours:
        print("BLOCKED: run with --fetch, and keep data/derived/insat", file=sys.stderr)
        return 2

    region = india_box()
    common = sorted(set(official) & set(ours))
    by_hour: dict[int, Counter] = {h: Counter() for h in range(24)}
    totals: Counter = Counter()
    evening: Counter = Counter()
    for when in common:
        official_lon, official_lat = official[when]
        ours_lon, ours_lat = ours[when]
        keep = inside(longitudes=official_lon, latitudes=official_lat, box=region)
        official_lon, official_lat = official_lon[keep], official_lat[keep]
        keep = inside(longitudes=ours_lon, latitudes=ours_lat, box=region)
        ours_lon, ours_lat = ours_lon[keep], ours_lat[keep]

        ours_found = matched(
            query_longitudes=ours_lon,
            query_latitudes=ours_lat,
            reference_longitudes=official_lon,
            reference_latitudes=official_lat,
        )
        official_found = matched(
            query_longitudes=official_lon,
            query_latitudes=official_lat,
            reference_longitudes=ours_lon,
            reference_latitudes=ours_lat,
        )
        hour = (when + IST).hour
        counts = {
            "official": len(official_lon),
            "ours": len(ours_lon),
            "ours_matched": int(ours_found.sum()),
            "official_matched": int(official_found.sum()),
            "official_in_box": int(
                inside(longitudes=official_lon, latitudes=official_lat, box=BOX).sum()
            ),
            "ours_in_box": int(inside(longitudes=ours_lon, latitudes=ours_lat, box=BOX).sum()),
        }
        by_hour[hour].update(counts)
        totals.update(counts)
        if hour in EVENING_HOURS_IST:
            evening.update(counts)

    only_official = sorted(set(official) - set(ours))
    only_ours = sorted(set(ours) - set(official))
    payload = {
        "dataset": DATASET,
        "days": list(DAYS),
        "match_radius_m": MATCH_RADIUS_M,
        "region": "India bounding box of the ingest",
        "granules_official": len(official),
        "granules_ours": len(ours),
        "granules_compared": len(common),
        "slots_only_official": [t.isoformat() for t in only_official],
        "slots_only_ours": [t.isoformat() for t in only_ours],
        "totals": dict(totals),
        "evening_hours_ist": list(EVENING_HOURS_IST),
        "evening_totals": dict(evening),
        "by_hour_ist": {str(h): dict(c) for h, c in by_hour.items()},
    }
    ARTIFACT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

    def share(part: int, whole: int) -> str:
        return "not measured" if whole == 0 else f"{part / whole:.1%}"

    lines = [
        "# INSAT-3DS: this project's detector against ISRO's operational fire product",
        "",
        "Regenerate: `uv run python scripts/official_fir_compare.py`",
        provenance_line(__file__),
        "",
        f"Product `{DATASET}` from MOSDAC, 1 to 3 November 2024, inside the India bounding",
        f"box. Matched means the other record has a detection within {MATCH_RADIUS_M:.0f} m in",
        "the same half hour granule. The product's KML carries corrupted address and time",
        "fields, so only coordinates are read and the time comes from the file name.",
        "",
        f"Granules: {len(official)} official, {len(ours)} ours, {len(common)} in both.",
        "",
        "| Quantity | Official product | This project |",
        "|---|---|---|",
        f"| detections in compared granules | {totals['official']} | {totals['ours']} |",
        f"| matched by the other record | {totals['official_matched']} | "
        f"{totals['ours_matched']} |",
        f"| share matched | {share(totals['official_matched'], totals['official'])} | "
        f"{share(totals['ours_matched'], totals['ours'])} |",
        f"| inside the Punjab and Haryana box | {totals['official_in_box']} | "
        f"{totals['ours_in_box']} |",
        f"| inside the box in hours 15 to 17 IST | {evening['official_in_box']} | "
        f"{evening['ours_in_box']} |",
        "",
        "## By hour of day, IST",
        "",
        "| Hour | Official | Ours | Official matched | Ours matched | Official in box "
        "| Ours in box |",
        "|---|---|---|---|---|---|---|",
    ]
    for hour in range(24):
        c = by_hour[hour]
        lines.append(
            f"| {hour:02d} | {c['official']} | {c['ours']} | {c['official_matched']} | "
            f"{c['ours_matched']} | {c['official_in_box']} | {c['ours_in_box']} |"
        )
    lines.append("")
    ensure_dir(DOC.parent)
    DOC.write_text("\n".join(lines))
    print(json.dumps(dict(totals)))
    print(f"wrote {ARTIFACT.relative_to(ROOT)} and {DOC.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
