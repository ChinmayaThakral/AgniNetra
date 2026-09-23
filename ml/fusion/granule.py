"""Read one INSAT-3DS L1C granule, window it to India and calibrate it.

The product stores each channel as a 10 bit grey count with a per channel lookup
table mapping count to brightness temperature in kelvin. The table is the
calibration, so a count is meaningless without it and no arithmetic is done on
counts anywhere in this module.
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import h5py
import numpy as np

from ml.fusion.geolocate import forward

# The ingest bounding box, matching the one the detections were pulled against.
INDIA_WEST: Final[float] = 68.0
INDIA_EAST: Final[float] = 97.5
INDIA_SOUTH: Final[float] = 6.5
INDIA_NORTH: Final[float] = 37.5

FILL_COUNT: Final[int] = 1023
_NAME = re.compile(r"3SIMG_(\d{2})([A-Z]{3})(\d{4})_(\d{2})(\d{2})_")
_MONTHS: Final[dict[str, int]] = {
    m: i + 1
    for i, m in enumerate(
        ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
    )
}


class GranuleError(RuntimeError):
    """Raised when a granule cannot be read or does not cover the window."""


@dataclass(frozen=True)
class IndiaWindow:
    """One granule, cut to India and calibrated to kelvin."""

    acquired_utc: datetime
    mir: np.ndarray
    tir1: np.ndarray
    longitude: np.ndarray
    latitude: np.ndarray
    source: str

    @property
    def acquired_ist(self) -> datetime:
        from datetime import timedelta

        return self.acquired_utc + timedelta(hours=5, minutes=30)

    @property
    def hour_ist(self) -> int:
        return self.acquired_ist.hour


def time_from_name(name: str) -> datetime:
    """Parse the acquisition time from the granule file name, in UTC.

    The file name is the authority rather than the attributes, because a granule is
    identified by name everywhere else in this pipeline and a mismatch between the
    two would otherwise pass silently.
    """
    match = _NAME.search(name)
    if not match:
        raise GranuleError(f"cannot parse an acquisition time from {name!r}")
    day, month, year, hour, minute = match.groups()
    if month not in _MONTHS:
        raise GranuleError(f"unknown month {month!r} in {name!r}")
    return datetime(int(year), _MONTHS[month], int(day), int(hour), int(minute), tzinfo=UTC)


def read_india(path: Path) -> IndiaWindow:
    """Return the India window of one granule with MIR and TIR1 in kelvin.

    Raises GranuleError rather than returning an empty array when the window falls
    outside the grid, because an empty window that reaches a histogram reads as an
    hour with no fire.
    """
    acquired = time_from_name(path.name)
    with h5py.File(path, "r") as handle:
        x_axis = handle["X"][:]
        y_axis = handle["Y"][:]

        west_x, north_y = forward(longitude=INDIA_WEST, latitude=INDIA_NORTH)
        east_x, south_y = forward(longitude=INDIA_EAST, latitude=INDIA_SOUTH)
        cols = np.where((x_axis >= float(west_x)) & (x_axis <= float(east_x)))[0]
        rows = np.where((y_axis >= float(south_y)) & (y_axis <= float(north_y)))[0]
        if cols.size == 0 or rows.size == 0:
            raise GranuleError(f"{path.name} does not cover the India window")

        row_slice = slice(int(rows.min()), int(rows.max()) + 1)
        col_slice = slice(int(cols.min()), int(cols.max()) + 1)

        def calibrated(channel: str) -> np.ndarray:
            counts = handle[f"IMG_{channel}"][0, row_slice, col_slice]
            table = handle[f"IMG_{channel}_TEMP"][:]
            kelvin = table[np.clip(counts, 0, table.size - 1)].astype(np.float32)
            # The top count is the fill value as well as the hottest bin, so a
            # pixel sitting on it is not a measurement.
            return np.where(counts >= FILL_COUNT, np.nan, kelvin)

        mir = calibrated("MIR")
        tir1 = calibrated("TIR1")
        grid_x, grid_y = np.meshgrid(x_axis[col_slice], y_axis[row_slice])

    from ml.fusion.geolocate import inverse

    longitude, latitude = inverse(x=grid_x, y=grid_y)
    return IndiaWindow(
        acquired_utc=acquired,
        mir=mir,
        tir1=tir1,
        longitude=longitude.astype(np.float32),
        latitude=latitude.astype(np.float32),
        source=path.name,
    )
