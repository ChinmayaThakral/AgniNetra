"""DuckDB schema for detections and for ingest provenance.

The provenance table exists from the first run rather than being added later,
because a dataset whose acquisition history was reconstructed after the fact is
not reproducible and BharatThermal-1 is meant to be.
"""

from typing import Final

import duckdb

DETECTIONS_DDL: Final[str] = """
CREATE TABLE IF NOT EXISTS detections (
    detection_id        VARCHAR PRIMARY KEY,
    source              VARCHAR NOT NULL,
    family              VARCHAR NOT NULL,
    instrument          VARCHAR NOT NULL,
    satellite           VARCHAR NOT NULL,
    latitude            DOUBLE  NOT NULL,
    longitude           DOUBLE  NOT NULL,
    acq_ts_utc          TIMESTAMPTZ NOT NULL,
    acq_ts_ist          TIMESTAMP   NOT NULL,
    acq_date_ist        DATE        NOT NULL,
    acq_hour_ist        SMALLINT    NOT NULL,
    daynight            VARCHAR,
    confidence_band     VARCHAR NOT NULL,
    confidence_ordinal  SMALLINT NOT NULL,
    confidence_raw      VARCHAR NOT NULL,
    frp                 DOUBLE,
    scan                DOUBLE,
    track               DOUBLE,
    brightness          DOUBLE,
    bright_t31          DOUBLE,
    bright_ti4          DOUBLE,
    bright_ti5          DOUBLE,
    country_id          VARCHAR,
    version             VARCHAR,
    ingest_run_id       VARCHAR NOT NULL
);
"""

INGEST_RUNS_DDL: Final[str] = """
CREATE TABLE IF NOT EXISTS ingest_runs (
    ingest_run_id       VARCHAR PRIMARY KEY,
    source              VARCHAR NOT NULL,
    bbox                VARCHAR NOT NULL,
    window_start        DATE NOT NULL,
    window_end          DATE NOT NULL,
    request_count       INTEGER NOT NULL,
    row_count           INTEGER NOT NULL,
    rows_inserted       INTEGER NOT NULL,
    transactions_before INTEGER,
    transactions_after  INTEGER,
    started_at          TIMESTAMPTZ NOT NULL,
    finished_at         TIMESTAMPTZ NOT NULL,
    notes               VARCHAR
);
"""

INDEX_DDL: Final[tuple[str, ...]] = (
    "CREATE INDEX IF NOT EXISTS detections_acq_ist ON detections (acq_date_ist);",
    "CREATE INDEX IF NOT EXISTS detections_source ON detections (source);",
    "CREATE INDEX IF NOT EXISTS detections_lat_lon ON detections (latitude, longitude);",
)


def create_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Create the detections and provenance tables and their indexes."""
    con.execute(DETECTIONS_DDL)
    con.execute(INGEST_RUNS_DDL)
    for statement in INDEX_DDL:
        con.execute(statement)
