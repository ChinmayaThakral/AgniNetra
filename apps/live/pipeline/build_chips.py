"""Sentinel-2 image chips for Swipe and for Heatle's zoom-out clue.

Usage, from the repository root, once, not in the scheduled job:
    uv run python -m apps.live.pipeline.build_chips

Imagery is Copernicus Sentinel-2 L2A, read as cloud optimised GeoTIFFs from the AWS open
data archive and found through Element 84's STAC search. Neither needs a key or an
account, and only the small window around each site is read, never a whole tile, D139.
For each site the least cloudy scene of the last dry season is used, and a scene that
leaves the window partly empty is passed over for the next.

Swipe takes persistent sources from the console's published list that burn at night at
least MIN_NIGHT of the times they are seen. Crop fires are a daytime pattern, so this
keeps fields out of the game, rule 1. The eight imagery verified sites are its hidden gold
questions. Nothing written here carries a coordinate: an item is an identifier, a picture
and the scene it came from.
"""

import hashlib
import io
import json
import math
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from ml.paths import ROOT

PIPELINE = ROOT / "apps" / "live" / "pipeline"
PUBLIC = ROOT / "apps" / "live" / "web" / "public"
SOURCES = ROOT / "apps" / "console" / "public" / "data" / "sources.json"
STAC = "https://earth-search.aws.element84.com/v1/search"
SEASON = "2025-11-01T00:00:00Z/2026-05-31T23:59:59Z"
# Searches in turn, as (cloud cover under, empty pixels under) in percent. The empty pixel
# limit skips tiles cut by the edge of the satellite's swath, which usually leave a site's
# window part empty. Some sites lie only on such tiles: of six that found no scene this
# way on 2026-10-06, each had 38 to 86 scenes under 20 percent cloud without the limit.
# So the last search drops it and lets the read's own emptiness check decide.
SEARCHES = ((5, 2), (20, 2), (20, None))
SCENES = 10
MIN_NIGHT = 0.6
GOLD_RADIUS_M = 600.0
CLOSE_M = 2560.0
WIDE_M = 10240.0
CHIP_PX = 256
QUALITY = 80
MAX_EMPTY = 0.01
PAUSE_S = 0.2
# The mean earth radius feed.py uses, so a distance here matches one there.
EARTH_RADIUS_M = 6371008.8
WORKERS = 8
PROGRESS = 25


def item_id(*, longitude: float, latitude: float) -> str:
    """A stable name for a site that does not spell out where it is."""
    return "s" + hashlib.sha1(f"{longitude:.4f},{latitude:.4f}".encode()).hexdigest()[:10]


def _distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    p1, p2 = math.radians(a[1]), math.radians(b[1])
    dp, dl = p2 - p1, math.radians(b[0] - a[0])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


def swipe_answer(verified: str) -> str:
    """The Swipe choice a verified Heatle answer falls under: a flare, or any industry."""
    return "flare" if "flare" in verified else "factory"


def swipe_candidates(sources: list[dict], heatle: list[dict]) -> list[dict]:
    """Night-heavy persistent sources, each verified Heatle site carrying its gold answer."""
    out = []
    for s in sources:
        if s["nightFraction"] is None or s["nightFraction"] < MIN_NIGHT:
            continue
        here = (s["lon"], s["lat"])
        near = [h for h in heatle if _distance_m(here, tuple(h["centre"])) <= GOLD_RADIUS_M]
        gold = swipe_answer(near[0]["answer"]) if near else None
        out.append(
            {
                "id": item_id(longitude=s["lon"], latitude=s["lat"]),
                "lon": s["lon"],
                "lat": s["lat"],
                "gold": gold,
            }
        )
    return out


def least_cloudy(*, longitude: float, latitude: float) -> list[dict]:
    """Scenes over a point in the season, clearest first, relaxing the limits in turn."""
    for cloud, empty in SEARCHES:
        query = {"eo:cloud_cover": {"lt": cloud}}
        if empty is not None:
            query["s2:nodata_pixel_percentage"] = {"lt": empty}
        body = {
            "collections": ["sentinel-2-l2a"],
            "intersects": {"type": "Point", "coordinates": [longitude, latitude]},
            "datetime": SEASON,
            "query": query,
            "sortby": [{"field": "properties.eo:cloud_cover", "direction": "asc"}],
            "limit": SCENES,
        }
        request = urllib.request.Request(
            STAC, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            features = json.load(response)["features"]
        if features:
            return features
    return []


def read_chip(href: str, *, longitude: float, latitude: float, span_m: float):
    """The window of a scene's true colour image centred on a point, and its empty share."""
    import numpy as np
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.warp import transform
    from rasterio.windows import from_bounds

    env = {
        "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
        "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif",
        "GDAL_HTTP_MAX_RETRY": "3",
        "GDAL_HTTP_RETRY_DELAY": "2",
        # A stalled range read otherwise waits forever and holds up the whole run. A slow
        # one is not stalled: a 2.2 MB tile shared among WORKERS readers was measured
        # taking over 60 s, so only a transfer under 1 KB/s for 30 s is abandoned.
        "GDAL_HTTP_CONNECTTIMEOUT": "20",
        "GDAL_HTTP_LOW_SPEED_LIMIT": "1024",
        "GDAL_HTTP_LOW_SPEED_TIME": "30",
        "GDAL_HTTP_TIMEOUT": "600",
        "GDAL_HTTP_MULTIPLEX": "YES",
        "GDAL_HTTP_VERSION": "2",
        "GDAL_INGESTED_BYTES_AT_OPEN": "32768",
        "VSI_CACHE": "TRUE",
    }
    with rasterio.Env(**env), rasterio.open(href) as src:
        xs, ys = transform("EPSG:4326", src.crs, [longitude], [latitude])
        half = span_m / 2
        window = from_bounds(xs[0] - half, ys[0] - half, xs[0] + half, ys[0] + half, src.transform)
        data = src.read(
            window=window,
            out_shape=(3, CHIP_PX, CHIP_PX),
            boundless=True,
            fill_value=0,
            resampling=Resampling.average,
        )
    empty = float(np.mean(np.all(data == 0, axis=0)))
    return np.transpose(data, (1, 2, 0)), empty


def stretch(pixels):
    """A gentle per channel contrast stretch, 2nd to 98th percentile, for a hazy scene."""
    import numpy as np

    out = np.empty_like(pixels)
    for band in range(3):
        channel = pixels[:, :, band].astype("float32")
        low, high = np.percentile(channel, (2, 98))
        scaled = (channel - low) / max(high - low, 1.0)
        out[:, :, band] = np.clip(scaled * 255.0, 0, 255).astype("uint8")
    return out


def webp(pixels) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.fromarray(stretch(pixels)).save(buffer, format="WEBP", quality=QUALITY, method=6)
    return buffer.getvalue()


def chip_for(*, longitude: float, latitude: float, spans: dict[str, float]) -> dict | None:
    """Every requested span from the first clear scene that covers them all."""
    for scene in least_cloudy(longitude=longitude, latitude=latitude):
        href = scene["assets"]["visual"]["href"]
        images = {}
        for name, span in spans.items():
            pixels, empty = read_chip(href, longitude=longitude, latitude=latitude, span_m=span)
            if empty > MAX_EMPTY:
                break
            images[name] = webp(pixels)
        else:
            return {
                "scene": scene["id"],
                "acquired": scene["properties"]["datetime"][:10],
                "images": images,
            }
    return None


def credit_for(acquired: list[str]) -> str:
    years = sorted({day[:4] for day in acquired})
    return "Contains modified Copernicus Sentinel data " + ", ".join(years) + "."


def write_swipe(path: Path, items: list[dict], credit: str) -> None:
    swipe = {
        "schema": "agninetra-swipe/1",
        "credit": credit,
        "close_span_km": CLOSE_M / 1000,
        "items": items,
    }
    path.write_text(json.dumps(swipe, indent=1) + "\n")


def main() -> int:
    pack_path = PIPELINE / "reference_pack.json"
    pack = json.loads(pack_path.read_text())
    sources = json.loads(SOURCES.read_text())
    chips = PUBLIC / "chips"
    chips.mkdir(parents=True, exist_ok=True)
    game = PUBLIC / "game"
    game.mkdir(parents=True, exist_ok=True)
    swipe_path = game / "swipe.json"
    started = time.monotonic()

    candidates = swipe_candidates(sources, pack["heatle"])
    # Each chip is written and listed as soon as it is made, so a rerun after an
    # interruption starts from the sites still missing.
    done = {}
    if swipe_path.exists():
        for item in json.loads(swipe_path.read_text())["items"]:
            if (PUBLIC / item["chip"]).exists():
                done[item["id"]] = item
    todo = [c for c in candidates if c["id"] not in done]
    print(f"{len(candidates)} swipe sites, {len(candidates) - len(todo)} already made")

    def listed() -> list[dict]:
        return [done[c["id"]] for c in candidates if c["id"] in done]

    def make(c: dict) -> dict | None:
        time.sleep(PAUSE_S)
        for attempt in range(2):
            try:
                return chip_for(longitude=c["lon"], latitude=c["lat"], spans={"close": CLOSE_M})
            except Exception as exc:  # a network failure for one site must not end the run
                print(f"  {c['id']}: attempt {attempt + 1} failed, {exc}")
        return None

    missing = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(make, c): c for c in todo}
        for n, future in enumerate(as_completed(futures), start=1):
            c, made = futures[future], future.result()
            if made is None:
                missing += 1
            else:
                (chips / f"{c['id']}.webp").write_bytes(made["images"]["close"])
                done[c["id"]] = {
                    "id": c["id"],
                    "chip": f"chips/{c['id']}.webp",
                    "scene": made["scene"],
                    "acquired": made["acquired"],
                    "gold": c["gold"],
                }
                items = listed()
                write_swipe(swipe_path, items, credit_for([i["acquired"] for i in items]))
            if n % PROGRESS == 0:
                print(f"  {n} of {len(todo)} swipe sites, {time.monotonic() - started:.0f} s")

    for site in pack["heatle"]:
        lon, lat = site["centre"]
        name = item_id(longitude=lon, latitude=lat)
        kept = site.get("images")
        if kept and all((PUBLIC / kept[kind]).exists() for kind in ("close", "wide")):
            continue
        made = chip_for(longitude=lon, latitude=lat, spans={"close": CLOSE_M, "wide": WIDE_M})
        time.sleep(PAUSE_S)
        if made is None:
            site.pop("images", None)
            continue
        for kind, data in made["images"].items():
            (chips / f"{name}_{kind}.webp").write_bytes(data)
        site["images"] = {
            "close": f"chips/{name}_close.webp",
            "wide": f"chips/{name}_wide.webp",
            "scene": made["scene"],
            "acquired": made["acquired"],
        }

    items = listed()
    pictured = [s["images"] for s in pack["heatle"] if "images" in s]
    credit = credit_for([i["acquired"] for i in items + pictured])
    write_swipe(swipe_path, items, credit)
    pack["imagery_credit"] = credit
    pack_path.write_text(json.dumps(pack, separators=(",", ":")) + "\n")
    keep = {i["chip"] for i in items} | {p[k] for p in pictured for k in ("close", "wide")}
    for stale in chips.glob("*.webp"):
        if f"chips/{stale.name}" not in keep:
            stale.unlink()
    print(
        f"{len(items)} swipe chips ({sum(i['gold'] is not None for i in items)} gold), "
        f"{missing} sites with no clear scene, "
        f"{len(pictured)} heatle sites with images, "
        f"{time.monotonic() - started:.0f} s"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
