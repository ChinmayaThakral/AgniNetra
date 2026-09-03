"""Acquisition time handling.

FIRMS reports acq_date as YYYY-MM-DD and acq_time as an integer HHMM in UTC, with
no zero padding, so 138 means 01:38 and 45 means 00:45. Parsing that as a string
without padding is the standard way this breaks.

Storage rule: UTC is authoritative and IST is derived and stored alongside it.
Both are stored. Storing only UTC would push a timezone conversion into every
phase 5 query, and storing only IST would lose the sensor's own reference frame.
The published finding this project responds to is stated in IST, so the IST date
and hour are first class columns rather than expressions.
"""

from datetime import UTC, datetime, timedelta, timezone
from typing import Final

IST: Final[timezone] = timezone(timedelta(hours=5, minutes=30), name="IST")


def parse_acq_timestamp(acq_date: str, acq_time: str | int) -> datetime:
    """Combine a FIRMS acq_date and acq_time into a timezone aware UTC datetime.

    acq_time is an HHMM integer that FIRMS does not zero pad.
    """
    raw = str(acq_time).strip()
    if not raw.isdigit():
        raise ValueError(f"acq_time is not numeric: {acq_time!r}")
    padded = raw.zfill(4)
    hour, minute = int(padded[:2]), int(padded[2:])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"acq_time out of range: {acq_time!r} parsed as {hour:02d}:{minute:02d}")
    day = datetime.strptime(acq_date.strip(), "%Y-%m-%d").date()
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC)


def to_ist(moment: datetime) -> datetime:
    """Convert a timezone aware datetime to IST."""
    if moment.tzinfo is None:
        raise ValueError("refusing to convert a naive datetime, the offset would be a guess")
    return moment.astimezone(IST)
