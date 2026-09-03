"""Loading parsed detections into DuckDB, with the fixture guard.

The guard is the reason this module exists separately from the parser. A fixture
row must be usable by the test suite and must never reach the detections table on
a real run, so the refusal lives at the write boundary where it cannot be
bypassed by a caller that forgot to filter.
"""

import duckdb

from ml.ingest.parse import FIXTURE_MARKER, Detection

INSERT_COLUMNS = (
    "detection_id",
    "source",
    "family",
    "instrument",
    "satellite",
    "latitude",
    "longitude",
    "acq_ts_utc",
    "acq_ts_ist",
    "acq_date_ist",
    "acq_hour_ist",
    "daynight",
    "confidence_band",
    "confidence_ordinal",
    "confidence_raw",
    "frp",
    "scan",
    "track",
    "brightness",
    "bright_t31",
    "bright_ti4",
    "bright_ti5",
    "country_id",
    "version",
    "ingest_run_id",
)


class FixtureRowRefusedError(RuntimeError):
    """Raised when a row carrying the fixture marker reaches a real write."""


def _row_tuple(detection: Detection, ingest_run_id: str) -> tuple[object, ...]:
    return (
        detection.detection_id,
        detection.source,
        detection.family,
        detection.instrument,
        detection.satellite,
        detection.latitude,
        detection.longitude,
        detection.acq_ts_utc,
        detection.acq_ts_ist.replace(tzinfo=None),
        detection.acq_date_ist,
        detection.acq_hour_ist,
        detection.daynight,
        detection.confidence_band,
        detection.confidence_ordinal,
        detection.confidence_raw,
        detection.frp,
        detection.scan,
        detection.track,
        detection.brightness,
        detection.bright_t31,
        detection.bright_ti4,
        detection.bright_ti5,
        detection.country_id,
        detection.version,
        ingest_run_id,
    )


def insert_detections(
    con: duckdb.DuckDBPyConnection,
    detections: list[Detection],
    ingest_run_id: str,
    allow_fixture_rows: bool = False,
) -> int:
    """Insert detections, skipping identifiers already present. Returns rows inserted.

    allow_fixture_rows is set only by the test suite. On any other call a row
    carrying the fixture marker in its version column raises rather than being
    filtered out silently, because a silent filter would let a fixture reach a
    real run and disappear without a trace.
    """
    if not allow_fixture_rows:
        offenders = [d.detection_id for d in detections if d.version == FIXTURE_MARKER]
        if offenders:
            raise FixtureRowRefusedError(
                f"{len(offenders)} row(s) carry the {FIXTURE_MARKER} marker and cannot be "
                f"written to detections. First identifier: {offenders[0]}"
            )

    # A chunk covering a quiet window legitimately returns no rows, and
    # executemany rejects an empty parameter list.
    if not detections:
        return 0

    before = con.execute("SELECT count(*) FROM detections").fetchone()
    before_count = int(before[0]) if before else 0

    placeholders = ", ".join(["?"] * len(INSERT_COLUMNS))
    con.executemany(
        f"INSERT OR IGNORE INTO detections ({', '.join(INSERT_COLUMNS)}) VALUES ({placeholders})",
        [_row_tuple(d, ingest_run_id) for d in detections],
    )

    after = con.execute("SELECT count(*) FROM detections").fetchone()
    after_count = int(after[0]) if after else 0
    return after_count - before_count
