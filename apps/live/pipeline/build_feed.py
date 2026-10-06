"""Build the Live feed for one IST evening and write it where the web app reads it.

Usage, from the repository root:
    uv run python -m apps.live.pipeline.build_feed
    uv run python -m apps.live.pipeline.build_feed --date 2024-11-01
    uv run python -m apps.live.pipeline.build_feed --out data/live/feed

The feed is validated before it is written, so a feed that breaks one of the app's rules
is never published. Credentials come from the environment or `.env`.
"""

import argparse
import json
import sys
import time
from datetime import UTC, date, datetime
from pathlib import Path

from dotenv import load_dotenv

from ml.paths import DATA_DIR, ENV_PATH, ROOT

from .build_chips import CLOSE_M, WIDE_M
from .feed import (
    CAVEATS,
    IST,
    SCHEMA,
    Reference,
    build_cells,
    build_districts,
    build_match,
    cell_centre,
    cell_of,
    commentary,
    netu_lines,
    pm25_category,
    restrict_to_india,
    season_stats,
    validate,
)
from .sources import Districts, firms_fires, insat_fires, pm25_tomorrow, wind_grid

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
    """One verified site a day, clues in the order the game reveals them.

    With Sentinel-2 chips for the site, the fourth and fifth clues are the picture,
    close and then zoomed out, and the last names the state and rings the cell. Without
    them, the state and the site's history stand in for the pictures.
    """
    site = pack["heatle"][day.toordinal() % len(pack["heatle"])]
    # The place clue is the 11 km cell, like every other location the app shows.
    lon, lat = site["centre"]
    clues: list[dict] = [
        {"kind": "rhythm", "night_share": site["night_share"]},
        {"kind": "brightness", "median_frp_mw": site["median_frp_mw"]},
        {"kind": "land_cover", "value": site["land_cover"]},
    ]
    images = site.get("images")
    if images:
        clues += [
            {
                "kind": "image",
                "src": images["close"],
                "span_km": CLOSE_M / 1000,
                "acquired": images["acquired"],
            },
            {
                "kind": "image",
                "src": images["wide"],
                "span_km": WIDE_M / 1000,
                "acquired": images["acquired"],
            },
        ]
    else:
        clues += [
            {"kind": "state", "value": site["state"]},
            {"kind": "persistence", "detections_in_record": site["detections"]},
        ]
    clues.append(
        {
            "kind": "place",
            "state": site["state"],
            "centre": list(cell_centre(cell_of(longitude=lon, latitude=lat))),
        }
    )
    return {
        "clues": clues,
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
    parser.add_argument(
        "--out", type=Path, default=WEB_DATA / "feed", help="directory the feed is written to"
    )
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
    air = pm25_tomorrow(day)
    tomorrow = air[0]
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
        "commentary": commentary(
            match, None if insat_newest is None else insat_newest.astimezone(IST).strftime("%H:%M")
        ),
        "tomorrow": {
            "city": "Delhi",
            "forecast_date": tomorrow["date"],
            "pm25_24h_mean": tomorrow["pm25_24h_mean"],
            "cpcb_category": category,
            "evening_fire_cells": sum(c["evening"] for c in cells),
            "school_hybrid": "not measured",
            "source": "CAMS global forecast via Open-Meteo, not an official forecast",
        },
        "air": [
            {
                "city": a["city"],
                "pm25_24h_mean": a["pm25_24h_mean"],
                "cpcb_category": pm25_category(a["pm25_24h_mean"]),
            }
            for a in air
        ],
        "heatle": heatle_for(day, pack),
        # Wind is the last six hours before now, so it describes only the current
        # evening. A rebuilt past evening carries none rather than the wrong hours.
        "wind": wind_grid() if day == now.astimezone(IST).date() else None,
        "attribution": ATTRIBUTION
        + pack["attribution"]
        + ([pack["imagery_credit"]] if "imagery_credit" in pack else []),
        "caveats": list(CAVEATS),
    }
    validate(feed)

    out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    text = json.dumps(feed, separators=(",", ":"), allow_nan=False)
    (out_dir / f"{day}.json").write_text(text)
    (out_dir / "latest.json").write_text(text)
    # Smog Wrapped's season file is rebuilt from every evening on disk, so it is never
    # ahead of the feeds it summarises.
    evenings = [json.loads(p.read_text()) for p in sorted(out_dir.glob("20??-??-??.json"))]
    # Which evenings exist, so the app's day switcher never asks for one that does not.
    (out_dir / "days.json").write_text(json.dumps([e["evening_ist"] for e in evenings]))
    (out_dir / "season.json").write_text(
        json.dumps(season_stats(evenings), separators=(",", ":"), allow_nan=False)
    )
    print(
        f"{day}: {len(polar)} polar and {len(insat)} INSAT detections, {len(fires)} in India, "
        f"{len(cells)} cells, "
        f"insat share {match['insat_share']}, polar share {match['polar_share']}, "
        f"{time.monotonic() - started:.0f} s"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
