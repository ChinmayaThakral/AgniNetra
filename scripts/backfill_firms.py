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

from ml.ingest.columns import ALL_SOURCES
from ml.ingest.firms import FirmsClient, MissingMapKeyError, day_chunks
from ml.ingest.load import insert_detections
from ml.ingest.parse import INDIA_BBOX, parse_csv
from ml.ingest.schema import create_schema
from ml.ingest.transport import RequestsTransport
from ml.paths import DUCKDB_PATH, ENV_PATH, ensure_dir

BBOX_PARAM = ",".join(str(value) for value in INDIA_BBOX)

DEFAULT_SOURCES = ("VIIRS_SNPP_SP", "VIIRS_NOAA20_SP", "MODIS_SP")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=90, help="window length in days")
    parser.add_argument("--end", type=str, default=None, help="window end, YYYY-MM-DD")
    parser.add_argument("--sources", nargs="+", default=list(DEFAULT_SOURCES))
    parser.add_argument(
        "--availability-only",
        action="store_true",
        help="print availability and map key status, write nothing",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_dotenv(ENV_PATH)

    try:
        client = FirmsClient(os.environ.get("FIRMS_MAP_KEY"), RequestsTransport())
    except MissingMapKeyError as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2

    unknown = [s for s in args.sources if s not in ALL_SOURCES]
    if unknown:
        print(f"unknown sources: {', '.join(unknown)}", file=sys.stderr)
        print(f"known: {', '.join(ALL_SOURCES)}", file=sys.stderr)
        return 2

    print("map key status before:")
    print(client.mapkey_status().strip())
    print("\ndata availability, min and max date per source:")
    availability = client.availability().strip()
    print(availability)

    if args.availability_only:
        return 0

    end = date.fromisoformat(args.end) if args.end else date.today() - timedelta(days=1)
    start = end - timedelta(days=args.days - 1)
    print(f"\nwindow {start} to {end} inclusive, {args.days} days")
    print(f"bbox {BBOX_PARAM}")

    ensure_dir(DUCKDB_PATH.parent)
    con = duckdb.connect(str(DUCKDB_PATH))
    create_schema(con)

    total_rows = 0
    total_inserted = 0
    for source in args.sources:
        run_id = str(uuid.uuid4())
        started = datetime.now(UTC)
        chunks = day_chunks(start, end)
        source_rows = 0
        source_inserted = 0
        requests_before = client.request_count

        for chunk_start, span in chunks:
            text = client.area_csv(source, BBOX_PARAM, chunk_start, span)
            detections = parse_csv(text, source)
            source_rows += len(detections)
            source_inserted += insert_detections(con, detections, run_id)

        con.execute(
            "INSERT INTO ingest_runs (ingest_run_id, source, bbox, window_start, window_end, "
            "request_count, row_count, rows_inserted, started_at, finished_at, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                source,
                BBOX_PARAM,
                start,
                end,
                client.request_count - requests_before,
                source_rows,
                source_inserted,
                started,
                datetime.now(UTC),
                None,
            ),
        )
        total_rows += source_rows
        total_inserted += source_inserted
        print(
            f"{source}: {len(chunks)} requests, {source_rows} rows parsed, "
            f"{source_inserted} inserted"
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
