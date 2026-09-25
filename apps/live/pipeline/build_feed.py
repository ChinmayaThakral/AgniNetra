"""Build the Live feed for one IST evening and write it where the web app reads it.

Usage, from the repository root:
    uv run python -m apps.live.pipeline.build_feed
    uv run python -m apps.live.pipeline.build_feed --date 2024-11-01

The feed is validated before it is written, so a feed that breaks one of the app's rules
is never published. Credentials come from the environment or `.env`.
"""

import argparse
import json
import sys
import time
from datetime import UTC, date, datetime

from dotenv import load_dotenv

from ml.paths import DATA_DIR, ENV_PATH, ROOT

from .feed import (
    CAVEATS,
    IST,
    SCHEMA,
    Reference,
    build_cells,
    build_districts,
    build_match,
    cell_of,
    netu_lines,
    pm25_category,
    restrict_to_india,
    validate,
)
from .sources import Districts, delhi_pm25_tomorrow, firms_fires, insat_fires

PIPELINE = ROOT / "apps" / "live" / "pipeline"
WEB_DATA = ROOT / "apps" / "live" / "web" / "public"
CACHE = DATA_DIR / "live" / "insat_l1c"
HEAVY_CATEGORIES = ("Very Poor", "Severe")
ATTRIBUTION = [
    "Data Source MOSDAC/SAC/ISRO. https://mosdac.gov.in. INSAT-3DS detections are this "
    "project's own value added product.",
    "We acknowledge the use of data from NASA LANCE FIRMS (https://earthdata.nasa.gov/firms), "
    "part of the NASA Earth Science Data and Information System.",
    "Air quality forecast: Copernicus Atmosphere Monitoring Service, via Open-Meteo, CC BY 4.0.",
]


def heatle_for(day: date, pack: dict) -> dict:
    """One verified site a day, clues in the order the game reveals them."""
    site = pack["heatle"][day.toordinal() % len(pack["heatle"])]
    return {
        "clues": [
            {"kind": "rhythm", "night_share": site["night_share"]},
            {"kind": "brightness", "median_frp_mw": site["median_frp_mw"]},
            {"kind": "land_cover", "value": site["land_cover"]},
            {"kind": "state", "value": site["state"]},
            {"kind": "persistence", "detections_in_record": site["detections"]},
            {"kind": "place", "centre": site["centre"]},
        ],
        "answer": site["answer"],
        "choices": [
            "steel or iron plant",
            "coal mine",
            "brick kiln",
            "power plant",
            "gas flare",
            "other industry",
            "cannot tell",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", help="IST evening to build, YYYY-MM-DD; default today")
    parser.add_argument("--drop-raw", action="store_true", help="delete raw granules once analysed")
    args = parser.parse_args()
    load_dotenv(ENV_PATH)
    started = time.monotonic()
    now = datetime.now(UTC)
    day = date.fromisoformat(args.date) if args.date else now.astimezone(IST).date()

    pack = json.loads((PIPELINE / "reference_pack.json").read_text())
    reference = Reference(pack, year=day.year)
    districts = Districts(WEB_DATA / "data" / "boundaries.json")

    CACHE.mkdir(parents=True, exist_ok=True)
    polar, polar_newest = firms_fires(day)
    insat, insat_newest = insat_fires(day, CACHE, keep_raw=not args.drop_raw)
    fires, places = restrict_to_india(polar + insat, districts)
    match = build_match(fires)
    cells = build_cells(fires, reference, lambda **kw: places[cell_of(**kw)])
    tomorrow = delhi_pm25_tomorrow(day)
    category = pm25_category(tomorrow["pm25_24h_mean"])
    insat_delay = None if insat_newest is None else (now - insat_newest).total_seconds() / 3600

    feed = {
        "schema": SCHEMA,
        "generated_utc": now.isoformat(timespec="seconds"),
        "evening_ist": str(day),
        "latency": {
            "insat_newest_utc": None if insat_newest is None else insat_newest.isoformat(),
            "insat_delay_hours": None if insat_delay is None else round(insat_delay, 1),
            "polar_newest_utc": None if polar_newest is None else polar_newest.isoformat(),
        },
        "match": match,
        "cells": cells,
        "districts": build_districts(cells),
        "netu": netu_lines(match, insat_delay, heavy=category in HEAVY_CATEGORIES),
        "tomorrow": {
            "city": "Delhi",
            "forecast_date": tomorrow["date"],
            "pm25_24h_mean": tomorrow["pm25_24h_mean"],
            "cpcb_category": category,
            "evening_fire_cells": sum(c["evening"] for c in cells),
            "school_hybrid": "not measured",
            "source": "CAMS global forecast via Open-Meteo, not an official forecast",
        },
        "heatle": heatle_for(day, pack),
        "attribution": ATTRIBUTION + pack["attribution"],
        "caveats": list(CAVEATS),
    }
    validate(feed)

    out_dir = WEB_DATA / "feed"
    out_dir.mkdir(parents=True, exist_ok=True)
    text = json.dumps(feed, separators=(",", ":"), allow_nan=False)
    (out_dir / f"{day}.json").write_text(text)
    (out_dir / "latest.json").write_text(text)
    print(
        f"{day}: {len(polar)} polar and {len(insat)} INSAT detections, {len(fires)} in India, "
        f"{len(cells)} cells, "
        f"insat share {match['insat_share']}, polar share {match['polar_share']}, "
        f"{time.monotonic() - started:.0f} s"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
