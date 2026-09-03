"""End to end phase 1a tests. Every one runs with no network access.

The transport is a stub that returns fixture text, so the chunked loop, the
backoff, the parser, the identifier and the loader are all exercised without a
map key and without a request leaving the machine.
"""

from datetime import date

import duckdb
import pytest

from ml.ingest.firms import (
    FirmsClient,
    FirmsRequestError,
    MissingMapKeyError,
    Response,
    day_chunks,
)
from ml.ingest.load import FixtureRowRefusedError, insert_detections
from ml.ingest.parse import FIXTURE_MARKER, parse_csv
from ml.ingest.schema import create_schema
from ml.paths import ROOT

FIXTURE_DIR = ROOT / "tests" / "fixtures"


def read_fixture(name: str) -> str:
    return (FIXTURE_DIR / name).read_text()


class StubTransport:
    """Returns a queued sequence of responses and records the URLs requested."""

    def __init__(self, responses: list[Response]) -> None:
        self._responses = list(responses)
        self.urls: list[str] = []

    def get(self, url: str) -> Response:
        self.urls.append(url)
        if len(self._responses) > 1:
            return self._responses.pop(0)
        return self._responses[0]


@pytest.fixture
def con() -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect()
    create_schema(connection)
    return connection


class TestParsing:
    def test_viirs_fixture_parses_and_bbox_filters(self) -> None:
        rows = parse_csv(read_fixture("SYNTHETIC_viirs_snpp.csv"), "VIIRS_SNPP_NRT")
        # The fourth fixture row is London, outside the India bounding box.
        assert len(rows) == 3
        assert all(68.0 <= r.longitude <= 97.5 for r in rows)

    def test_modis_fixture_parses_with_its_own_columns(self) -> None:
        rows = parse_csv(read_fixture("SYNTHETIC_modis.csv"), "MODIS_SP")
        assert len(rows) == 3
        assert rows[0].brightness is not None
        assert rows[0].bright_ti4 is None
        assert rows[0].country_id == "IND"

    def test_ist_boundary_row_lands_on_the_next_day(self) -> None:
        rows = parse_csv(read_fixture("SYNTHETIC_viirs_snpp.csv"), "VIIRS_SNPP_NRT")
        boundary = next(r for r in rows if r.acq_ts_utc.strftime("%H%M") == "2000")
        assert boundary.acq_ts_utc.strftime("%Y-%m-%d") == "2026-01-15"
        assert boundary.acq_date_ist == "2026-01-16"
        assert boundary.acq_hour_ist == 1

    def test_confidence_normalises_across_families(self) -> None:
        viirs = parse_csv(read_fixture("SYNTHETIC_viirs_snpp.csv"), "VIIRS_SNPP_NRT")
        modis = parse_csv(read_fixture("SYNTHETIC_modis.csv"), "MODIS_SP")
        assert {r.confidence_band for r in viirs} == {"nominal", "high", "low"}
        assert {r.confidence_band for r in modis} == {"high", "nominal", "low"}
        assert all(r.confidence_raw for r in viirs + modis)

    def test_missing_documented_column_is_refused(self) -> None:
        text = "latitude,longitude\n23.1,80.2\n"
        with pytest.raises(ValueError, match="missing documented columns"):
            parse_csv(text, "VIIRS_SNPP_NRT")


class TestIdempotency:
    def test_ingesting_the_same_fixture_twice_leaves_the_count_unchanged(
        self, con: duckdb.DuckDBPyConnection
    ) -> None:
        rows = parse_csv(read_fixture("SYNTHETIC_viirs_snpp.csv"), "VIIRS_SNPP_NRT")

        first = insert_detections(con, rows, "run-1", allow_fixture_rows=True)
        count_after_first = con.execute("SELECT count(*) FROM detections").fetchone()[0]

        second = insert_detections(con, rows, "run-2", allow_fixture_rows=True)
        count_after_second = con.execute("SELECT count(*) FROM detections").fetchone()[0]

        assert first == 3
        assert second == 0
        assert count_after_first == count_after_second == 3

    def test_overlapping_windows_do_not_duplicate(self, con: duckdb.DuckDBPyConnection) -> None:
        rows = parse_csv(read_fixture("SYNTHETIC_viirs_snpp.csv"), "VIIRS_SNPP_NRT")
        insert_detections(con, rows, "run-1", allow_fixture_rows=True)
        insert_detections(con, rows[:2], "run-2", allow_fixture_rows=True)
        assert con.execute("SELECT count(*) FROM detections").fetchone()[0] == 3


class TestFixtureGuard:
    def test_real_run_refuses_fixture_rows(self, con: duckdb.DuckDBPyConnection) -> None:
        rows = parse_csv(read_fixture("SYNTHETIC_viirs_snpp.csv"), "VIIRS_SNPP_NRT")
        assert all(r.version == FIXTURE_MARKER for r in rows)
        with pytest.raises(FixtureRowRefusedError, match=FIXTURE_MARKER):
            insert_detections(con, rows, "run-real")
        assert con.execute("SELECT count(*) FROM detections").fetchone()[0] == 0


class TestClient:
    def test_missing_key_raises_with_the_request_url(self) -> None:
        with pytest.raises(MissingMapKeyError, match="map_key"):
            FirmsClient("", StubTransport([Response(200, "")]))

    def test_chunked_backfill_issues_one_request_per_chunk(self) -> None:
        transport = StubTransport([Response(200, read_fixture("SYNTHETIC_viirs_snpp.csv"))])
        client = FirmsClient("test-key", transport, sleep=lambda _: None)

        chunks = day_chunks(date(2026, 1, 1), date(2026, 3, 31))
        for chunk_start, span in chunks:
            client.area_csv("VIIRS_SNPP_NRT", "68,6.5,97.5,37.5", chunk_start, span)

        assert len(chunks) == 18
        assert client.request_count == 18
        assert len(transport.urls) == 18

    def test_day_range_above_the_cap_is_refused(self) -> None:
        client = FirmsClient("test-key", StubTransport([Response(200, "")]))
        with pytest.raises(ValueError, match="exceeds the documented cap"):
            client.area_csv("VIIRS_SNPP_NRT", "68,6.5,97.5,37.5", date(2026, 1, 1), 10)

    def test_retries_then_succeeds(self) -> None:
        transport = StubTransport(
            [
                Response(429, "rate limited"),
                Response(503, "unavailable"),
                Response(200, read_fixture("SYNTHETIC_modis.csv")),
            ]
        )
        slept: list[float] = []
        client = FirmsClient("test-key", transport, sleep=slept.append)
        text = client.area_csv("MODIS_SP", "68,6.5,97.5,37.5", date(2026, 1, 1), 5)

        assert "country_id" in text
        assert client.request_count == 3
        assert slept == [2.0, 4.0]

    def test_non_retryable_status_fails_immediately(self) -> None:
        transport = StubTransport([Response(401, "invalid key")])
        client = FirmsClient("test-key", transport, sleep=lambda _: None)
        with pytest.raises(FirmsRequestError, match="401"):
            client.area_csv("MODIS_SP", "68,6.5,97.5,37.5", date(2026, 1, 1), 5)
        assert client.request_count == 1

    def test_map_key_is_redacted_from_error_text(self) -> None:
        transport = StubTransport([Response(401, "nope")])
        client = FirmsClient("super-secret-key", transport, sleep=lambda _: None)
        with pytest.raises(FirmsRequestError) as caught:
            client.area_csv("MODIS_SP", "68,6.5,97.5,37.5", date(2026, 1, 1), 5)
        assert "super-secret-key" not in str(caught.value)
        assert "MAP_KEY_REDACTED" in str(caught.value)
