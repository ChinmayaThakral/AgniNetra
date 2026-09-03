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
