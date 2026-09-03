"""Confidence normalisation across the two sensor families.

MODIS reports an integer 0 to 100. VIIRS reports one of l, n, h. Both are mapped
onto one ordinal band and the raw value is kept in its own column so nothing is
discarded.

The FIRMS FAQ states that MODIS assigns detections to low, nominal and high
classes but does not publish the cut points. The 0 to 29, 30 to 79, 80 to 100
split used here is the split in common use with this product. It is a project
decision, recorded as D6, and it is marked unverified in context/RESEARCH.md until
someone confirms it against the Collection 6 user guide.
"""

from typing import Final

BAND_LOW: Final[str] = "low"
BAND_NOMINAL: Final[str] = "nominal"
BAND_HIGH: Final[str] = "high"

ORDINAL: Final[dict[str, int]] = {BAND_LOW: 0, BAND_NOMINAL: 1, BAND_HIGH: 2}

MODIS_NOMINAL_FLOOR: Final[int] = 30
MODIS_HIGH_FLOOR: Final[int] = 80

_VIIRS_MAP: Final[dict[str, str]] = {
    "l": BAND_LOW,
    "n": BAND_NOMINAL,
    "h": BAND_HIGH,
    "low": BAND_LOW,
    "nominal": BAND_NOMINAL,
    "high": BAND_HIGH,
}


def normalise_modis(raw: str | int) -> str:
    """Map a MODIS 0 to 100 confidence integer onto the ordinal band."""
    try:
        value = int(str(raw).strip())
    except ValueError as exc:
        raise ValueError(f"MODIS confidence is not an integer: {raw!r}") from exc
    if not 0 <= value <= 100:
        raise ValueError(f"MODIS confidence out of range 0 to 100: {value}")
    if value >= MODIS_HIGH_FLOOR:
        return BAND_HIGH
    if value >= MODIS_NOMINAL_FLOOR:
        return BAND_NOMINAL
    return BAND_LOW


def normalise_viirs(raw: str) -> str:
    """Map a VIIRS categorical confidence onto the ordinal band."""
    key = str(raw).strip().lower()
    if key not in _VIIRS_MAP:
        raise ValueError(f"VIIRS confidence not one of l, n, h: {raw!r}")
    return _VIIRS_MAP[key]


def normalise(family: str, raw: str | int) -> str:
    """Dispatch on sensor family."""
    if family == "modis":
        return normalise_modis(raw)
    if family == "viirs":
        return normalise_viirs(str(raw))
    raise ValueError(f"unknown sensor family: {family!r}")


def band_ordinal(band: str) -> int:
    """Return the sortable integer for a band."""
    if band not in ORDINAL:
        raise ValueError(f"unknown confidence band: {band!r}")
    return ORDINAL[band]
