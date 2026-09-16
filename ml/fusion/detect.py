"""Contextual fire detection on an INSAT-3DS India window.

A fixed brightness temperature cutoff is the wrong instrument at 4 km. A fire that
fills a fraction of a 4 km pixel raises the pixel temperature by a few kelvin, not
to a flame temperature, so a cutoff tuned to look right on a hot afternoon finds
nothing at night and finds bare rock at noon. The standard remedy is contextual:
compare a pixel against the background around it and flag the deviation.

Two channels do the work. A fire radiates far more strongly in the mid wave
infrared than in the thermal infrared, so the MIR minus TIR1 difference separates
combustion from a merely warm surface, which raises both channels together.

A third channel settles what the first two cannot. Solar reflection in the mid wave
band raises MIR above its background without any combustion, and it raises the MIR
minus TIR1 difference too, so neither test defends against sunlight. The thermal
infrared does: a fire cannot make the 11 micron channel colder than its
surroundings, while thin cloud and bare soil emissivity contrast can and do. D81.

Phase 5 puts a learned detector out of scope. This is the published contextual
threshold family, implemented plainly and swept rather than tuned, because an
unswept constant produces a number nobody can size. D70.
"""

from dataclasses import dataclass
from typing import Final

import numpy as np

from ml.fusion.solar import solar_zenith_angle_deg

# An absolute floor, and the reason it exists. Without it the contextual test alone
# returned 150 detections at 17:00 IST on 1 November 2024 whose brightest members
# sat at 248 to 256 K, which is minus 25 to minus 17 Celsius. Those are cloud tops:
# a cold cloud can show a large MIR minus TIR1 difference through solar reflection
# in the mid wave band and through emissivity differences, and a purely relative
# test cannot tell that from combustion. A fire is hot in absolute terms as well as
# relative to its surroundings. D79.
MIR_FLOOR_K: Final[float] = 300.0

# Defaults are the centre of the sweep, not a tuned optimum. Every published number
# states the sweep beside the value.
MIR_EXCESS_K: Final[float] = 4.0
DIFF_EXCESS_K: Final[float] = 4.0
BACKGROUND_RADIUS: Final[int] = 5

# How far below its own TIR1 background a candidate may sit and still be believed.
# A sub pixel fire raises the 11 micron channel slightly, so a real detection sits at
# or just above its TIR1 background. Measured on 13 raw granules from 1 November 2024:
# detections between 16:00 and 17:00 IST, which are 94 percent inside the Punjab and
# Haryana stubble burning box, have a TIR1 excess with a 10th percentile of -0.25 K and
# a median of +0.13 K. Detections between 11:00 and 12:00 IST, which are spread across
# the tropics and are the solar artifact, have a 90th percentile of -1.15 K and a median
# of -3.37 K. The two populations barely overlap. Swept from -2.0 to -0.2 K: at -1.0 the
# midday count falls 92 percent while every detection from 15:00 IST onward survives
# untouched, and tightening further starts removing genuine afternoon fires. D81.
MAX_TIR1_DEFICIT_K: Final[float] = 1.0


@dataclass(frozen=True)
class Detections:
    row: np.ndarray
    col: np.ndarray
    longitude: np.ndarray
    latitude: np.ndarray
    mir: np.ndarray
    diff: np.ndarray
    solar_zenith: np.ndarray
    valid_pixels: int

    def __len__(self) -> int:
        return int(self.row.size)


def _background_at(field: np.ndarray, rows: np.ndarray, cols: np.ndarray, radius: int):
    """Median and median absolute deviation around the given pixels only.

    Computing the statistic at every pixel costs a median over 121 neighbours for
    each of 700000 pixels and takes minutes a granule. It is also wasted: a pixel is
    only ever flagged if it first clears the absolute floor, and almost none do, so
    the background is only needed where a candidate sits. The result is identical
    because the conjunction already required the floor.
    """
    padded = np.pad(field, radius, mode="edge")
    size = 2 * radius + 1
    stack = np.empty((rows.size, size * size), dtype=np.float64)
    for index, (row, col) in enumerate(zip(rows, cols, strict=True)):
        stack[index] = padded[row : row + size, col : col + size].ravel()
    with np.errstate(invalid="ignore"):
        median = np.nanmedian(stack, axis=1)
        deviation = np.nanmedian(np.abs(stack - median[:, None]), axis=1)
    return median, deviation


def detect(
    window,
    mir_excess: float = MIR_EXCESS_K,
    diff_excess: float = DIFF_EXCESS_K,
    radius: int = BACKGROUND_RADIUS,
    mir_floor: float = MIR_FLOOR_K,
    max_tir1_deficit: float = MAX_TIR1_DEFICIT_K,
) -> Detections:
    """Flag pixels hotter than their surroundings in both the MIR and the difference.

    A pixel qualifies only if it exceeds the local background on both tests and is not
    colder than its TIR1 background. No one test is enough: MIR alone flags sunlit
    desert, the difference alone flags cloud edges where the two channels decouple,
    and both together still flag sunlit ground because solar reflection widens the
    difference as well. The TIR1 condition is what rejects that.
    """
    mir = window.mir.astype(np.float64)
    tir1 = window.tir1.astype(np.float64)
    diff = mir - tir1
    observed = np.isfinite(mir) & np.isfinite(diff)

    # The absolute floor first, because it is cheap and it is a necessary condition.
    candidate_rows, candidate_cols = np.nonzero(observed & (mir > mir_floor))
    if candidate_rows.size == 0:
        empty = np.array([], dtype=int)
        return Detections(
            row=empty,
            col=empty,
            longitude=np.array([], dtype=np.float32),
            latitude=np.array([], dtype=np.float32),
            mir=np.array([], dtype=np.float32),
            diff=np.array([], dtype=np.float32),
            solar_zenith=np.array([], dtype=np.float32),
            valid_pixels=int(observed.sum()),
        )

    mir_background, mir_spread = _background_at(mir, candidate_rows, candidate_cols, radius)
    diff_background, diff_spread = _background_at(diff, candidate_rows, candidate_cols, radius)
    tir1_background, _ = _background_at(tir1, candidate_rows, candidate_cols, radius)

    candidate_mir = mir[candidate_rows, candidate_cols]
    candidate_diff = diff[candidate_rows, candidate_cols]
    candidate_tir1 = tir1[candidate_rows, candidate_cols]
    hot = candidate_mir > (mir_background + np.maximum(mir_excess, 3.0 * mir_spread))
    signature = candidate_diff > (diff_background + np.maximum(diff_excess, 3.0 * diff_spread))
    not_colder = (candidate_tir1 - tir1_background) >= -max_tir1_deficit
    keep = hot & signature & not_colder

    rows, cols = candidate_rows[keep], candidate_cols[keep]
    return Detections(
        row=rows,
        col=cols,
        longitude=window.longitude[rows, cols],
        latitude=window.latitude[rows, cols],
        mir=window.mir[rows, cols],
        diff=diff[rows, cols].astype(np.float32),
        solar_zenith=solar_zenith_angle_deg(
            window.latitude[rows, cols], window.longitude[rows, cols], window.acquired_utc
        ).astype(np.float32),
        valid_pixels=int(observed.sum()),
    )
