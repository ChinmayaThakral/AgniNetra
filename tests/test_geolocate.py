"""The Mercator must reproduce the product's own stated corners.

A projection that is close is not close enough. A spherical Mercator lands 27 km
out in latitude on this grid, which is seven pixels at 4 km, and every collocation
downstream would be silently displaced by that much. The file states its corner
coordinates in metres, so this is checkable against the data rather than against
another implementation.
"""

import numpy as np
import pytest

from ml.fusion.geolocate import K0, SEMI_MAJOR, SEMI_MINOR, forward, inverse

# From Projection_Information in 3SIMG_01NOV2024_1130_L1C_ASIA_MER_V01R00.h5.
UPPER_LEFT_LAT_LON = (45.5, 44.5)
UPPER_LEFT_XY = (-3473242.733735, 5401854.420193)


def test_upper_left_corner_matches_the_product() -> None:
    x, y = forward(UPPER_LEFT_LAT_LON[1], UPPER_LEFT_LAT_LON[0])
    assert float(x) == pytest.approx(UPPER_LEFT_XY[0], abs=1.0)
    assert float(y) == pytest.approx(UPPER_LEFT_XY[1], abs=1.0)


def test_a_spherical_mercator_would_not_pass() -> None:
    """Guards the reason this module exists rather than trusting it stays known."""
    phi_s = np.radians(17.75)
    k0_sphere = np.cos(phi_s)
    lat = np.radians(UPPER_LEFT_LAT_LON[0])
    y_sphere = SEMI_MAJOR * k0_sphere * np.log(np.tan(np.pi / 4 + lat / 2))
    error = abs(float(y_sphere) - UPPER_LEFT_XY[1])
    assert error > 10_000, f"the spherical form is only {error:.0f} m out, check the premise"


def test_origin_maps_to_zero_easting() -> None:
    x, _ = forward(77.25, 0.0)
    assert float(x) == pytest.approx(0.0, abs=1e-6)


def test_equator_maps_to_zero_northing() -> None:
    _, y = forward(77.25, 0.0)
    assert float(y) == pytest.approx(0.0, abs=1e-6)


@pytest.mark.parametrize(
    "lon,lat",
    [(68.0, 6.5), (97.5, 37.5), (82.0, 24.0), (77.25, 17.75), (44.5, -10.0)],
)
def test_round_trip_is_exact(lon: float, lat: float) -> None:
    back_lon, back_lat = inverse(*forward(lon, lat))
    assert float(back_lon) == pytest.approx(lon, abs=1e-9)
    assert float(back_lat) == pytest.approx(lat, abs=1e-9)


def test_the_ellipsoid_is_wgs84() -> None:
    assert SEMI_MAJOR == 6378137.0
    assert pytest.approx(6356752.3142) == SEMI_MINOR
    flattening = 1.0 / ((SEMI_MAJOR - SEMI_MINOR) / SEMI_MAJOR)
    assert flattening == pytest.approx(298.257, abs=0.001)


def test_scale_factor_is_the_ellipsoidal_one() -> None:
    """The spherical scale at 17.75 degrees differs in the fourth decimal, which is
    what produces a kilometre scale error over the width of the grid."""
    spherical = float(np.cos(np.radians(17.75)))
    assert pytest.approx(spherical, abs=1e-6) != K0
    assert pytest.approx(spherical, abs=1e-3) == K0


def test_arrays_are_supported() -> None:
    lons = np.array([70.0, 80.0, 90.0])
    lats = np.array([10.0, 20.0, 30.0])
    x, y = forward(lons, lats)
    assert x.shape == lons.shape and y.shape == lats.shape
    assert np.all(np.diff(x) > 0) and np.all(np.diff(y) > 0)
