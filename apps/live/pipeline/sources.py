"""Where the Live feed's inputs come from: FIRMS, INSAT-3DS, Open-Meteo and boundaries.

Every fetch here is the network side of a pure function in feed.py. Credentials are read
from the environment and never printed; the scheduled job receives them as repository
secrets, the owner's machine from `.env`.

MOSDAC's terms allow redistributing value added products and forbid redistributing its
products as downloaded, D126. So INSAT enters the feed only through this project's own
detector run on L1C granules, and only as cells.
"""

import json
import os
import urllib.parse
import urllib.request
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import duckdb

from ml.fusion.detect import detect
from ml.fusion.granule import read_india, time_from_name
from ml.fusion.mosdac import TokenSource, download, search
from ml.ingest.firms import FirmsClient
from ml.ingest.parse import INDIA_BBOX, parse_csv
from ml.ingest.transport import RequestsTransport

from .feed import AIR_CITIES, IST, MATCH_END_IST, MATCH_START_IST, Fire, day_mean

L1C = "3SIMG_L1C_ASIA_MER"
FIRMS_NRT = ("VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT", "MODIS_NRT")
BBOX = ",".join(str(value) for value in INDIA_BBOX)
AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
# Wind for "What's that smoke?", on a 1.5 degree grid over the ingest box. Each point is
# one call against Open-Meteo's free limit of 10000 a day, so the grid is coarse and the
# job fetches it once per run.
WIND_GRID_DEG = 1.5
WIND_CHUNK = 100
REQUEST_TIMEOUT_S = 60.0


def match_window_utc(day: date) -> tuple[datetime, datetime]:
    start = datetime(day.year, day.month, day.day, MATCH_START_IST, tzinfo=IST)
    end = datetime(day.year, day.month, day.day, MATCH_END_IST, tzinfo=IST)
    return start.astimezone(UTC), end.astimezone(UTC)


def firms_fires(day: date) -> tuple[list[Fire], datetime | None]:
    """Polar detections for one IST day from the near real time sources."""
    client = FirmsClient(os.environ.get("FIRMS_MAP_KEY"), RequestsTransport())
    start, end = match_window_utc(day)
    fires, newest = [], None
    for utc_day in sorted({start.date(), end.date()}):
        for source in FIRMS_NRT:
            text = client.area_csv(source, BBOX, utc_day, 1)
            for d in parse_csv(text, source):
                when = d.acq_ts_utc
                if start <= when < end:
                    fires.append(
                        Fire(
                            longitude=d.longitude, latitude=d.latitude, when_utc=when, team="polar"
                        )
                    )
                if newest is None or when > newest:
                    newest = when
    return fires, newest


def insat_fires(
    day: date, cache: Path, keep_raw: bool = True
) -> tuple[list[Fire], datetime | None]:
    """INSAT-3DS detections from this project's detector, for the match window.

    Each granule's detections are cached beside it, so an evening run downloads and
    analyses only the slots that arrived since the last run. The scheduled job drops the
    24 MB raw file once its detections are cached; the owner's machine keeps it, because a
    reduced output cannot be used to review the detector that produced it, D81.
    """
    tokens = TokenSource(os.environ.get("MOSDAC_USERNAME"), os.environ.get("MOSDAC_PASSWORD"))
    start, end = match_window_utc(day)
    fires, newest = [], None
    for utc_day in sorted({start.date(), end.date()}):
        for granule in search(L1C, str(utc_day), str(utc_day)):
            if not granule.is_hdf5:
                continue
            when = time_from_name(granule.identifier)
            if not start <= when < end:
                continue
            points = cached_detections(granule.granule_id, granule.identifier, cache, tokens)
            if not keep_raw:
                (cache / granule.identifier).unlink(missing_ok=True)
            for lon, lat in points:
                fires.append(Fire(longitude=lon, latitude=lat, when_utc=when, team="insat"))
            if newest is None or when > newest:
                newest = when
    return fires, newest


def cached_detections(
    granule_id: str, identifier: str, cache: Path, tokens: TokenSource
) -> list[tuple[float, float]]:
    """Detections for one granule, computed once and read from the cache after that."""
    stored = cache / f"{identifier}.detections.json"
    if stored.exists():
        return [tuple(p) for p in json.loads(stored.read_text())]
    path = cache / identifier
    if not path.exists():
        download(granule_id, tokens, path)
    found = detect(read_india(path))
    points = [
        (round(float(lon), 5), round(float(lat), 5))
        for lon, lat in zip(found.longitude, found.latitude, strict=True)
    ]
    stored.write_text(json.dumps(points))
    return points


def pm25_tomorrow(day: date) -> list[dict]:
    """The CAMS PM2.5 forecast for every city in AIR_CITIES, as tomorrow's 24 hour mean.

    One request covers every city, so the whole list costs one call against Open-Meteo's
    free limit.
    """
    query = urllib.parse.urlencode(
        {
            "latitude": ",".join(str(lat) for _name, _lon, lat in AIR_CITIES),
            "longitude": ",".join(str(lon) for _name, lon, _lat in AIR_CITIES),
            "hourly": "pm2_5",
            "timezone": "Asia/Kolkata",
            "forecast_days": 3,
        }
    )
    with urllib.request.urlopen(f"{AIR_QUALITY_URL}?{query}", timeout=REQUEST_TIMEOUT_S) as r:
        body = json.load(r)
    places = body if isinstance(body, list) else [body]
    tomorrow = str(day + timedelta(days=1))
    return [
        {
            "city": name,
            "date": tomorrow,
            "pm25_24h_mean": day_mean(place["hourly"]["time"], place["hourly"]["pm2_5"], tomorrow),
        }
        for (name, _lon, _lat), place in zip(AIR_CITIES, places, strict=True)
    ]


class Districts:
    """Point in polygon against the app's own boundary file, ODbL."""

    def __init__(self, boundaries: Path) -> None:
        self._con = duckdb.connect()
        self._con.execute("INSTALL spatial; LOAD spatial;")
        data = json.loads(boundaries.read_text())
        rows = []
        for feature in data["features"]:
            props = feature["properties"]
            rows.append((props["kind"], props["name"], json.dumps(feature["geometry"])))
        self._con.execute("CREATE TABLE areas (kind VARCHAR, name VARCHAR, geojson VARCHAR)")
        self._con.executemany("INSERT INTO areas VALUES (?, ?, ?)", rows)
        self._con.execute(
            "CREATE TABLE shapes AS SELECT kind, name, ST_GeomFromGeoJSON(geojson) AS g FROM areas"
        )

    def __call__(self, *, longitude: float, latitude: float) -> tuple[str | None, str | None]:
        found = dict(
            self._con.execute(
                "SELECT kind, min(name) FROM shapes "
                "WHERE ST_Contains(g, ST_Point(?, ?)) GROUP BY kind",
                [longitude, latitude],
            ).fetchall()
        )
        return found.get("state"), found.get("district")


def wind_grid() -> dict:
    """Hourly 10 m wind for the last six hours and the current hour, on a coarse grid.

    Directions are meteorological: the bearing the wind blows from, in degrees.
    """
    west, south, east, north = INDIA_BBOX
    points = [
        (round(west + i * WIND_GRID_DEG, 2), round(south + j * WIND_GRID_DEG, 2))
        for i in range(int((east - west) / WIND_GRID_DEG) + 1)
        for j in range(int((north - south) / WIND_GRID_DEG) + 1)
    ]
    out, hours = [], None
    for k in range(0, len(points), WIND_CHUNK):
        chunk = points[k : k + WIND_CHUNK]
        query = urllib.parse.urlencode(
            {
                "latitude": ",".join(str(lat) for _, lat in chunk),
                "longitude": ",".join(str(lon) for lon, _ in chunk),
                "hourly": "wind_speed_10m,wind_direction_10m",
                "past_hours": 6,
                "forecast_hours": 1,
                "timezone": "Asia/Kolkata",
                "wind_speed_unit": "kmh",
            }
        )
        with urllib.request.urlopen(f"{FORECAST_URL}?{query}", timeout=REQUEST_TIMEOUT_S) as r:
            body = json.load(r)
        for (lon, lat), site in zip(chunk, body, strict=True):
            hourly = site["hourly"]
            hours = hourly["time"]
            out.append(
                [
                    lon,
                    lat,
                    [
                        [speed, direction]
                        for speed, direction in zip(
                            hourly["wind_speed_10m"], hourly["wind_direction_10m"], strict=True
                        )
                    ],
                ]
            )
    return {
        "grid_deg": WIND_GRID_DEG,
        "hours_ist": hours or [],
        "points": out,
        "source": "Open-Meteo forecast API, CC BY 4.0",
    }
