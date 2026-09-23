"""Solar zenith angle from latitude, longitude and a UTC timestamp.

The contextual fire test in detect.py cannot tell reflected sunlight on bare
ground from combustion, because both raise the mid wave channel above its local
background. The published remedy conditions the threshold on how high the sun
sits, which needs the solar zenith angle at every pixel: the angle between the
local vertical and the direction to the sun, zero when the sun is directly
overhead and 90 degrees at the horizon.

The formula is the standard truncated Fourier fit from solar engineering, given
in Spencer, J. W., "Fourier series representation of the position of the sun",
Search 2(5), 1971, and reproduced as Iqbal, "An Introduction to Solar Radiation",
1983, table 1.5.1. It states the solar declination and the equation of time as a
few harmonics of the day of year, then combines declination, hour angle and
latitude by the standard spherical relation. Spencer's stated accuracy is about
0.0006 radian, about 2 arcminutes, for the declination and about 35 seconds of
time for the equation of time, both far tighter than this project needs: the
thresholds this feeds only split day from night and do not resolve to the
arcminute. Atmospheric refraction near the horizon, worth about half a degree, is
not applied for the same reason.
"""

import math
from datetime import datetime

import numpy as np


def _day_angle_rad(when_utc: datetime) -> float:
    """Spencer's fractional year angle, radians, from day of year and hour of day."""
    day_of_year = when_utc.timetuple().tm_yday
    hour = when_utc.hour + when_utc.minute / 60.0 + when_utc.second / 3600.0
    return 2.0 * math.pi / 365.0 * (day_of_year - 1 + (hour - 12.0) / 24.0)


def _declination_deg(when_utc: datetime) -> float:
    """Solar declination in degrees, positive north. Spencer 1971."""
    g = _day_angle_rad(when_utc)
    radians = (
        0.006918
        - 0.399912 * math.cos(g)
        + 0.070257 * math.sin(g)
        - 0.006758 * math.cos(2 * g)
        + 0.000907 * math.sin(2 * g)
        - 0.002697 * math.cos(3 * g)
        + 0.00148 * math.sin(3 * g)
    )
    return math.degrees(radians)


def _equation_of_time_minutes(when_utc: datetime) -> float:
    """Apparent solar time minus mean solar time, in minutes. Spencer 1971."""
    g = _day_angle_rad(when_utc)
    return 229.18 * (
        0.000075
        + 0.001868 * math.cos(g)
        - 0.032077 * math.sin(g)
        - 0.014615 * math.cos(2 * g)
        - 0.040849 * math.sin(2 * g)
    )


def solar_zenith_angle_deg(
    *,
    latitude: float | np.ndarray,
    longitude: float | np.ndarray,
    when_utc: datetime,
) -> np.ndarray:
    """Solar zenith angle in degrees: 0 is overhead, 90 is the horizon, above 90 is night.

    latitude and longitude are degrees, positive north and positive east, scalar or
    an array of any matching shape. when_utc is one timestamp shared by every
    point, which matches an INSAT-3DS window where the whole scene is one
    acquisition time, and must already be UTC: the value is used as given and is
    not converted.
    """
    lat = np.radians(np.asarray(latitude, dtype=np.float64))
    lon = np.asarray(longitude, dtype=np.float64)

    declination = math.radians(_declination_deg(when_utc))
    minutes_utc = when_utc.hour * 60.0 + when_utc.minute + when_utc.second / 60.0
    true_solar_time = minutes_utc + _equation_of_time_minutes(when_utc) + 4.0 * lon
    hour_angle = np.radians(true_solar_time / 4.0 - 180.0)

    cos_zenith = np.sin(lat) * math.sin(declination) + np.cos(lat) * math.cos(declination) * np.cos(
        hour_angle
    )
    return np.degrees(np.arccos(np.clip(cos_zenith, -1.0, 1.0)))
