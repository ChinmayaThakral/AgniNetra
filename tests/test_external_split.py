"""The fourth held out group is external and must stay disjoint from the three."""

import pytest

from ml.labels.splits import (
    EXTERNAL_EXTENTS,
    EXTERNAL_GROUP,
    HELD_OUT_GROUPS,
    SplitError,
    assert_external_disjoint_from_states,
    assign_fold,
    in_external_extent,
)


def test_external_group_is_not_a_state_group() -> None:
    assert EXTERNAL_GROUP not in HELD_OUT_GROUPS
    assert_external_disjoint_from_states()


def test_adding_it_as_a_state_group_is_refused() -> None:
    bad = dict(HELD_OUT_GROUPS)
    bad[EXTERNAL_GROUP] = ("Pakistan",)
    with pytest.raises(SplitError, match="must not be a state group"):
        assert_external_disjoint_from_states(bad)


def test_lahore_falls_in_the_pakistan_extent() -> None:
    assert in_external_extent(longitude=74.33, latitude=31.55) == "Pakistan"


def test_colombo_falls_in_the_sri_lanka_extent() -> None:
    assert in_external_extent(longitude=79.86, latitude=6.93) == "Sri Lanka"


def test_a_point_in_no_extent_returns_none() -> None:
    assert in_external_extent(longitude=88.36, latitude=22.57) is None


def test_the_extents_overlap_india_so_containment_alone_proves_nothing() -> None:
    """Amritsar is Indian and sits inside the Pakistan bounding rectangle. The
    external group is defined by having no Indian state, not by these extents."""
    assert in_external_extent(longitude=74.87, latitude=31.63) == "Pakistan"
    assert assign_fold("Punjab") == "group_a"


def test_every_extent_is_a_sane_rectangle() -> None:
    for country, (west, south, east, north) in EXTERNAL_EXTENTS.items():
        assert west < east, country
        assert south < north, country
