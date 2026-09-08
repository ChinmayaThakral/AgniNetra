"""Contextual fire detection on an INSAT-3DS India window.

A fixed brightness temperature cutoff is the wrong instrument at 4 km. A fire that
fills a fraction of a 4 km pixel raises the pixel temperature by a few kelvin, not
to a flame temperature, so a cutoff tuned to look right on a hot afternoon finds
nothing at night and finds bare rock at noon. The standard remedy is contextual:
compare a pixel against the background around it and flag the deviation.

Two channels do the work. A fire radiates far more strongly in the mid wave
infrared than in the thermal infrared, so the MIR minus TIR1 difference separates
combustion from a merely warm surface, which raises both channels together.

Phase 5 puts a learned detector out of scope. This is the published contextual
threshold family, implemented plainly and swept rather than tuned, because an
unswept constant produces a number nobody can size. D70.
"""

from dataclasses import dataclass
from typing import Final

import numpy as np

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


@dataclass(frozen=True)
class Detections:
    row: np.ndarray
    col: np.ndarray
    longitude: np.ndarray
    latitude: np.ndarray
    mir: np.ndarray
    diff: np.ndarray
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
) -> Detections:
    """Flag pixels hotter than their surroundings in both the MIR and the difference.

    A pixel qualifies only if it exceeds the local background on both tests. Either
    alone is not enough: MIR alone flags sunlit desert, and the difference alone
    flags cloud edges where the two channels decouple.
    """
    mir = window.mir.astype(np.float64)
    diff = (window.mir - window.tir1).astype(np.float64)
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
            valid_pixels=int(observed.sum()),
        )

    mir_background, mir_spread = _background_at(mir, candidate_rows, candidate_cols, radius)
    diff_background, diff_spread = _background_at(diff, candidate_rows, candidate_cols, radius)

    candidate_mir = mir[candidate_rows, candidate_cols]
    candidate_diff = diff[candidate_rows, candidate_cols]
    hot = candidate_mir > (mir_background + np.maximum(mir_excess, 3.0 * mir_spread))
    signature = candidate_diff > (diff_background + np.maximum(diff_excess, 3.0 * diff_spread))
    keep = hot & signature

    rows, cols = candidate_rows[keep], candidate_cols[keep]
    return Detections(
        row=rows,
        col=cols,
        longitude=window.longitude[rows, cols],
        latitude=window.latitude[rows, cols],
        mir=window.mir[rows, cols],
        diff=(window.mir - window.tir1)[rows, cols],
        valid_pixels=int(observed.sum()),
    )
