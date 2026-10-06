"""The qualifying Heatle rounds that unlock Swipe, and Swipe's community set.

The first run keeps the full candidate list and the qualifying pictures' originals under
data/live/qualify_chips, outside the public folder; later runs read them from there.

Usage, from the repository root, with QUALIFY_SECRET in `.env`, the same value the server
is given:
    uv run python -m apps.live.pipeline.build_qualify_pack

A Swipe site within 1 km of a Global Energy Monitor asset, the project's own industrial
radius, has a registry backed answer: it becomes a qualifying round. Its answer is stored
only as an HMAC under QUALIFY_SECRET, so the public repository does not give it away. The
sites with no such match are the unidentified ones; with the eight imagery verified sites
mixed in unannounced, they are what qualified players label. Each verified site is kept
only as an HMAC too, so the public files do not say which they are.
"""

import json
import os
import sys
from pathlib import Path

import duckdb
from dotenv import load_dotenv

from ml.paths import DATA_DIR, ENV_PATH, ROOT

from .build_chips import CLOSE_M, PUBLIC, SOURCES, WIDE_M, _distance_m, chip_for, item_id
from .build_feed import PIPELINE
from .site_details import details_for, observed_months

OUT = PIPELINE / "qualify_pack.json"
# Qualifying pictures are published under names keyed by the secret, and their originals
# kept off the public folder, so a picture cannot be traced back to a site id.
HIDDEN = DATA_DIR / "live" / "qualify_chips"
OPAQUE = PUBLIC / "chips" / "q"
SWIPE = PUBLIC / "game" / "swipe.json"
DB = DATA_DIR / "agninetra.duckdb"
MATCH_M = 1000.0
CHOICES = [
    "steel or iron plant",
    "coal mine",
    "brick kiln",
    "power plant",
    "gas flare",
    "other industry",
    "cannot tell",
]


def answer_for(tracker: str) -> str | None:
    name = tracker.lower()
    if "steel" in name:
        return "steel or iron plant"
    if "coal mine" in name:
        return "coal mine"
    if "power" in name:
        return "power plant"
    if "cement" in name:
        return "other industry"
    return None


def nearest_asset(lon: float, lat: float, assets: list[tuple]) -> str | None:
    best = None
    for tracker, alon, alat in assets:
        if abs(alon - lon) > 0.02 or abs(alat - lat) > 0.02:
            continue
        d = _distance_m((lon, lat), (alon, alat))
        if d <= MATCH_M and (best is None or d < best[0]):
            best = (d, answer_for(tracker))
    return best[1] if best else None


def rounded(value: float, step: float) -> float:
    """Clue values coarse enough that they cannot be looked up in the console's site list."""
    return round(round(value / step) * step, 6)


def about(count: int) -> int:
    """A count to two significant figures."""
    if count < 100:
        return count
    digits = len(str(count)) - 2
    return round(count, -digits)


def publish_chip(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_bytes(source.read_bytes())


def main() -> int:
    load_dotenv(ENV_PATH)
    secret = os.environ.get("QUALIFY_SECRET", "")
    if len(secret) < 32:
        print("QUALIFY_SECRET is missing or short; it must match the server's", file=sys.stderr)
        return 1
    from apps.live.community import mac

    pack = json.loads((PIPELINE / "reference_pack.json").read_text())
    gold_ids = {item_id(longitude=s["centre"][0], latitude=s["centre"][1]) for s in pack["heatle"]}
    sources = {
        item_id(longitude=s["lon"], latitude=s["lat"]): s for s in json.loads(SOURCES.read_text())
    }
    swipe = json.loads(SWIPE.read_text())
    # The public Swipe file keeps only the community sites, so the full list is kept here
    # for the next run.
    everything = HIDDEN / "swipe_all.json"
    if everything.exists():
        swipe["items"] = json.loads(everything.read_text())
    else:
        HIDDEN.mkdir(parents=True, exist_ok=True)
        everything.write_text(json.dumps(swipe["items"]))
    db = duckdb.connect(str(DB), read_only=True)
    db.execute("LOAD spatial")
    assets = db.execute("SELECT tracker, longitude, latitude FROM ref_gem_assets").fetchall()
    observed = observed_months(db)

    puzzles, community, gold_macs = [], 0, []
    for item in swipe["items"]:
        site = sources.get(item["id"])
        is_gold = item.pop("gold", None) is not None or item["id"] in gold_ids
        answer = (
            None if is_gold or site is None else nearest_asset(site["lon"], site["lat"], assets)
        )
        item["community"] = answer is None
        community += item["community"]
        if is_gold:
            gold_macs.append(mac(secret, "gold", item["id"]))
        wide = PUBLIC / "chips" / f"{item['id']}_wide.webp"
        close = PUBLIC / "chips" / f"{item['id']}.webp"
        if not item["community"]:
            wide, close = HIDDEN / wide.name, HIDDEN / close.name
            for public in (PUBLIC / "chips" / wide.name, PUBLIC / "chips" / close.name):
                if public.exists():
                    HIDDEN.mkdir(parents=True, exist_ok=True)
                    public.replace(HIDDEN / public.name)
        if site is not None and not wide.exists():
            try:
                made = chip_for(longitude=site["lon"], latitude=site["lat"], spans={"wide": WIDE_M})
            except OSError as exc:
                # A stalled imagery search costs this site its wide picture, not the run.
                print(f"{item['id']}: no wide picture, {exc}", file=sys.stderr)
                made = None
            if made is not None:
                wide.write_bytes(made["images"]["wide"])
        if answer is None:
            if wide.exists():
                item["wide"] = f"chips/{item['id']}_wide.webp"
            if site is not None:
                item["details"] = details_for(db, site, observed)
            continue
        if not wide.exists() or not close.exists():
            continue
        token = mac(secret, "chip", item["id"])[:16]
        publish_chip(close, OPAQUE / f"{token}.webp")
        publish_chip(wide, OPAQUE / f"{token}_w.webp")
        puzzles.append(
            {
                "id": token,
                "clues": [
                    {"kind": "rhythm", "night_share": rounded(site["nightFraction"], 0.05)},
                    {
                        "kind": "image",
                        "src": f"chips/q/{token}.webp",
                        "span_km": CLOSE_M / 1000,
                        "acquired": item["acquired"],
                    },
                    {"kind": "spread", "spread_m": rounded(site["spreadM"], 250)},
                    {
                        "kind": "image",
                        "src": f"chips/q/{token}_w.webp",
                        "span_km": WIDE_M / 1000,
                    },
                    {"kind": "persistence", "detections_in_record": about(site["detections"])},
                    {"kind": "state", "value": site["state"]},
                ],
                "answer_mac": mac(secret, token, answer),
            }
        )

    OUT.write_text(
        json.dumps(
            {
                "schema": "agninetra-qualify/1",
                "choices": CHOICES,
                "puzzles": puzzles,
                "gold_macs": gold_macs,
            },
            separators=(",", ":"),
        )
        + "\n"
    )
    swipe["items"] = [item for item in swipe["items"] if item["community"]]
    SWIPE.write_text(json.dumps(swipe, indent=1) + "\n")
    print(
        f"{len(puzzles)} qualifying rounds, {community} community sites "
        f"({len(gold_macs)} verified among them), written to {OUT.relative_to(ROOT)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
