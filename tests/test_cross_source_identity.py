"""The same physical detection arriving from two sources must collapse to one row.

VIIRS_SNPP_SP and VIIRS_SNPP_NRT are the same instrument at different processing
tiers. If the detection identifier included the source or the tier, both rows would
survive and idempotency would fail across sources while still passing the single
source test in test_ingest_pipeline.py.

The tiers happen to partition the calendar rather than overlap, measured from the
availability endpoint on 2026-09-04, so this cannot bite today. It would bite the
day FIRMS changes that partitioning, or the day someone backfills an overlapping
window from both tiers.
"""

import duckdb
import pytest

from ml.ingest.load import insert_detections
from ml.ingest.parse import parse_csv
from ml.ingest.plan import Segment, assert_no_double_count
from ml.ingest.schema import create_schema
from ml.paths import ROOT

FIXTURE = ROOT / "tests" / "fixtures" / "SYNTHETIC_viirs_snpp.csv"


@pytest.fixture
def con() -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect()
    create_schema(connection)
    return connection


def test_identifier_ignores_the_processing_tier() -> None:
    text = FIXTURE.read_text()
    sp = parse_csv(text, "VIIRS_SNPP_SP")
    nrt = parse_csv(text, "VIIRS_SNPP_NRT")

    assert [d.source for d in sp] != [d.source for d in nrt]
    assert [d.detection_id for d in sp] == [d.detection_id for d in nrt]


def test_same_detection_from_two_sources_inserts_once(
    con: duckdb.DuckDBPyConnection,
) -> None:
    text = FIXTURE.read_text()
    sp = parse_csv(text, "VIIRS_SNPP_SP")
    nrt = parse_csv(text, "VIIRS_SNPP_NRT")

    first = insert_detections(con, sp, "run-sp", allow_fixture_rows=True)
    second = insert_detections(con, nrt, "run-nrt", allow_fixture_rows=True)
    total = con.execute("SELECT count(*) FROM detections").fetchone()[0]

    assert first == 3
    assert second == 0, "the NRT copy created duplicate rows"
    assert total == 3


def test_the_first_source_wins_and_is_recorded(con: duckdb.DuckDBPyConnection) -> None:
    """INSERT OR IGNORE keeps the first row, so provenance shows which tier won."""
    text = FIXTURE.read_text()
    insert_detections(con, parse_csv(text, "VIIRS_SNPP_SP"), "run-sp", allow_fixture_rows=True)
    insert_detections(con, parse_csv(text, "VIIRS_SNPP_NRT"), "run-nrt", allow_fixture_rows=True)
    sources = {r[0] for r in con.execute("SELECT DISTINCT source FROM detections").fetchall()}
    assert sources == {"VIIRS_SNPP_SP"}


def test_a_different_satellite_is_a_different_detection(
    con: duckdb.DuckDBPyConnection,
) -> None:
    """Terra and Aqua seeing the same fire are two detections, not one."""
    text = FIXTURE.read_text()
    snpp = parse_csv(text, "VIIRS_SNPP_NRT")
    noaa20 = parse_csv(text.replace(",N,VIIRS,", ",N20,VIIRS,"), "VIIRS_NOAA20_NRT")

    assert {d.detection_id for d in snpp}.isdisjoint({d.detection_id for d in noaa20})
    insert_detections(con, snpp, "run-a", allow_fixture_rows=True)
    insert_detections(con, noaa20, "run-b", allow_fixture_rows=True)
    assert con.execute("SELECT count(*) FROM detections").fetchone()[0] == 6


class TestPlanOverlap:
    def test_overlapping_segments_are_refused(self) -> None:
        from datetime import date

        overlapping = [
            Segment("viirs_snpp", "VIIRS_SNPP_SP", date(2026, 4, 1), date(2026, 4, 30)),
            Segment("viirs_snpp", "VIIRS_SNPP_NRT", date(2026, 4, 28), date(2026, 5, 30)),
        ]
        with pytest.raises(ValueError, match="paid for twice"):
            assert_no_double_count(overlapping)

    def test_adjacent_segments_are_allowed(self) -> None:
        from datetime import date

        adjacent = [
            Segment("viirs_snpp", "VIIRS_SNPP_SP", date(2026, 4, 1), date(2026, 4, 27)),
            Segment("viirs_snpp", "VIIRS_SNPP_NRT", date(2026, 4, 28), date(2026, 5, 30)),
        ]
        assert_no_double_count(adjacent)
