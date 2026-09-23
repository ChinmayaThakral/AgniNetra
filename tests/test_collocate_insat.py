"""The collocation between polar detections and INSAT granules had no coverage.

The script matched every polar detection five and a half hours out once, because it
stripped the IST offset from a timestamp instead of converting it, and still found a
granule inside the time tolerance, so nothing looked wrong. These tests pin the three
units that decide a match: distance, the conversion to UTC, and the nearest granule
within tolerance. D121.
"""

import importlib.util
import sys
from datetime import UTC, datetime, timedelta, timezone

import numpy as np
import pytest

from ml.paths import ROOT

_spec = importlib.util.spec_from_file_location(
    "collocate_insat", ROOT / "scripts" / "collocate_insat.py"
)
assert _spec is not None and _spec.loader is not None
collocate = importlib.util.module_from_spec(_spec)
sys.modules["collocate_insat"] = collocate
_spec.loader.exec_module(collocate)

IST = timezone(timedelta(hours=5, minutes=30))


def test_one_degree_of_latitude_is_the_mean_earth_arc() -> None:
    """2 pi R over 360 for R = 6371008.8 m, the IUGG mean radius the script uses."""
    distance = collocate._haversine_m(
        lat1=np.array(20.0), lon1=np.array(77.0), lat2=np.array(21.0), lon2=np.array(77.0)
    )
    assert float(distance) == pytest.approx(111195.08, abs=0.05)


def test_distance_is_symmetric_and_zero_on_itself() -> None:
    a = {"lat1": np.array(30.7), "lon1": np.array(76.8)}
    b = {"lat2": np.array(28.6), "lon2": np.array(77.2)}
    forward = collocate._haversine_m(**a, **b)
    backward = collocate._haversine_m(
        lat1=b["lat2"], lon1=b["lon2"], lat2=a["lat1"], lon2=a["lon1"]
    )
    assert float(forward) == pytest.approx(float(backward))
    assert float(collocate._haversine_m(**a, lat2=a["lat1"], lon2=a["lon1"])) == 0.0


def test_an_ist_timestamp_converts_to_the_same_instant_in_utc() -> None:
    ist = datetime(2024, 11, 1, 13, 11, tzinfo=IST)
    assert collocate.to_utc(ist) == datetime(2024, 11, 1, 7, 41, tzinfo=UTC)


def test_a_naive_timestamp_is_refused_rather_than_assumed() -> None:
    with pytest.raises(ValueError, match="naive"):
        collocate.to_utc(datetime(2024, 11, 1, 13, 11))


def test_the_match_uses_the_instant_not_the_wall_clock() -> None:
    """The defect this file exists for.

    A detection at 13:11 IST is 07:41 UTC. Of granules at 07:30 and 13:00 UTC, the
    right match is 07:30. Comparing the IST wall clock, 13:11, against UTC times picks
    13:00 instead, eleven minutes away and inside the tolerance, which is why the
    original defect produced plausible matches rather than none.
    """
    granules = np.array(
        [datetime(2024, 11, 1, 7, 30, tzinfo=UTC), datetime(2024, 11, 1, 13, 0, tzinfo=UTC)]
    )
    detection = datetime(2024, 11, 1, 13, 11, tzinfo=IST)
    assert collocate.nearest_granule(detection, granules, timedelta(minutes=15)) == 0


def test_the_tolerance_is_inclusive_at_its_edge_and_exclusive_past_it() -> None:
    granules = np.array([datetime(2024, 11, 1, 7, 30, tzinfo=UTC)])
    at_edge = datetime(2024, 11, 1, 7, 45, tzinfo=UTC)
    past_edge = datetime(2024, 11, 1, 7, 46, tzinfo=UTC)
    assert collocate.nearest_granule(at_edge, granules, timedelta(minutes=15)) == 0
    assert collocate.nearest_granule(past_edge, granules, timedelta(minutes=15)) == -1
