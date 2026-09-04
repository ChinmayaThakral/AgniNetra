#!/usr/bin/env python3
"""Phase 2b: load the Global Energy Monitor trackers with provenance.

Four sectors, four trackers. Status filtering and operating windows are applied at
load, and both are reported so the decision is attributable rather than absorbed.

Usage:
    uv run python scripts/load_gem_2b.py
"""

import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import duckdb
import openpyxl

from ml.paths import DUCKDB_PATH, ROOT
from ml.reference.gem import load_tracker
from ml.reference.geo import install_geo
from ml.reference.provenance import create_provenance, record_layer

GEM = ROOT / "data" / "reference" / "gem"

DDL = """
CREATE OR REPLACE TABLE ref_gem_assets (
    asset_id      INTEGER PRIMARY KEY,
    sector        VARCHAR NOT NULL,
    tracker       VARCHAR NOT NULL,
    name          VARCHAR,
    latitude      DOUBLE NOT NULL,
    longitude     DOUBLE NOT NULL,
    status        VARCHAR NOT NULL,
    start_year    INTEGER,
    retired_year  INTEGER,
    capacity      DOUBLE,
    subnational   VARCHAR
);
"""

POWER = "Global Integrated Power August 2026-v3.xlsx"
COAL = "Global Coal Mine Tracker, August 2026.xlsx"
STEEL = "Plant-level_data_Global_Iron_and_Steel_Tracker_June_2026_V1.xlsx"
CEMENT = "Plant-level data - Global Cement and Concrete Tracker - July 2026 - Standard Copy V1.xlsx"

# Release dates as printed on each tracker's file name and About sheet.
RELEASES = {
    POWER: "August 2026",
    COAL: "August 2026",
    STEEL: "June 2026",
    CEMENT: "July 2026",
}


def steel_status_by_id() -> dict[str, str]:
    """Steel carries status on a second sheet, keyed by GEM plant ID."""
    workbook = openpyxl.load_workbook(GEM / STEEL, read_only=True, data_only=True)
    sheet = workbook["Plant capacities and status"]
    rows = sheet.iter_rows(values_only=True)
    header = [str(c).strip() if c is not None else "" for c in next(rows)]
    id_index = header.index("GEM plant ID")
    status_index = header.index("Status")
    mapping: dict[str, str] = {}
    for row in rows:
        key = str(row[id_index]).strip()
        if key and key not in mapping:
            mapping[key] = str(row[status_index] or "").strip()
    workbook.close()
    return mapping


def main() -> int:
    con = duckdb.connect(str(DUCKDB_PATH))
    install_geo(con)
    create_provenance(con)
    con.execute(DDL)

    steel_status = steel_status_by_id()
    specs = [
        (
            "power",
            POWER,
            "Power facilities",
            "Country/area",
            "Status",
            "Plant / Project name",
            "Start year",
            "Retired year",
            "Capacity (MW)",
            "Subnational unit (state, province)",
            None,
            None,
        ),
        (
            "coal_mine",
            COAL,
            "Non-closed mines",
            "Country / Area",
            "Status",
            "Mine Name",
            "Opening Year",
            "Closing Year",
            "Capacity (Mtpa)",
            "State, Province",
            None,
            None,
        ),
        (
            "steel",
            STEEL,
            "Plant data",
            "Country/area",
            None,
            "Plant name (English)",
            "Start date",
            "Retired date",
            None,
            "Subnational unit",
            steel_status,
            "GEM plant ID",
        ),
        (
            "cement",
            CEMENT,
            "Final data",
            "Country/area",
            "Operating status",
            "Plant name (English)",
            "Start date",
            None,
            "Cement capacity (million metric tonnes per annum)",
            "Subnational unit",
            None,
            None,
        ),
    ]

    all_assets = []
    now = datetime.now(UTC)
    for (
        sector,
        filename,
        sheet,
        country_col,
        status_col,
        name_col,
        start_col,
        retired_col,
        capacity_col,
        sub_col,
        by_id,
        id_col,
    ) in specs:
        assets, tally = load_tracker(
            GEM / filename,
            sheet,
            sector,
            country_col,
            status_col,
            name_col,
            start_col,
            retired_col,
            capacity_col,
            sub_col,
            by_id,
            id_col,
        )
        kept = len(assets)
        seen = sum(tally.values())
        print(f"\n{sector}: {filename}")
        print(f"  India rows {seen}, kept {kept}, dropped {seen - kept}")
        for status, count in sorted(tally.items(), key=lambda kv: -kv[1]):
            mark = "keep" if status in ("operating", "retired", "mothballed") else "drop"
            print(f"    {mark}  {status:28s} {count}")
        with_window = sum(1 for a in assets if a.start_year is not None)
        with_retire = sum(1 for a in assets if a.retired_year is not None)
        print(f"  start year known {with_window}/{kept}, retired year known {with_retire}")
        all_assets.extend(assets)

    con.executemany(
        "INSERT INTO ref_gem_assets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                i,
                a.sector,
                a.tracker,
                a.name,
                a.latitude,
                a.longitude,
                a.status,
                a.start_year,
                a.retired_year,
                a.capacity,
                a.subnational,
            )
            for i, a in enumerate(all_assets)
        ],
    )
    for sector in ("power", "coal_mine", "steel", "cement"):
        count = int(
            con.execute(
                "SELECT count(*) FROM ref_gem_assets WHERE sector = ?", [sector]
            ).fetchone()[0]
        )
        tracker = next(a.tracker for a in all_assets if a.sector == sector)
        record_layer(
            con,
            layer_name=f"gem_{sector}",
            source_name="Global Energy Monitor",
            product_version=RELEASES[tracker],
            vintage=RELEASES[tracker],
            download_url="https://globalenergymonitor.org/projects/",
            licence="CC BY 4.0",
            redistributable=True,
            feature_count=count,
            downloaded_at=now,
            notes=(
                "India rows only. Status filtered to built and operated at some point; "
                "operating window carried per asset. D28 and D29."
            ),
        )
    print(f"\nref_gem_assets rows: {len(all_assets)}")
    for row in con.execute(
        "SELECT sector, count(*), count(start_year), count(retired_year) "
        "FROM ref_gem_assets GROUP BY 1 ORDER BY 2 DESC"
    ).fetchall():
        print(
            f"  {row[0]:10s} {row[1]:5d} assets, {row[2]} with start year, "
            f"{row[3]} with retired year"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
