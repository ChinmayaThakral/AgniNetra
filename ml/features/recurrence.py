"""Self referential recurrence features at a location.

This is the feature family that carries the signal. A flare recurs nightly with
low radiative power variance; crop residue burning has a seasonal envelope and no
inter annual return at the same pixel; a wildfire is bursty and does not come back.

Leakage rule, and it is the whole point of this module. A feature computed for a
detection at time t uses only detections strictly before t at that location. Using
the detection itself, or anything after it, leaks the answer into the feature and
produces an evaluation number that cannot be reproduced in operation. Every
function here takes the history explicitly and asserts the ordering, rather than
filtering inside and trusting the caller to have sorted.

Every quantity here is computed a second way in the tests and the two are asserted
to agree. That habit is what caught the coordinate axis bug in phase 2a and it
costs almost nothing.
"""

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import pairwise

# Grid cell for "the same location". VIIRS is 375 m, so 0.005 degrees is roughly
# half a pixel at Indian latitudes and groups repeat detections of one source
# without merging two adjacent sources.
CELL_DEGREES = 0.005


class LeakageError(RuntimeError):
    """Raised when history contains an event at or after the reference time."""


@dataclass(frozen=True)
class Event:
    """One prior detection at a location."""

    when: datetime
    frp: float
    is_night: bool


def cell_key(longitude: float, latitude: float) -> tuple[int, int]:
    """Return the integer grid cell a coordinate falls in."""
    return (
        math.floor(longitude / CELL_DEGREES),
        math.floor(latitude / CELL_DEGREES),
    )


def _check_history(history: list[Event], now: datetime) -> None:
    if now.tzinfo is None:
        raise LeakageError("reference time must be timezone aware")
    for event in history:
        if event.when.tzinfo is None:
            raise LeakageError("history events must be timezone aware")
        if event.when >= now:
            raise LeakageError(
                f"history contains an event at {event.when.isoformat()} which is at or "
                f"after the reference time {now.isoformat()}. Features must not see "
                "the present or the future."
            )


def count_in_window(history: list[Event], now: datetime, days: int) -> int:
    """Number of prior detections within the trailing window."""
    _check_history(history, now)
    cutoff = now - timedelta(days=days)
    return sum(1 for event in history if event.when >= cutoff)


def night_fraction(history: list[Event], now: datetime, days: int = 90) -> float | None:
    """Share of prior detections in the window that were at night.

    Returns None when the window is empty, rather than 0.0. A location with no
    history is not a location that never burns at night, and filling the
    difference with a default would let the model read absence as daytime.
    """
    _check_history(history, now)
    cutoff = now - timedelta(days=days)
    window = [event for event in history if event.when >= cutoff]
    if not window:
        return None
    return sum(1 for event in window if event.is_night) / len(window)


def frp_variance(history: list[Event], now: datetime, days: int = 90) -> float | None:
    """Population variance of prior radiative power in the window.

    Low variance with a high count is the flare signature. Returns None for fewer
    than two events, where variance is not defined.
    """
    _check_history(history, now)
    cutoff = now - timedelta(days=days)
    values = [event.frp for event in history if event.when >= cutoff]
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    return sum((value - mean) ** 2 for value in values) / len(values)


def mean_inter_arrival_days(history: list[Event], now: datetime) -> float | None:
    """Mean gap in days between consecutive prior detections.

    Returns None for fewer than two events. The measure is deliberately the mean
    of gaps rather than the span divided by the count, because the two differ and
    the tests assert the intended one.
    """
    _check_history(history, now)
    if len(history) < 2:
        return None
    ordered = sorted(event.when for event in history)
    gaps = [(later - earlier).total_seconds() / 86400.0 for earlier, later in pairwise(ordered)]
    return sum(gaps) / len(gaps)


def returned_previous_year(history: list[Event], now: datetime, tolerance_days: int = 30) -> bool:
    """Whether any prior detection sits near the same calendar date a year before.

    Inter annual return at the same pixel separates a flare or an industrial site
    from a wildfire, which does not come back.
    """
    _check_history(history, now)
    target = now - timedelta(days=365)
    window = timedelta(days=tolerance_days)
    return any(abs(event.when - target) <= window for event in history)
