"""Provenance for every reference layer.

The dataset card in phase 3 is generated from this table, so a layer without a
provenance row is a layer that cannot ship. The pattern matches ingest_runs.
"""

from datetime import UTC, datetime
from typing import Final

import duckdb

REFERENCE_LAYERS_DDL: Final[str] = """
CREATE TABLE IF NOT EXISTS reference_layers (
    layer_name       VARCHAR PRIMARY KEY,
    source_name      VARCHAR NOT NULL,
    product_version  VARCHAR,
    vintage          VARCHAR NOT NULL,
    download_url     VARCHAR NOT NULL,
    downloaded_at    TIMESTAMPTZ NOT NULL,
    licence          VARCHAR NOT NULL,
    redistributable  BOOLEAN NOT NULL,
    feature_count    INTEGER NOT NULL,
    notes            VARCHAR
);
"""


def create_provenance(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(REFERENCE_LAYERS_DDL)


def record_layer(
    con: duckdb.DuckDBPyConnection,
    layer_name: str,
    source_name: str,
    vintage: str,
    download_url: str,
    licence: str,
    redistributable: bool,
    feature_count: int,
    product_version: str | None = None,
    downloaded_at: datetime | None = None,
    notes: str | None = None,
) -> None:
    """Upsert one provenance row.

    redistributable records whether the licence permits shipping the layer inside
    BharatThermal-1. A layer may be usable for labelling and still not shippable,
    and that distinction is tracked from the first load rather than untangled in
    phase 3.
    """
    con.execute("DELETE FROM reference_layers WHERE layer_name = ?", [layer_name])
    con.execute(
        "INSERT INTO reference_layers (layer_name, source_name, product_version, vintage, "
        "download_url, downloaded_at, licence, redistributable, feature_count, notes) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            layer_name,
            source_name,
            product_version,
            vintage,
            download_url,
            downloaded_at or datetime.now(UTC),
            licence,
            redistributable,
            feature_count,
            notes,
        ],
    )
