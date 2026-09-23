"""Deterministic detection identifiers.

The identifier is a BLAKE2b digest over the sensor, the rounded coordinates and
the UTC acquisition timestamp. It exists so that re ingesting an overlapping
window is a no op rather than a duplicate insert, which matters because the
backfill loop chunks by day range and adjacent chunks can overlap at the seam.

Coordinates are rounded to five decimal places before hashing. FIRMS publishes
coordinates at five decimals, so this preserves the product's own precision while
removing float representation noise that would otherwise produce two identifiers
for one detection.
"""

import hashlib
from datetime import UTC, datetime
from typing import Final

COORD_DECIMALS: Final[int] = 5
DIGEST_BYTES: Final[int] = 16


def round_coord(value: float | str) -> str:
    """Round a coordinate to the product precision and render it canonically."""
    return f"{round(float(value), COORD_DECIMALS):.{COORD_DECIMALS}f}"


def detection_id(
    *,
    instrument: str,
    satellite: str,
    latitude: float | str,
    longitude: float | str,
    acq_utc: datetime,
) -> str:
    """Return the deterministic identifier for one detection.

    acq_utc must be timezone aware, and is normalised to UTC before hashing so
    that the same instant expressed in any offset yields the same identifier. A
    naive datetime would make the identifier depend on the machine's local zone,
    which would silently break idempotency across the team's laptops.
    """
    if acq_utc.tzinfo is None:
        raise ValueError("acq_utc must be timezone aware, otherwise the id is machine dependent")

    parts = (
        str(instrument).strip().upper(),
        str(satellite).strip().upper(),
        round_coord(latitude),
        round_coord(longitude),
        acq_utc.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    payload = "|".join(parts).encode("utf-8")
    return hashlib.blake2b(payload, digest_size=DIGEST_BYTES).hexdigest()
