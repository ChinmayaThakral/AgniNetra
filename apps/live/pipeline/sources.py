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

from .feed import IST, MATCH_END_IST, MATCH_START_IST, Fire

L1C = "3SIMG_L1C_ASIA_MER"
FIRMS_NRT = ("VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT", "MODIS_NRT")
BBOX = ",".join(str(value) for value in INDIA_BBOX)
AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
DELHI = (77.21, 28.61)
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


def delhi_pm25_tomorrow(day: date) -> dict:
    """The CAMS global PM2.5 forecast for Delhi, as a 24 hour mean for the next IST day."""
    query = urllib.parse.urlencode(
        {
            "latitude": DELHI[1],
            "longitude": DELHI[0],
            "hourly": "pm2_5",
            "timezone": "Asia/Kolkata",
            "forecast_days": 3,
        }
    )
    with urllib.request.urlopen(f"{AIR_QUALITY_URL}?{query}", timeout=REQUEST_TIMEOUT_S) as r:
        body = json.load(r)
    tomorrow = str(day + timedelta(days=1))
    values = [
        v
        for t, v in zip(body["hourly"]["time"], body["hourly"]["pm2_5"], strict=True)
        if t.startswith(tomorrow) and v is not None
    ]
    return {
        "date": tomorrow,
        "hours": len(values),
        "pm25_24h_mean": round(sum(values) / len(values), 1) if len(values) == 24 else None,
    }


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
