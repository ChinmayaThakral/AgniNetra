"""Unit tests for the phase 1a ingest primitives. No network access."""

from datetime import UTC, datetime

import pytest

from ml.ingest.columns import UNION_COLUMNS, columns_for, family_for
from ml.ingest.confidence import (
    MODIS_HIGH_FLOOR,
    MODIS_NOMINAL_FLOOR,
    normalise_modis,
    normalise_viirs,
)
from ml.ingest.firms import MAX_DAY_RANGE, day_chunks
from ml.ingest.identity import detection_id
from ml.ingest.timeutil import IST, parse_acq_timestamp, to_ist


class TestTimestamps:
    def test_acq_time_is_zero_padded(self) -> None:
        assert parse_acq_timestamp("2026-01-15", 138).hour == 1
        assert parse_acq_timestamp("2026-01-15", 138).minute == 38
        assert parse_acq_timestamp("2026-01-15", 45).hour == 0
        assert parse_acq_timestamp("2026-01-15", 45).minute == 45

    def test_four_digit_time_parses(self) -> None:
        moment = parse_acq_timestamp("2026-01-15", "2000")
        assert (moment.hour, moment.minute) == (20, 0)

    def test_ist_date_differs_from_utc_date_across_the_boundary(self) -> None:
        # 20:00 UTC on the 15th is 01:30 IST on the 16th. This is the case that
        # silently breaks phase 5 if IST is derived once and stored wrongly.
        utc = parse_acq_timestamp("2026-01-15", "2000")
        ist = to_ist(utc)
        assert utc.strftime("%Y-%m-%d") == "2026-01-15"
        assert ist.strftime("%Y-%m-%d") == "2026-01-16"
        assert (ist.hour, ist.minute) == (1, 30)

    def test_evening_ist_burning_window_maps_back_before_midnight_utc(self) -> None:
        # 17:00 IST, the shifted burning peak, is 11:30 UTC on the same day.
        utc = parse_acq_timestamp("2026-11-05", "1130")
        assert to_ist(utc).hour == 17

    def test_naive_datetime_is_refused(self) -> None:
        with pytest.raises(ValueError, match="naive"):
            to_ist(datetime(2026, 1, 15, 20, 0))

    def test_out_of_range_time_is_refused(self) -> None:
        with pytest.raises(ValueError, match="out of range"):
            parse_acq_timestamp("2026-01-15", "2599")


class TestConfidence:
    def test_modis_boundaries(self) -> None:
        assert normalise_modis(0) == "low"
        assert normalise_modis(MODIS_NOMINAL_FLOOR - 1) == "low"
        assert normalise_modis(MODIS_NOMINAL_FLOOR) == "nominal"
        assert normalise_modis(MODIS_HIGH_FLOOR - 1) == "nominal"
        assert normalise_modis(MODIS_HIGH_FLOOR) == "high"
        assert normalise_modis(100) == "high"

    def test_modis_out_of_range_is_refused(self) -> None:
        with pytest.raises(ValueError, match="out of range"):
            normalise_modis(101)
        with pytest.raises(ValueError, match="out of range"):
            normalise_modis(-1)

    def test_viirs_categories(self) -> None:
        assert normalise_viirs("l") == "low"
        assert normalise_viirs("n") == "nominal"
        assert normalise_viirs("h") == "high"
        assert normalise_viirs("H") == "high"

    def test_viirs_unknown_is_refused(self) -> None:
        with pytest.raises(ValueError, match="not one of"):
            normalise_viirs("x")


class TestIdentity:
    def test_same_instant_in_any_offset_gives_one_id(self) -> None:
        moment = datetime(2026, 1, 15, 20, 0, tzinfo=UTC)
        assert detection_id(
            instrument="VIIRS", satellite="N", latitude=23.1, longitude=80.2, acq_utc=moment
        ) == detection_id(
            instrument="VIIRS",
            satellite="N",
            latitude=23.1,
            longitude=80.2,
            acq_utc=moment.astimezone(IST),
        )

    def test_float_noise_below_product_precision_collapses(self) -> None:
        moment = datetime(2026, 1, 15, 20, 0, tzinfo=UTC)
        assert detection_id(
            instrument="VIIRS", satellite="N", latitude=23.1, longitude=80.2, acq_utc=moment
        ) == detection_id(
            instrument="VIIRS",
            satellite="N",
            latitude=23.100000001,
            longitude=80.199999999,
            acq_utc=moment,
        )

    def test_distinct_locations_give_distinct_ids(self) -> None:
        moment = datetime(2026, 1, 15, 20, 0, tzinfo=UTC)
        assert detection_id(
            instrument="VIIRS", satellite="N", latitude=23.1, longitude=80.2, acq_utc=moment
        ) != detection_id(
            instrument="VIIRS", satellite="N", latitude=23.2, longitude=80.2, acq_utc=moment
        )

    def test_naive_datetime_is_refused(self) -> None:
        with pytest.raises(ValueError, match="timezone aware"):
            detection_id(
                instrument="VIIRS",
                satellite="N",
                latitude=23.1,
                longitude=80.2,
                acq_utc=datetime(2026, 1, 15, 20, 0),
            )


class TestColumns:
    def test_families_resolve(self) -> None:
        assert family_for("VIIRS_SNPP_SP") == "viirs"
        assert family_for("MODIS_SP") == "modis"

    def test_unknown_source_is_refused(self) -> None:
        with pytest.raises(ValueError, match="unknown FIRMS source"):
            columns_for("VIIRS_NOAA21_SP")

    def test_union_covers_both_families(self) -> None:
        for column in ("bright_ti4", "bright_ti5", "brightness", "bright_t31", "country_id"):
            assert column in UNION_COLUMNS


class TestDayChunks:
    def test_ninety_days_splits_at_the_documented_cap(self) -> None:
        from datetime import date

        chunks = day_chunks(date(2026, 1, 1), date(2026, 3, 31))
        assert sum(span for _, span in chunks) == 90
        assert all(span <= MAX_DAY_RANGE for _, span in chunks)
        assert len(chunks) == 18

    def test_chunks_do_not_overlap_and_cover_the_window(self) -> None:
        from datetime import date, timedelta

        start, end = date(2026, 1, 1), date(2026, 1, 13)
        covered: list[date] = []
        for chunk_start, span in day_chunks(start, end):
            covered.extend(chunk_start + timedelta(days=i) for i in range(span))
        assert covered == sorted(covered)
        assert len(covered) == len(set(covered))
        assert covered[0] == start and covered[-1] == end

    def test_reversed_window_is_refused(self) -> None:
        from datetime import date

        with pytest.raises(ValueError, match="before window start"):
            day_chunks(date(2026, 3, 31), date(2026, 1, 1))
