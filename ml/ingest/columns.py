"""Documented FIRMS CSV column sets, per source family.

Taken from the FIRMS API documentation rather than from a downloaded sample,
because the column set differs between sensor families and a sample encodes only
the one family it came from.

Verified against the FIRMS API pages on 2026-09-03:
https://firms.modaps.eosdis.nasa.gov/api/area/
https://firms.modaps.eosdis.nasa.gov/content/academy/data_api/firms_api_use.html
"""

from typing import Final

VIIRS_COLUMNS: Final[tuple[str, ...]] = (
    "latitude",
    "longitude",
    "bright_ti4",
    "scan",
    "track",
    "acq_date",
    "acq_time",
    "satellite",
    "instrument",
    "confidence",
    "version",
    "bright_ti5",
    "frp",
    "daynight",
)

MODIS_COLUMNS: Final[tuple[str, ...]] = (
    "latitude",
    "longitude",
    "brightness",
    "scan",
    "track",
    "acq_date",
    "acq_time",
    "satellite",
    "instrument",
    "confidence",
    "version",
    "bright_t31",
    "frp",
    "daynight",
)

# The union is what the detections table stores. MODIS carries country_id,
# brightness and bright_t31; VIIRS carries bright_ti4 and bright_ti5. A column
# absent from a source is stored as NULL rather than as a filled default, so that
# a missing value is distinguishable from a measured zero.
# country_id is carried in the union, and therefore in the schema, even though the
# area endpoint does not return it. The archive download product does, so a later
# backfill from that product can populate it without a schema change.
UNION_COLUMNS: Final[tuple[str, ...]] = tuple(
    dict.fromkeys((*VIIRS_COLUMNS, *MODIS_COLUMNS, "country_id"))
)

# Columns the documentation lists but the area endpoint does not return. Measured
# against the live MODIS_NRT area endpoint on 2026-09-04: the documented MODIS set
# has 15 columns including country_id, the area response has 14 without it. The
# documented set describes the archive download product, not this endpoint. D18.
OPTIONAL_COLUMNS: Final[frozenset[str]] = frozenset({"country_id"})

VIIRS_SOURCES: Final[tuple[str, ...]] = (
    "VIIRS_SNPP_NRT",
    "VIIRS_SNPP_SP",
    "VIIRS_NOAA20_NRT",
    "VIIRS_NOAA20_SP",
    "VIIRS_NOAA21_NRT",
)

MODIS_SOURCES: Final[tuple[str, ...]] = (
    "MODIS_NRT",
    "MODIS_SP",
)

ALL_SOURCES: Final[tuple[str, ...]] = VIIRS_SOURCES + MODIS_SOURCES


def required_columns_for(source: str) -> tuple[str, ...]:
    """Return the columns a response must carry for the source to be parseable."""
    return tuple(c for c in columns_for(source) if c not in OPTIONAL_COLUMNS)


def columns_for(source: str) -> tuple[str, ...]:
    """Return the documented column set for a FIRMS source name."""
    if source in VIIRS_SOURCES:
        return VIIRS_COLUMNS
    if source in MODIS_SOURCES:
        return MODIS_COLUMNS
    raise ValueError(f"unknown FIRMS source: {source!r}. Known: {', '.join(ALL_SOURCES)}")


def family_for(source: str) -> str:
    """Return 'viirs' or 'modis' for a FIRMS source name."""
    if source in VIIRS_SOURCES:
        return "viirs"
    if source in MODIS_SOURCES:
        return "modis"
    raise ValueError(f"unknown FIRMS source: {source!r}")
