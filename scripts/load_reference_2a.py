#!/usr/bin/env python3
"""Load the phase 2a reference layers into DuckDB with provenance.

Three layers, none of which needs a registration: the EOG global gas flare
catalogue, OpenStreetMap industrial features from the Geofabrik India extract, and
ESA WorldCover land cover.

WorldCover is not bulk loaded here. There are no detections to sample yet because
phase 1b is blocked on the map key, and the full India tile set is 7.50 GB. The
sampler and the tile resolver are built and tested; the bulk pull happens when
there are points to sample. Recorded as D13.

Usage:
    uv run python scripts/load_reference_2a.py
"""

import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import duckdb

from ml.paths import DUCKDB_PATH, ROOT, ensure_dir
from ml.reference.flares import load_year
from ml.reference.geo import install_geo
from ml.reference.provenance import create_provenance, record_layer

RAW = ROOT / "data" / "raw"
REFERENCE = ROOT / "data" / "reference"

EOG_YEARS: dict[int, str] = {
    2019: "VIIRS_Global_flaring_d.7_slope_0.029353_2019_web_v20201114.xlsx",
    2020: "VIIRS_Global_flaring_d.7_slope_0.029353_2020_web_v1.xlsx",
    2021: "VIIRS_Global_flaring_d.7_slope_0.029353_2021_web.xlsx",
    2022: "VIIRS_Global_flaring_d.7_slope_0.029353_2022_v20230526_web.xlsx",
    2023: "VIIRS_Global_flaring_d.7_slope_0.029353_2023_v20230614_web_IDmatch.xlsx",
    2024: "VIIRS_Global_flaring_d.7_slope_0.029353_2024_v20240730_web_IDmatch.xlsx",
}

OSM_VINTAGE = "2026-09-02T20:20:51Z"
OSM_SEQUENCE = "4895"

FLARES_DDL = """
CREATE TABLE IF NOT EXISTS ref_flares (
    catalogue_year  INTEGER NOT NULL,
    sheet           VARCHAR NOT NULL,
    country         VARCHAR,
    iso             VARCHAR NOT NULL,
    flare_id        VARCHAR,
    latitude        DOUBLE NOT NULL,
    longitude       DOUBLE NOT NULL,
    bcm             DOUBLE,
    avg_temp_k      DOUBLE,
    ellipticity     DOUBLE,
    detection_freq  DOUBLE,
    clear_obs       INTEGER,
    flare_type      VARCHAR
);
"""

OSM_DDL = """
CREATE TABLE IF NOT EXISTS ref_osm_industrial (
    osm_type   VARCHAR NOT NULL,
    osm_id     BIGINT NOT NULL,
    tag_key    VARCHAR NOT NULL,
    tag_value  VARCHAR NOT NULL,
    name       VARCHAR,
    operator   VARCHAR,
    longitude  DOUBLE NOT NULL,
    latitude   DOUBLE NOT NULL,
    PRIMARY KEY (osm_type, osm_id)
);
"""

ADMIN_DDL = """
CREATE TABLE IF NOT EXISTS ref_osm_admin (
    osm_id       BIGINT NOT NULL,
    admin_level  VARCHAR NOT NULL,
    name         VARCHAR,
    name_en      VARCHAR,
    geom         GEOMETRY NOT NULL,
    PRIMARY KEY (osm_id, admin_level)
);
"""


def _as_float(value: object) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def load_flares(con: duckdb.DuckDBPyConnection) -> int:
    con.execute(FLARES_DDL)
    con.execute("DELETE FROM ref_flares")
    total = 0
    for year, filename in EOG_YEARS.items():
        path = RAW / "eog" / filename
        if not path.is_file():
            print(f"  missing {path.name}, skipping {year}")
            continue
        rows = load_year(path, year)
        con.executemany(
            "INSERT INTO ref_flares VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    r["catalogue_year"],
                    r["sheet"],
                    r["country"],
                    r["iso"],
                    None if r["flare_id"] is None else str(r["flare_id"]),
                    r["latitude"],
                    r["longitude"],
                    _as_float(r["bcm"]),
                    _as_float(r["avg_temp_k"]),
                    _as_float(r["ellipticity"]),
                    _as_float(r["detection_freq"]),
                    None if _as_float(r["clear_obs"]) is None else int(_as_float(r["clear_obs"])),
                    r["flare_type"],
                )
                for r in rows
            ],
        )
        print(f"  {year}: {len(rows)} India flares")
        total += len(rows)
    return total


def load_osm_industrial(con: duckdb.DuckDBPyConnection) -> int:
    path = REFERENCE / "osm_industrial.csv"
    if not path.is_file():
        raise FileNotFoundError(f"run scripts/filter_osm.py first, missing {path}")
    con.execute(OSM_DDL)
    con.execute("DELETE FROM ref_osm_industrial")
    con.execute(
        "INSERT INTO ref_osm_industrial "
        "SELECT osm_type, osm_id, tag_key, tag_value, name, operator, longitude, latitude "
        f"FROM read_csv('{path}', header=true, AUTO_DETECT=true)"
    )
    return int(con.execute("SELECT count(*) FROM ref_osm_industrial").fetchone()[0])


def load_osm_admin(con: duckdb.DuckDBPyConnection) -> int:
    path = REFERENCE / "osm_admin.csv"
    if not path.is_file():
        print(f"  {path.name} not present yet, skipping admin boundaries")
        return 0
    con.execute(ADMIN_DDL)
    con.execute("DELETE FROM ref_osm_admin")
    # Read through DuckDB rather than the csv module: a state multipolygon in WKT
    # exceeds the csv module's 131072 character field limit, and it also exceeds
    # DuckDB's default 2 MB line limit, hence max_line_size.
    con.execute(
        "INSERT OR IGNORE INTO ref_osm_admin "
        "SELECT osm_id, admin_level, name, name_en, ST_GeomFromText(wkt) "
        f"FROM read_csv('{path}', header=true, "
        "columns={'osm_id':'BIGINT','admin_level':'VARCHAR','name':'VARCHAR',"
        "'name_en':'VARCHAR','wkt':'VARCHAR'}, max_line_size=67108864)"
    )
    return int(con.execute("SELECT count(*) FROM ref_osm_admin").fetchone()[0])


def main() -> int:
    ensure_dir(DUCKDB_PATH.parent)
    con = duckdb.connect(str(DUCKDB_PATH))
    install_geo(con)
    create_provenance(con)
    now = datetime.now(UTC)

    print("EOG global gas flare catalogue")
    flare_count = load_flares(con)
    record_layer(
        con,
        layer_name="eog_flares",
        source_name="EOG VIIRS global gas flaring, Colorado School of Mines",
        product_version="d.7 slope 0.029353",
        vintage="2019 to 2024 annual catalogues",
        download_url="https://eogdata.mines.edu/products/vnf/global_gas_flare.html",
        licence="EOG public data, attribution required, redistribution not confirmed",
        redistributable=False,
        feature_count=flare_count,
        downloaded_at=now,
        notes="Filtered to ISO code IND on the catalogue's own country column.",
    )

    print("OSM industrial features")
    osm_count = load_osm_industrial(con)
    record_layer(
        con,
        layer_name="osm_industrial",
        source_name="OpenStreetMap via Geofabrik India extract",
        product_version=f"geofabrik sequence {OSM_SEQUENCE}",
        vintage=OSM_VINTAGE,
        download_url="https://download.geofabrik.de/asia/india-latest.osm.pbf",
        licence="ODbL 1.0",
        redistributable=True,
        feature_count=osm_count,
        downloaded_at=now,
        notes="landuse=industrial, man_made=works, man_made=flare, power=plant. "
        "Ways reduced to node centroid.",
    )
    print(f"  {osm_count} features")

    print("OSM administrative boundaries")
    admin_count = load_osm_admin(con)
    if admin_count:
        record_layer(
            con,
            layer_name="osm_admin",
            source_name="OpenStreetMap via Geofabrik India extract",
            product_version=f"geofabrik sequence {OSM_SEQUENCE}",
            vintage=OSM_VINTAGE,
            download_url="https://download.geofabrik.de/asia/india-latest.osm.pbf",
            licence="ODbL 1.0",
            redistributable=True,
            feature_count=admin_count,
            downloaded_at=now,
            notes="admin_level 4 states and union territories, 6 districts. "
            "Same snapshot as the industrial features, deliberately.",
        )
        print(f"  {admin_count} areas")

    record_layer(
        con,
        layer_name="esa_worldcover",
        source_name="ESA WorldCover 10 m",
        product_version="v200",
        vintage="2021",
        download_url="https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map",
        licence="CC BY 4.0",
        redistributable=True,
        feature_count=1,
        downloaded_at=now,
        notes="Sampler built and tested against tile N24E081. Bulk pull deferred: "
        "102 tiles over the India bbox totalling 7.50 GB, and there are no "
        "detections to sample until phase 1b. See D13.",
    )

    print("\nprovenance:")
    for row in con.execute(
        "SELECT layer_name, vintage, licence, redistributable, feature_count "
        "FROM reference_layers ORDER BY layer_name"
    ).fetchall():
        print(f"  {row[0]}: {row[4]} features, {row[1]}, {row[2]}, redistributable={row[3]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
