"""Recurrence features, with every derived quantity computed a second way.

The second computation is the point. Six silent bugs in this project were caught
by a number disagreeing with an independent calculation, not by a test that
anticipated the bug. These tests recompute each feature by a different route and
assert agreement.
"""

from datetime import UTC, datetime, timedelta

import pytest

from ml.features.recurrence import (
    CELL_DEGREES,
    Event,
    LeakageError,
    cell_key,
    count_in_window,
    frp_variance,
    mean_inter_arrival_days,
    night_fraction,
    returned_previous_year,
)

NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


def nightly_flare(days: int, frp: float = 10.0) -> list[Event]:
    """A flare: one detection per night for the trailing days, near constant power."""
    return [Event(NOW - timedelta(days=d), frp, True) for d in range(1, days + 1)]


class TestLeakageGuard:
    def test_event_at_the_reference_time_is_refused(self) -> None:
        with pytest.raises(LeakageError, match="at or after"):
            count_in_window([Event(NOW, 5.0, True)], NOW, 90)

    def test_event_after_the_reference_time_is_refused(self) -> None:
        future = [Event(NOW + timedelta(seconds=1), 5.0, True)]
        with pytest.raises(LeakageError, match="at or after"):
            night_fraction(future, NOW)

    def test_naive_reference_time_is_refused(self) -> None:
        with pytest.raises(LeakageError, match="timezone aware"):
            count_in_window([], datetime(2026, 3, 1, 12, 0), 90)

    def test_every_feature_enforces_the_guard(self) -> None:
        leaking = [Event(NOW, 5.0, True)]
        for feature in (
            lambda: count_in_window(leaking, NOW, 90),
            lambda: night_fraction(leaking, NOW),
            lambda: frp_variance(leaking, NOW),
            lambda: mean_inter_arrival_days(leaking, NOW),
            lambda: returned_previous_year(leaking, NOW),
        ):
            with pytest.raises(LeakageError):
                feature()


class TestCountSecondMethod:
    def test_count_matches_an_independent_filter(self) -> None:
        history = nightly_flare(120)
        measured = count_in_window(history, NOW, 90)
        cutoff = NOW - timedelta(days=90)
        independent = len([e for e in history if e.when >= cutoff])
        assert measured == independent
        assert measured == 90


class TestNightFraction:
    def test_all_night_history_gives_one(self) -> None:
        assert night_fraction(nightly_flare(30), NOW) == 1.0

    def test_half_and_half_gives_one_half(self) -> None:
        history = [Event(NOW - timedelta(days=d), 5.0, d % 2 == 0) for d in range(1, 41)]
        measured = night_fraction(history, NOW, 90)
        independent = sum(1 for e in history if e.is_night) / len(history)
        assert measured == pytest.approx(independent)
        assert measured == pytest.approx(0.5)

    def test_empty_window_is_none_not_zero(self) -> None:
        """A location with no history is not a location that never burns at night."""
        old = [Event(NOW - timedelta(days=400), 5.0, True)]
        assert night_fraction(old, NOW, 90) is None


class TestFrpVariance:
    def test_constant_power_has_zero_variance(self) -> None:
        assert frp_variance(nightly_flare(30, frp=12.0), NOW) == pytest.approx(0.0)

    def test_variance_matches_statistics_module(self) -> None:
        import statistics

        history = [Event(NOW - timedelta(days=d), float(d * 3 % 17), True) for d in range(1, 31)]
        measured = frp_variance(history, NOW, 90)
        independent = statistics.pvariance([e.frp for e in history])
        assert measured == pytest.approx(independent)

    def test_single_event_is_none(self) -> None:
        assert frp_variance([Event(NOW - timedelta(days=1), 5.0, True)], NOW) is None


class TestInterArrival:
    def test_nightly_flare_averages_one_day(self) -> None:
        assert mean_inter_arrival_days(nightly_flare(60), NOW) == pytest.approx(1.0)

    def test_mean_of_gaps_is_not_span_over_count(self) -> None:
        """The two differ, and the tests pin which one is intended."""
        history = [
            Event(NOW - timedelta(days=100), 5.0, True),
            Event(NOW - timedelta(days=99), 5.0, True),
            Event(NOW - timedelta(days=1), 5.0, True),
        ]
        measured = mean_inter_arrival_days(history, NOW)
        span_over_count = 99.0 / 3
        assert measured == pytest.approx((1.0 + 98.0) / 2)
        assert measured != pytest.approx(span_over_count)

    def test_single_event_is_none(self) -> None:
        assert mean_inter_arrival_days([Event(NOW - timedelta(days=5), 5.0, True)], NOW) is None


class TestInterAnnualReturn:
    def test_a_year_ago_returns_true(self) -> None:
        history = [Event(NOW - timedelta(days=365), 5.0, True)]
        assert returned_previous_year(history, NOW) is True

    def test_recent_burst_only_returns_false(self) -> None:
        """A wildfire signature: bursty and recent, with no inter annual return."""
        assert returned_previous_year(nightly_flare(20), NOW) is False

    def test_outside_tolerance_returns_false(self) -> None:
        history = [Event(NOW - timedelta(days=365 - 45), 5.0, True)]
        assert returned_previous_year(history, NOW, tolerance_days=30) is False


class TestCellKey:
    def test_points_within_half_a_pixel_share_a_cell(self) -> None:
        assert cell_key(longitude=82.6757, latitude=24.1030) == cell_key(
            longitude=82.6757 + CELL_DEGREES / 4, latitude=24.1030
        )

    def test_points_a_cell_apart_differ(self) -> None:
        assert cell_key(longitude=82.6757, latitude=24.1030) != cell_key(
            longitude=82.6757 + CELL_DEGREES * 1.5, latitude=24.1030
        )

    def test_cell_key_is_stable_across_the_negative_boundary(self) -> None:
        """floor, not int, so cells do not double in width at zero."""
        assert cell_key(longitude=-0.001, latitude=0.0) != cell_key(longitude=0.001, latitude=0.0)
