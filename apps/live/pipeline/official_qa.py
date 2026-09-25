"""Private nightly check: this detector against ISRO's own INSAT-3DS fire product.

Never part of the app. MOSDAC's terms forbid redistributing its products as downloaded,
D126, so the result is written under `data/`, which is never committed, and the feed
builder does not import this module; a test holds that.

The check is useful because the official product does see evening burning, D127, so a
sharp disagreement on an evening is worth a person's look before the app's numbers are
trusted. Per IST hour, fire cells in India from each record are compared. An hour is
flagged when one side sees at least MIN_CELLS cells and the other sees less than a fifth
of that or more than five times it. Both constants are a first setting, to be swept once
a week of evenings exists, per the rule in CONVENTIONS on unswept constants.

Usage:
    uv run python -m apps.live.pipeline.official_qa --date 2026-10-20
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from datetime import UTC, date, datetime

from dotenv import load_dotenv

from ml.fusion.granule import time_from_name
from ml.fusion.mosdac import TokenSource, download, search
from ml.paths import DATA_DIR, ENV_PATH, ROOT

from .feed import IST, cell_centre, cell_of
from .sources import Districts, match_window_utc

FIR = "3SIMG_L2P_FIR"
OFFICIAL_CACHE = DATA_DIR / "live" / "insat_fir"
OURS_CACHE = DATA_DIR / "live" / "insat_l1c"
OUT = DATA_DIR / "live_qa"
BOUNDARIES = ROOT / "apps" / "live" / "web" / "public" / "data" / "boundaries.json"
MIN_CELLS = 10
RATIO_LIMIT = 5.0
COORDINATES = re.compile(r"<coordinates>\s*([-0-9.]+),([-0-9.]+)")
SLOT = re.compile(r"3SIMG_(\d{2}[A-Z]{3}\d{4})_(\d{4})_")


def official_slot(name: str) -> datetime:
    found = SLOT.search(name)
    if not found:
        raise ValueError(f"no slot in {name}")
    return datetime.strptime(found.group(1) + found.group(2), "%d%b%Y%H%M").replace(tzinfo=UTC)


def flag(official: int, ours: int) -> bool:
    """True when the two records disagree sharply in one hour."""
    if max(official, ours) < MIN_CELLS:
        return False
    low, high = sorted((official, ours))
    return low == 0 or high / low > RATIO_LIMIT


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", help="IST evening, YYYY-MM-DD; default today")
    args = parser.parse_args()
    load_dotenv(ENV_PATH)
    day = date.fromisoformat(args.date) if args.date else datetime.now(UTC).astimezone(IST).date()
    start, end = match_window_utc(day)
    tokens = TokenSource(os.environ.get("MOSDAC_USERNAME"), os.environ.get("MOSDAC_PASSWORD"))
    locate = Districts(BOUNDARIES)
    india: dict[tuple[int, int], bool] = {}

    def in_india(cell: tuple[int, int]) -> bool:
        if cell not in india:
            lon, lat = cell_centre(cell)
            india[cell] = locate(longitude=lon, latitude=lat)[0] is not None
        return india[cell]

    official: dict[int, set] = defaultdict(set)
    OFFICIAL_CACHE.mkdir(parents=True, exist_ok=True)
    for utc_day in sorted({start.date(), end.date()}):
        for granule in search(FIR, str(utc_day), str(utc_day)):
            when = official_slot(granule.identifier)
            if not start <= when < end:
                continue
            path = OFFICIAL_CACHE / granule.identifier
            if not path.exists():
                download(granule.granule_id, tokens, path)
            for lon, lat in COORDINATES.findall(path.read_text(errors="replace")):
                cell = cell_of(longitude=float(lon), latitude=float(lat))
                if in_india(cell):
                    official[when.astimezone(IST).hour].add(cell)

    ours: dict[int, set] = defaultdict(set)
    for stored in sorted(OURS_CACHE.glob("*.detections.json")):
        when = time_from_name(stored.name)
        if not start <= when < end:
            continue
        for lon, lat in json.loads(stored.read_text()):
            cell = cell_of(longitude=lon, latitude=lat)
            if in_india(cell):
                ours[when.astimezone(IST).hour].add(cell)

    hours = []
    for hour in sorted(set(official) | set(ours)):
        o, m = len(official[hour]), len(ours[hour])
        both = len(official[hour] & ours[hour])
        hours.append({"hour_ist": hour, "official": o, "ours": m, "both": both, "flag": flag(o, m)})
    report = {
        "evening_ist": str(day),
        "min_cells": MIN_CELLS,
        "ratio_limit": RATIO_LIMIT,
        "private": "never published, MOSDAC products may not be redistributed, D126",
        "hours": hours,
        "flagged_hours": [h["hour_ist"] for h in hours if h["flag"]],
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{day}.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"{day}: {len(hours)} hours compared, flagged {report['flagged_hours']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
