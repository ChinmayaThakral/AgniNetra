"""The solar zenith angle must agree with facts about the sun that do not depend on
this module to be true.

Nothing in this file is fitted to make the assertions pass. Each reference value is
a fact from elementary astronomy or geography, stated independently of the Spencer
1971 formula that solar.py implements, with its source named at the point of use.
"""

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from ml.fusion.solar import solar_zenith_angle_deg

# The current mean obliquity of the ecliptic, about 23 degrees 26 minutes, is why
# the sun's declination swings between plus and minus this value over the year and
# why the tropics sit where they do. Standard astronomical constant, not derived
# from this module.
OBLIQUITY_DEG = 23.44


def _min_zenith_over_the_day(lat: float, lon: float, day_utc: datetime) -> float:
    """The smallest zenith angle reached across one UTC day, found by a fine scan.

    Scanning rather than computing the exact minute of local solar noon avoids
    needing the equation of time from an outside source: the scan finds the true
    minimum the module itself predicts, and the assertion is only that the minimum
    is small, which the reference fact requires regardless of exactly when it
    occurs.
    """
    return min(
        float(
            solar_zenith_angle_deg(
                latitude=lat, longitude=lon, when_utc=day_utc + timedelta(minutes=m)
            )
        )
        for m in range(0, 24 * 60, 1)
    )


def test_declination_reaches_the_obliquity_at_the_june_solstice() -> None:
    """At latitude 90 the hour angle cannot matter: cosine of 90 degrees is zero, so
    the zenith angle at the pole is exactly 90 minus the declination regardless of
    longitude or clock time. At the June solstice the declination equals the
    obliquity of the ecliptic by definition of the solstice, so the pole's zenith
    angle should sit near 90 minus 23.44, independent of hour angle entirely.
    """
    zenith = solar_zenith_angle_deg(
        latitude=90.0, longitude=0.0, when_utc=datetime(2024, 6, 21, 0, 0, tzinfo=UTC)
    )
    assert float(zenith) == pytest.approx(90.0 - OBLIQUITY_DEG, abs=0.1)


def test_declination_reaches_the_obliquity_at_the_december_solstice() -> None:
    zenith = solar_zenith_angle_deg(
        latitude=90.0, longitude=0.0, when_utc=datetime(2024, 12, 21, 0, 0, tzinfo=UTC)
    )
    assert float(zenith) == pytest.approx(90.0 + OBLIQUITY_DEG, abs=0.1)


def test_the_midnight_sun_is_visible_at_the_north_pole_in_june() -> None:
    """Around the June solstice the sun never sets at the North Pole, the midnight
    sun, an elementary fact of polar geography independent of this module."""
    worst = max(
        float(
            solar_zenith_angle_deg(
                latitude=90.0, longitude=0.0, when_utc=datetime(2024, 6, 20, hour, 0, tzinfo=UTC)
            )
        )
        for hour in range(24)
    )
    assert worst < 90.0, f"the sun would set at the pole in June, zenith reached {worst}"


def test_polar_night_covers_the_south_pole_in_june() -> None:
    """The Southern Hemisphere counterpart: polar night, the sun never rises."""
    best = min(
        float(
            solar_zenith_angle_deg(
                latitude=-90.0, longitude=0.0, when_utc=datetime(2024, 6, 20, hour, 0, tzinfo=UTC)
            )
        )
        for hour in range(24)
    )
    assert best > 90.0, f"the sun would rise at the south pole in June, zenith reached {best}"


def test_the_sun_stands_overhead_at_the_tropic_of_cancer_on_the_june_solstice() -> None:
    """The Tropic of Cancer, 23.44 N, is defined as the northernmost latitude where
    the sun can appear directly overhead, which happens at local solar noon on the
    June solstice. This is what the line of latitude means, not a measurement.
    """
    minimum = _min_zenith_over_the_day(OBLIQUITY_DEG, 77.0, datetime(2024, 6, 20, tzinfo=UTC))
    assert minimum < 0.5, f"expected the sun overhead, minimum zenith was {minimum}"


def test_the_sun_stands_overhead_at_the_equator_on_the_september_equinox() -> None:
    """By definition of an equinox the subsolar point sits on the equator. The 2024
    September equinox fell on September 22 (published equinox date)."""
    minimum = _min_zenith_over_the_day(0.0, 77.0, datetime(2024, 9, 22, tzinfo=UTC))
    assert minimum < 0.5, f"expected the sun overhead, minimum zenith was {minimum}"


def test_day_and_night_are_equal_length_at_the_equator_on_the_equinox() -> None:
    """Equinox means equal night: at any latitude the sun is above the horizon for
    close to half of an equinox day. Checked at the equator over the 2024
    September equinox with a five minute scan.
    """
    start = datetime(2024, 9, 22, tzinfo=UTC)
    samples = [
        float(
            solar_zenith_angle_deg(
                latitude=0.0, longitude=77.0, when_utc=start + timedelta(minutes=m)
            )
        )
        for m in range(0, 24 * 60, 5)
    ]
    daylight_fraction = sum(1 for z in samples if z < 90.0) / len(samples)
    assert daylight_fraction == pytest.approx(0.5, abs=0.05)


def test_arrays_broadcast_and_keep_their_shape() -> None:
    lon, lat = np.meshgrid(np.linspace(68.0, 97.0, 4), np.linspace(8.0, 35.0, 5))
    zenith = solar_zenith_angle_deg(
        latitude=lat, longitude=lon, when_utc=datetime(2024, 11, 1, 6, 30, tzinfo=UTC)
    )
    assert zenith.shape == lat.shape
    assert np.all(zenith >= 0.0) and np.all(zenith <= 180.0)


def test_kerala_at_midday_faces_the_sun_more_squarely_than_punjab_at_dusk() -> None:
    """Not a reference value, the property this module exists to expose: on 1
    November 2024 a tropical point at 11:30 IST sits far closer to the sun than a
    Punjab point at 16:30 IST, which is the separation the detector's day and
    night thresholds are built on.
    """
    kerala_at_1130_ist = solar_zenith_angle_deg(
        latitude=15.0, longitude=78.0, when_utc=datetime(2024, 11, 1, 6, 0, tzinfo=UTC)
    )
    punjab_at_1630_ist = solar_zenith_angle_deg(
        latitude=30.0, longitude=75.5, when_utc=datetime(2024, 11, 1, 11, 0, tzinfo=UTC)
    )
    assert float(kerala_at_1130_ist) < 45.0
    assert float(punjab_at_1630_ist) > 60.0
    assert float(kerala_at_1130_ist) < float(punjab_at_1630_ist)
