"""Source planning: which FIRMS source serves which part of a window.

Standard processing lags near real time, and the two tiers partition the calendar
rather than overlapping. Measured from the availability endpoint on 2026-09-04:

    VIIRS_SNPP_SP    2012-01-20 to 2026-04-27
    VIIRS_SNPP_NRT   2026-04-28 to 2026-09-03
    VIIRS_NOAA20_SP  2018-04-01 to 2026-05-31
    VIIRS_NOAA20_NRT 2026-06-01 to 2026-09-03
    VIIRS_NOAA21_NRT 2024-01-17 to 2026-09-03, no SP tier
    MODIS_SP         2000-11-01 to 2026-04-30
    MODIS_NRT        2026-05-01 to 2026-09-03

Each SP tier ends exactly one day before its NRT tier begins, so a window is
covered without a gap and without a double count. Asking for the wrong tier
returns nothing rather than failing, which is why the plan is derived from the
endpoint rather than from a default.

The detection identifier does not include the source or the processing tier, so
even if the tiers did overlap the same physical detection would collapse to one
row. The planner avoids paying for the duplicate request; the identifier is what
guarantees correctness.
"""

from dataclasses import dataclass
from datetime import date
from itertools import pairwise
from typing import Final

# Sensor families and their tiers, most recent tier last.
SENSOR_TIERS: Final[dict[str, tuple[str, ...]]] = {
    "modis": ("MODIS_SP", "MODIS_NRT"),
    "viirs_snpp": ("VIIRS_SNPP_SP", "VIIRS_SNPP_NRT"),
    "viirs_noaa20": ("VIIRS_NOAA20_SP", "VIIRS_NOAA20_NRT"),
    "viirs_noaa21": ("VIIRS_NOAA21_NRT",),
}


@dataclass(frozen=True)
class Segment:
    """One contiguous stretch of a window served by one source."""

    sensor: str
    source: str
    start: date
    end: date

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


def parse_availability(csv_text: str) -> dict[str, tuple[date, date]]:
    """Parse the availability CSV into source -> (min_date, max_date)."""
    availability: dict[str, tuple[date, date]] = {}
    for line in csv_text.strip().splitlines()[1:]:
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 3:
            continue
        source, min_raw, max_raw = parts[0], parts[1], parts[2]
        try:
            availability[source] = (date.fromisoformat(min_raw), date.fromisoformat(max_raw))
        except ValueError:
            continue
    return availability


def plan_window(
    start: date,
    end: date,
    availability: dict[str, tuple[date, date]],
    sensors: tuple[str, ...] = tuple(SENSOR_TIERS),
) -> tuple[list[Segment], list[str]]:
    """Return the segments covering the window, and any warnings.

    A warning is raised as text rather than an exception when a sensor covers only
    part of the window, because partial coverage is a real property of the archive
    and not an error. It must reach STATE.md rather than being silently dropped.
    """
    segments: list[Segment] = []
    warnings: list[str] = []

    for sensor in sensors:
        covered_days = 0
        for source in SENSOR_TIERS[sensor]:
            if source not in availability:
                warnings.append(f"{source} absent from the availability response")
                continue
            source_min, source_max = availability[source]
            segment_start = max(start, source_min)
            segment_end = min(end, source_max)
            if segment_start > segment_end:
                continue
            segments.append(Segment(sensor, source, segment_start, segment_end))
            covered_days += (segment_end - segment_start).days + 1

        window_days = (end - start).days + 1
        if covered_days == 0:
            warnings.append(f"{sensor} covers none of {start} to {end}")
        elif covered_days < window_days:
            warnings.append(
                f"{sensor} covers {covered_days} of {window_days} days in {start} to {end}"
            )

    return segments, warnings


def assert_no_double_count(segments: list[Segment]) -> None:
    """Raise if two segments for one sensor cover the same day."""
    by_sensor: dict[str, list[Segment]] = {}
    for segment in segments:
        by_sensor.setdefault(segment.sensor, []).append(segment)
    for sensor, items in by_sensor.items():
        ordered = sorted(items, key=lambda s: s.start)
        for earlier, later in pairwise(ordered):
            if later.start <= earlier.end:
                raise ValueError(
                    f"{sensor} segments overlap: {earlier.source} ends {earlier.end} "
                    f"and {later.source} starts {later.start}. The window would be "
                    "requested twice and paid for twice."
                )
