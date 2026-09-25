#!/usr/bin/env python3
"""Phase 1b entry point. Backfill FIRMS detections for the India bounding box.

Nothing here runs without a map key. If the key is absent the script exits non
zero with the exact reason, and phase 1b stays blocked. It never narrows the
window silently and never writes a placeholder row.

Usage:
    uv run python scripts/backfill_firms.py --days 90
    uv run python scripts/backfill_firms.py --days 90 --sources VIIRS_SNPP_SP MODIS_SP
    uv run python scripts/backfill_firms.py --availability-only
"""

import argparse
import os
import sys
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import duckdb
from dotenv import load_dotenv

from ml.ingest.firms import (
    MIN_REQUEST_INTERVAL_SECONDS,
    FirmsClient,
    MissingMapKeyError,
    TransactionStatusError,
    day_chunks,
    parse_transactions,
)
from ml.ingest.load import insert_detections
from ml.ingest.parse import INDIA_BBOX, parse_csv
from ml.ingest.plan import (
    SENSOR_TIERS,
    assert_no_double_count,
    parse_availability,
    plan_window,
)
from ml.ingest.schema import create_schema
from ml.ingest.transport import RequestsTransport
from ml.paths import DUCKDB_PATH, ENV_PATH, ensure_dir

BBOX_PARAM = ",".join(str(value) for value in INDIA_BBOX)

# Sources are never defaulted. They are planned from the availability endpoint,
# because the standard processing and near real time tiers partition the calendar
# and asking for the wrong tier returns nothing rather than failing. D17.


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=90, help="window length in days")
    parser.add_argument("--end", type=str, default=None, help="window end, YYYY-MM-DD")
    parser.add_argument(
        "--sensors", nargs="+", default=list(SENSOR_TIERS), choices=list(SENSOR_TIERS)
    )
    parser.add_argument(
        "--min-interval",
        type=float,
        default=MIN_REQUEST_INTERVAL_SECONDS,
        help="minimum seconds between requests, to hold the issue rate",
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=DUCKDB_PATH,
        help="store to write, the project store unless a scratch copy is named",
    )
    parser.add_argument(
        "--availability-only",
        action="store_true",
        help="print availability and map key status, write nothing",
    )
    return parser.parse_args()


def read_transactions(client: FirmsClient) -> int | None:
    """The rolling transaction count, or None stored as NULL when unreadable."""
    try:
        return parse_transactions(client.mapkey_status())
    except TransactionStatusError as exc:
        print(f"transactions not recorded: {exc}", file=sys.stderr)
        return None


def main() -> int:
    args = parse_args()
    load_dotenv(ENV_PATH)

    try:
        client = FirmsClient(
            os.environ.get("FIRMS_MAP_KEY"),
            RequestsTransport(),
            min_interval=args.min_interval,
        )
    except MissingMapKeyError as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2

    print("map key status before:")
    print(client.mapkey_status().strip())

    availability_csv = client.availability()
    availability = parse_availability(availability_csv)
    print("\ndata availability, min and max date per source:")
    print(availability_csv.strip())

    if args.availability_only:
        return 0

    end = date.fromisoformat(args.end) if args.end else date.today() - timedelta(days=1)
    start = end - timedelta(days=args.days - 1)

    segments, warnings = plan_window(start, end, availability, tuple(args.sensors))
    assert_no_double_count(segments)

    print(f"\nwindow {start} to {end} inclusive, {args.days} days")
    print(f"bbox {BBOX_PARAM}")
    print("\nsource plan:")
    for segment in segments:
        print(
            f"  {segment.sensor:14s} {segment.source:18s} "
            f"{segment.start} to {segment.end}  {segment.days:3d} days"
        )
    if warnings:
        print("\nplan warnings, these belong in STATE.md:")
        for warning in warnings:
            print(f"  {warning}")
    if not segments:
        print("\nBLOCKED: no source covers the requested window", file=sys.stderr)
        return 2

    ensure_dir(args.database.parent)
    con = duckdb.connect(str(args.database))
    create_schema(con)

    total_rows = 0
    total_inserted = 0
    for segment in segments:
        run_id = str(uuid.uuid4())
        started = datetime.now(UTC)
        chunks = day_chunks(segment.start, segment.end)
        segment_rows = 0
        segment_inserted = 0
        # Read before the request baseline, so the status call is not counted as one
        # of the run's requests.
        transactions_before = read_transactions(client)
        requests_before = client.request_count

        for chunk_start, span in chunks:
            text = client.area_csv(segment.source, BBOX_PARAM, chunk_start, span)
            detections = parse_csv(text, segment.source)
            segment_rows += len(detections)
            segment_inserted += insert_detections(con, detections, run_id)

        con.execute(
            "INSERT INTO ingest_runs (ingest_run_id, source, bbox, window_start, window_end, "
            "request_count, row_count, rows_inserted, transactions_before, "
            "transactions_after, started_at, finished_at, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                segment.source,
                BBOX_PARAM,
                segment.start,
                segment.end,
                client.request_count - requests_before,
                segment_rows,
                segment_inserted,
                transactions_before,
                read_transactions(client),
                started,
                datetime.now(UTC),
                f"sensor {segment.sensor}",
            ),
        )
        total_rows += segment_rows
        total_inserted += segment_inserted
        print(
            f"{segment.source}: {len(chunks)} requests, {segment_rows} rows parsed, "
            f"{segment_inserted} inserted"
        )

    print(f"\ntotal parsed {total_rows}, total inserted {total_inserted}")
    print(f"requests issued this run: {client.request_count}")
    print("\nper source in the store:")
    for row in con.execute(
        "SELECT source, count(*) FROM detections GROUP BY source ORDER BY 2 DESC"
    ).fetchall():
        print(f"  {row[0]}: {row[1]}")
    print(f"total rows: {con.execute('SELECT count(*) FROM detections').fetchone()[0]}")

    print("\nmap key status after:")
    print(client.mapkey_status().strip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
