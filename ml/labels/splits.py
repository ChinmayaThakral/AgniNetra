"""Spatially blocked splits by state.

Thermal detections are strongly spatially autocorrelated. A random split puts
detections from the same industrial site in both train and test and reports a
number that will not survive one question. D3.

Three held out state groups are used and the spread across them is reported
alongside the mean. The groups are fixed here rather than drawn at random, so that
a result is reproducible and so that each group spans a mix of the industrial,
agricultural and forested regimes rather than being one climate.
"""

from typing import Final

# Groups are built to be regime diverse rather than geographically contiguous. A
# contiguous group would confound region with source mix, which is the thing the
# spatially blocked protocol exists to avoid.
HELD_OUT_GROUPS: Final[dict[str, tuple[str, ...]]] = {
    "group_a": (
        "Punjab",
        "Odisha",
        "Karnataka",
        "Meghalaya",
    ),
    "group_b": (
        "Haryana",
        "Chhattisgarh",
        "Tamil Nadu",
        "Assam",
    ),
    "group_c": (
        "Uttar Pradesh",
        "Jharkhand",
        "Gujarat",
        "Mizoram",
    ),
}


class SplitError(RuntimeError):
    """Raised when the split protocol is violated."""


def validate_groups(groups: dict[str, tuple[str, ...]] = HELD_OUT_GROUPS) -> None:
    """Assert no state appears in two groups and no group is empty.

    Raises SplitError rather than returning a flag, because a silently overlapping
    split produces a number that looks fine and is not.
    """
    seen: dict[str, str] = {}
    for group_name, states in groups.items():
        if not states:
            raise SplitError(f"{group_name} is empty")
        for state in states:
            if state in seen:
                raise SplitError(
                    f"{state} appears in both {seen[state]} and {group_name}. "
                    "A state in two held out groups leaks between folds."
                )
            seen[state] = group_name


def assign_fold(state: str, groups: dict[str, tuple[str, ...]] = HELD_OUT_GROUPS) -> str | None:
    """Return the held out group a state belongs to, or None if it is always train."""
    for group_name, states in groups.items():
        if state in states:
            return group_name
    return None


def split_for(
    group_name: str, groups: dict[str, tuple[str, ...]] = HELD_OUT_GROUPS
) -> tuple[frozenset[str], frozenset[str]]:
    """Return (train states, test states) for one held out group.

    Every state not in the held out group is train, including states in the other
    two groups. This is a held out region protocol, not a three way partition.
    """
    if group_name not in groups:
        raise SplitError(f"unknown group {group_name!r}. Known: {', '.join(groups)}")
    test = frozenset(groups[group_name])
    everything = frozenset(state for states in groups.values() for state in states)
    return everything - test, test


# The fourth group is not a state group. The ingest bounding box is a rectangle
# and India is not, so 41 percent of ingested detections fall outside every Indian
# state polygon, 96.6 percent of them inside a neighbouring country. Those rows are
# a resource rather than a caveat: Pakistani Punjab burns the same crop on the same
# calendar as Indian Punjab with entirely different reference coverage, and Sri
# Lanka is a different agricultural regime altogether.
#
# Held apart from the three state groups, they answer a question no within India
# split can: does the model transfer across a national border where agricultural
# practice and reference coverage both change. D26.
EXTERNAL_GROUP: Final[str] = "group_d_external"

EXTERNAL_EXTENTS: Final[dict[str, tuple[float, float, float, float]]] = {
    "Pakistan": (60.8, 23.6, 77.9, 37.1),
    "Sri Lanka": (79.6, 5.8, 82.0, 10.0),
}


def in_external_extent(*, longitude: float, latitude: float) -> str | None:
    """Return the external country a coordinate falls in, or None.

    Only meaningful for a detection that falls inside no Indian state polygon.
    These extents overlap India, so containment here is not by itself evidence of
    being outside India.
    """
    for country, (west, south, east, north) in EXTERNAL_EXTENTS.items():
        if west <= longitude <= east and south <= latitude <= north:
            return country
    return None


def assert_external_disjoint_from_states(
    groups: dict[str, tuple[str, ...]] = HELD_OUT_GROUPS,
) -> None:
    """The external group is defined by absence of a state, so it cannot overlap.

    Asserted rather than assumed, because the guarantee rests on the assignment
    rule and a future change to that rule would break it silently.
    """
    if EXTERNAL_GROUP in groups:
        raise SplitError(
            f"{EXTERNAL_GROUP} must not be a state group. It is defined by falling "
            "outside every Indian state polygon, not by a list of state names."
        )
