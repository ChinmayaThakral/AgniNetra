"""GEM status filtering and the operating window guard."""

from datetime import date

import pytest

from ml.reference.gem import (
    DROPPED_STATUSES,
    KEPT_STATUSES,
    Asset,
    AssetWindowError,
    UnknownStatusError,
    assert_asset_valid_for,
    normalise_status,
    parse_coordinates,
    parse_year,
    status_is_kept,
)


def asset(start: int | None, retired: int | None) -> Asset:
    return Asset("power", "t.xlsx", "X", 24.1, 82.7, "operating", start, retired, None, None)


class TestStatusFiltering:
    def test_kept_and_dropped_do_not_overlap(self) -> None:
        assert KEPT_STATUSES.isdisjoint(DROPPED_STATUSES)

    def test_paper_only_statuses_are_dropped(self) -> None:
        for status in ("cancelled", "announced", "pre-construction", "proposed", "shelved"):
            assert status_is_kept(status) is False, status

    def test_built_statuses_are_kept(self) -> None:
        for status in ("operating", "retired", "mothballed"):
            assert status_is_kept(status) is True, status

    def test_construction_is_dropped(self) -> None:
        """Under construction emits no process heat and its start year is future."""
        assert status_is_kept("construction") is False

    def test_inferred_suffix_is_collapsed(self) -> None:
        assert normalise_status("shelved - inferred 2 y") == "shelved"
        assert status_is_kept("cancelled - inferred 4 y") is False

    def test_an_unfamiliar_status_raises_rather_than_falling_through(self) -> None:
        with pytest.raises(UnknownStatusError, match="neither the kept nor the dropped"):
            status_is_kept("partially decommissioned")


class TestYearParsing:
    def test_handles_the_shapes_gem_actually_uses(self) -> None:
        from datetime import datetime

        assert parse_year(datetime(2003, 5, 1)) == 2003
        assert parse_year(1995.0) == 1995
        assert parse_year("unknown") is None
        assert parse_year("") is None
        assert parse_year(None) is None

    def test_implausible_years_are_rejected(self) -> None:
        assert parse_year(12) is None
        assert parse_year(3200) is None


class TestCoordinateParsing:
    def test_separate_columns(self) -> None:
        row = (24.1, 82.7)
        assert parse_coordinates(row, {"latitude": 0, "longitude": 1}) == (24.1, 82.7)

    def test_combined_field(self) -> None:
        row = ("24.1, 82.7",)
        assert parse_coordinates(row, {"coordinates": 0}) == (24.1, 82.7)

    def test_malformed_combined_field_is_none_not_a_guess(self) -> None:
        assert parse_coordinates(("not a coordinate",), {"coordinates": 0}) is None


class TestOperatingWindow:
    def test_inside_the_window_is_valid(self) -> None:
        assert asset(2010, 2030).operating_in(date(2024, 10, 15)) is True

    def test_before_the_start_year_is_not(self) -> None:
        assert asset(2025, None).operating_in(date(2024, 10, 15)) is False

    def test_after_retirement_is_not(self) -> None:
        assert asset(2000, 2024).operating_in(date(2026, 7, 1)) is False

    def test_retired_plant_is_still_valid_for_an_earlier_detection(self) -> None:
        """The case a static join gets wrong in the other direction."""
        assert asset(2000, 2024).operating_in(date(2023, 11, 1)) is True

    def test_unknown_years_are_permissive_and_that_is_deliberate(self) -> None:
        assert asset(None, None).operating_in(date(2023, 11, 1)) is True


class TestWindowGuard:
    def test_guard_raises_before_the_start_year(self) -> None:
        with pytest.raises(AssetWindowError, match="did not exist yet"):
            assert_asset_valid_for(2025, None, date(2024, 10, 15))

    def test_guard_raises_after_retirement(self) -> None:
        with pytest.raises(AssetWindowError, match="already shut"):
            assert_asset_valid_for(2000, 2024, date(2026, 7, 1))

    def test_guard_passes_inside_the_window(self) -> None:
        assert_asset_valid_for(2000, 2030, date(2024, 10, 15))

    def test_guard_passes_when_years_are_unknown(self) -> None:
        assert_asset_valid_for(None, None, date(2024, 10, 15))
