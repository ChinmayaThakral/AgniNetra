"""FIRMS CSV parsing into the union row shape the detections table stores."""

import csv
from dataclasses import dataclass
from datetime import datetime
from io import StringIO
from typing import Final

from ml.ingest.columns import family_for, required_columns_for
from ml.ingest.confidence import band_ordinal, normalise
from ml.ingest.identity import detection_id
from ml.ingest.timeutil import parse_acq_timestamp, to_ist

# Fixture rows carry this marker in the version column. Nothing carrying it may
# reach the detections table on a real run. See ml/ingest/load.py and D8.
FIXTURE_MARKER: Final[str] = "SYNTHETIC_FIXTURE"

INDIA_BBOX: Final[tuple[float, float, float, float]] = (68.0, 6.5, 97.5, 37.5)


@dataclass(frozen=True)
class Detection:
    """One parsed detection, in the union shape."""

    detection_id: str
    source: str
    family: str
    instrument: str
    satellite: str
    latitude: float
    longitude: float
    acq_ts_utc: datetime
    acq_ts_ist: datetime
    acq_date_ist: str
    acq_hour_ist: int
    daynight: str | None
    confidence_band: str
    confidence_ordinal: int
    confidence_raw: str
    frp: float | None
    scan: float | None
    track: float | None
    brightness: float | None
    bright_t31: float | None
    bright_ti4: float | None
    bright_ti5: float | None
    country_id: str | None
    version: str | None


def _opt_float(row: dict[str, str], key: str) -> float | None:
    raw = row.get(key)
    if raw is None or str(raw).strip() == "":
        return None
    return float(raw)


def in_india_bbox(*, latitude: float, longitude: float) -> bool:
    """Return whether a coordinate falls inside the project bounding box."""
    west, south, east, north = INDIA_BBOX
    return west <= longitude <= east and south <= latitude <= north


def parse_csv(text: str, source: str, restrict_to_bbox: bool = True) -> list[Detection]:
    """Parse a FIRMS CSV response for one source into Detection rows.

    A response whose header is missing a required column is rejected rather than
    parsed partially, because a silently shortened row set is worse than a stop.
    Columns in OPTIONAL_COLUMNS may be absent: the documented MODIS set includes
    country_id but the live area endpoint does not return it. D18.
    """
    family = family_for(source)
    expected = required_columns_for(source)

    reader = csv.DictReader(StringIO(text))
    header = reader.fieldnames or []
    missing = [column for column in expected if column not in header]
    if missing:
        raise ValueError(
            f"FIRMS response for {source} is missing documented columns: {', '.join(missing)}. "
            f"Header was: {', '.join(header)}"
        )

    detections: list[Detection] = []
    for row in reader:
        if not row.get("latitude"):
            continue
        latitude = float(row["latitude"])
        longitude = float(row["longitude"])
        if restrict_to_bbox and not in_india_bbox(latitude=latitude, longitude=longitude):
            continue

        acq_utc = parse_acq_timestamp(row["acq_date"], row["acq_time"])
        acq_ist = to_ist(acq_utc)
        confidence_raw = str(row["confidence"]).strip()
        band = normalise(family, confidence_raw)
        instrument = str(row["instrument"]).strip()
        satellite = str(row["satellite"]).strip()

        detections.append(
            Detection(
                detection_id=detection_id(
                    instrument=instrument,
                    satellite=satellite,
                    latitude=latitude,
                    longitude=longitude,
                    acq_utc=acq_utc,
                ),
                source=source,
                family=family,
                instrument=instrument,
                satellite=satellite,
                latitude=latitude,
                longitude=longitude,
                acq_ts_utc=acq_utc,
                acq_ts_ist=acq_ist,
                acq_date_ist=acq_ist.strftime("%Y-%m-%d"),
                acq_hour_ist=acq_ist.hour,
                daynight=(row.get("daynight") or "").strip() or None,
                confidence_band=band,
                confidence_ordinal=band_ordinal(band),
                confidence_raw=confidence_raw,
                frp=_opt_float(row, "frp"),
                scan=_opt_float(row, "scan"),
                track=_opt_float(row, "track"),
                brightness=_opt_float(row, "brightness"),
                bright_t31=_opt_float(row, "bright_t31"),
                bright_ti4=_opt_float(row, "bright_ti4"),
                bright_ti5=_opt_float(row, "bright_ti5"),
                country_id=(row.get("country_id") or "").strip() or None,
                version=(row.get("version") or "").strip() or None,
            )
        )
    return detections
