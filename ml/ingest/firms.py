"""FIRMS area endpoint client.

Transport is injected so that the whole client is exercised without network
access. The default transport uses requests; the test suite passes a stub that
returns fixture text.

Day range cap. The FIRMS area API documents the day range parameter as "1 .. 5",
so a ninety day backfill is a chunked loop of at least eighteen requests, not one
call. The cap is a named constant rather than a literal so that a documentation
change is a one line edit with a recorded reason.

Transactions. The documented limit is 5000 transactions per 10 minute interval,
and the documentation states that larger transactions may count as more than one.
The client therefore counts requests issued, and the backfill records the map key
status before and after so that the true transaction cost is measured rather than
inferred.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Final, Protocol

BASE: Final[str] = "https://firms.modaps.eosdis.nasa.gov"
AREA_URL: Final[str] = BASE + "/api/area/csv/{key}/{source}/{bbox}/{days}/{start}"
AVAILABILITY_URL: Final[str] = BASE + "/api/data_availability/csv/{key}/all"
MAPKEY_STATUS_URL: Final[str] = BASE + "/mapserver/mapkey_status/?MAP_KEY={key}"

MAX_DAY_RANGE: Final[int] = 5
RETRY_STATUSES: Final[frozenset[int]] = frozenset({429, 500, 502, 503, 504})
MAX_ATTEMPTS: Final[int] = 5
BACKOFF_BASE_SECONDS: Final[float] = 2.0

# Measured on 2026-09-04: 74 requests over about 5 minutes, roughly 15 per
# minute, held the rolling 10 minute transaction counter at a peak of 1365
# against a limit of 5000. The constraint is a rate, not a quota, so the client
# paces itself rather than tracking a budget.
MIN_REQUEST_INTERVAL_SECONDS: Final[float] = 4.0


@dataclass(frozen=True)
class Response:
    """The subset of an HTTP response this client needs."""

    status: int
    text: str


class Transport(Protocol):
    """Anything that can fetch a URL and return a Response."""

    def get(self, url: str) -> Response: ...


class MissingMapKeyError(RuntimeError):
    """Raised when no FIRMS map key is available."""


class FirmsRequestError(RuntimeError):
    """Raised when the endpoint fails after every retry."""


def day_chunks(start: date, end: date, cap: int = MAX_DAY_RANGE) -> list[tuple[date, int]]:
    """Split an inclusive date window into (chunk start, day count) pairs.

    Chunks do not overlap. Idempotency does not depend on that, since the
    detection identifier absorbs any overlap, but a non overlapping split spends
    fewer transactions.
    """
    if end < start:
        raise ValueError(f"window end {end} is before window start {start}")
    if cap < 1:
        raise ValueError(f"day range cap must be at least 1, got {cap}")

    chunks: list[tuple[date, int]] = []
    cursor = start
    while cursor <= end:
        remaining = (end - cursor).days + 1
        span = min(cap, remaining)
        chunks.append((cursor, span))
        cursor += timedelta(days=span)
    return chunks


class FirmsClient:
    """Client for the FIRMS area, availability and map key status endpoints."""

    def __init__(
        self,
        map_key: str | None,
        transport: Transport,
        sleep: Callable[[float], None] = time.sleep,
        min_interval: float = 0.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not map_key or not map_key.strip():
            raise MissingMapKeyError(
                "FIRMS_MAP_KEY is empty. Put it in .env. Request one at "
                "https://firms.modaps.eosdis.nasa.gov/api/map_key/"
            )
        self._key = map_key.strip()
        self._transport = transport
        self._sleep = sleep
        self._min_interval = min_interval
        self._clock = clock
        self._last_request_at: float | None = None
        self.request_count = 0

    def _fetch(self, url: str) -> str:
        """Fetch with exponential backoff on the retryable statuses."""
        last_status = None
        for attempt in range(MAX_ATTEMPTS):
            self._pace()
            self.request_count += 1
            response = self._transport.get(url)
            last_status = response.status
            if response.status == 200:
                return response.text
            if response.status not in RETRY_STATUSES:
                raise FirmsRequestError(
                    f"FIRMS returned status {response.status} for {self._redact(url)}. "
                    f"Body starts: {response.text[:200]!r}"
                )
            if attempt < MAX_ATTEMPTS - 1:
                self._sleep(BACKOFF_BASE_SECONDS * (2**attempt))
        raise FirmsRequestError(
            f"FIRMS still returning {last_status} after {MAX_ATTEMPTS} attempts "
            f"for {self._redact(url)}"
        )

    def _pace(self) -> None:
        """Hold the issue rate below the configured interval."""
        if self._min_interval <= 0:
            return
        now = self._clock()
        if self._last_request_at is not None:
            wait = self._min_interval - (now - self._last_request_at)
            if wait > 0:
                self._sleep(wait)
                now = self._clock()
        self._last_request_at = now

    def _redact(self, url: str) -> str:
        return url.replace(self._key, "MAP_KEY_REDACTED")

    def availability(self) -> str:
        """Return the data availability CSV, reporting min and max date per source.

        Redacted for the same reason as mapkey_status: callers print it.
        """
        return self._redact(self._fetch(AVAILABILITY_URL.format(key=self._key)))

    def mapkey_status(self) -> str:
        """Return the map key status response, reporting transactions used.

        Redacted on the way out. The body is third party text that callers print to
        stdout and into `data/*.log`, and the standing rule here is that the key is
        never printed or logged. It does not contain the key in FIRMS's current
        responses; redacting rather than trusting that is what keeps the rule true if
        the upstream response ever echoes the request.
        """
        return self._redact(self._fetch(MAPKEY_STATUS_URL.format(key=self._key)))

    def area_csv(self, source: str, bbox: str, start: date, days: int) -> str:
        """Fetch one area chunk. days must not exceed the documented cap."""
        if days > MAX_DAY_RANGE:
            raise ValueError(
                f"day range {days} exceeds the documented cap of {MAX_DAY_RANGE}. "
                "Split the window with day_chunks()."
            )
        return self._fetch(
            AREA_URL.format(
                key=self._key,
                source=source,
                bbox=bbox,
                days=days,
                start=start.isoformat(),
            )
        )
