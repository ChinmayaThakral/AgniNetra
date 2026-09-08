"""Ellipsoidal Mercator for the INSAT-3DS L1C Asia grid.

The product carries a `Projection_Information` node giving a Mercator with a
77.25 degree origin, a 17.75 degree standard parallel and a WGS84 ellipsoid, and it
also states the corner coordinates in metres. That makes the projection testable
against the file itself rather than against a library's agreement with another
library.

A spherical Mercator is not good enough here. Tried first, it reproduces the stated
upper left corner to within 2 km in x and 27 km in y, and the grid is 4 km, so the
error is seven pixels of latitude. D78.
"""

from typing import Final

import numpy as np

SEMI_MAJOR: Final[float] = 6378137.0
SEMI_MINOR: Final[float] = 6356752.3142
LON_ORIGIN: Final[float] = 77.25
STANDARD_PARALLEL: Final[float] = 17.75

_E2: Final[float] = 1.0 - (SEMI_MINOR / SEMI_MAJOR) ** 2
_E: Final[float] = float(np.sqrt(_E2))


def _scale_factor() -> float:
    """Scale at the standard parallel, on the ellipsoid rather than the sphere."""
    phi = np.radians(STANDARD_PARALLEL)
    return float(np.cos(phi) / np.sqrt(1.0 - _E2 * np.sin(phi) ** 2))


K0: Final[float] = _scale_factor()


def forward(longitude, latitude):
    """Longitude and latitude in degrees to grid metres. Arrays or scalars."""
    lon = np.radians(np.asarray(longitude, dtype=float))
    lat = np.radians(np.asarray(latitude, dtype=float))
    x = SEMI_MAJOR * K0 * (lon - np.radians(LON_ORIGIN))
    sin_lat = np.sin(lat)
    isometric = np.log(
        np.tan(np.pi / 4.0 + lat / 2.0)
        * ((1.0 - _E * sin_lat) / (1.0 + _E * sin_lat)) ** (_E / 2.0)
    )
    return x, SEMI_MAJOR * K0 * isometric


def inverse(x, y, tolerance: float = 1e-12, max_iterations: int = 40):
    """Grid metres to longitude and latitude in degrees.

    The latitude has no closed form on the ellipsoid and is solved by the standard
    fixed point iteration, which converges in a handful of steps at these
    latitudes. Raises RuntimeError rather than returning a half converged value,
    because a silently wrong latitude is the failure this module exists to avoid.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    lon = np.degrees(x / (SEMI_MAJOR * K0) + np.radians(LON_ORIGIN))

    t = np.exp(-y / (SEMI_MAJOR * K0))
    phi = np.pi / 2.0 - 2.0 * np.arctan(t)
    for _ in range(max_iterations):
        sin_phi = np.sin(phi)
        updated = np.pi / 2.0 - 2.0 * np.arctan(
            t * ((1.0 - _E * sin_phi) / (1.0 + _E * sin_phi)) ** (_E / 2.0)
        )
        if np.max(np.abs(updated - phi)) < tolerance:
            phi = updated
            break
        phi = updated
    else:
        raise RuntimeError(
            f"inverse latitude did not converge in {max_iterations} iterations. "
            "A half converged latitude is worse than a failure."
        )
    return lon, np.degrees(phi)
