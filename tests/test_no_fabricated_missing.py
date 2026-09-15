"""A missing value must never be silently substituted with a real one.

`FEATURE_SQL` carried `coalesce(r.prior_count_90d, 0)`, so a detection with no
recurrence row was told its location had zero prior detections in 90 days. That
fabricated a zero for 92.1 percent of B1's training rows at a rate that differed by
class. D61.

**The first version of this guard listed two file paths, being the two where that
defect had already been found.** It therefore could not see `fillna(0.0)` in
`scripts/conformal_aoa_b2.py` and `scripts/export_console.py`, which was the same
defect in code written afterwards, feeding the applicability domain. A guard
written against an instance rather than against a class finds nothing new.

This version enumerates every tracked file and exempts by exact location with a
stated reason. A file this guard does not examine has to be named here.
"""

import re

import pytest

from ml.tracked import relative, tracked_files

# Any construct that turns absent into present. SQL, pandas and numpy.
SUBSTITUTIONS = (
    (re.compile(r"\bcoalesce\s*\(", re.IGNORECASE), "coalesce"),
    (re.compile(r"\bifnull\s*\(", re.IGNORECASE), "ifnull"),
    (re.compile(r"\bnvl\s*\(", re.IGNORECASE), "nvl"),
    (re.compile(r"\.fillna\s*\("), "fillna"),
    (re.compile(r"\bnan_to_num\s*\("), "nan_to_num"),
    (re.compile(r"\bSimpleImputer\s*\("), "SimpleImputer"),
    (re.compile(r"\.interpolate\s*\("), "interpolate"),
)

SCANNED_SUFFIXES = (".py", ".sql", ".ts", ".tsx")

# Exact location, reason. A substitution is allowed only where the value being
# supplied is genuinely known rather than invented, and the reason has to say why.
# `location` is `path:line`, pinned so the exemption cannot drift onto another line.
ALLOWED: dict[str, str] = {
    "ml/features/matrix.py:0": (
        "The module documents the removed coalesce in prose so the defect stays "
        "legible. No live substitution."
    ),
    "tests/test_no_fabricated_missing.py:0": "This file names the patterns by definition.",
    "scripts/verify_published_numbers.py:0": ("Reports on substitutions, does not perform one."),
    # Name fallbacks. `coalesce(nullif(name_en, ''), name)` chooses between two
    # observed values, the English name and the local one. Nothing is invented: if
    # both are absent the result is NULL and the row is filtered explicitly.
    "scripts/build_features_3b.py:60": "Name fallback between two observed values.",
    "scripts/diurnal_by_region.py:107": "Name fallback between two observed values.",
    "scripts/figure_coverage_density.py:42": "Name fallback between two observed values.",
    "scripts/figure_coverage_density.py:49": "Name fallback between two observed values.",
    "scripts/osm_coverage_report.py:30": "Name fallback between two observed values.",
    "scripts/osm_coverage_report.py:35": "Name fallback between two observed values.",
    "scripts/osm_coverage_report.py:70": "Name fallback between two observed values.",
    # Distance sentinels. 1e12 metres stands for "no such asset" inside a `least`,
    # so it is discarded whenever any real distance exists and survives only when
    # none does. It is then compared against a radius, where it correctly reads as
    # not near, or checked against 1e11 and rendered as absent. The sentinel is
    # never published as a distance and never averaged.
    "scripts/lift_with_gem.py:40": "Distance sentinel for absent asset, discarded by least.",
    "scripts/lift_with_gem.py:42": "Distance sentinel for absent asset, discarded by least.",
    "scripts/persistent_sources.py:58": "Distance sentinel, converted to None above 1e11.",
    "scripts/persistent_sources.py:59": "Distance sentinel, converted to None above 1e11.",
    "scripts/persistent_sources.py:60": "Distance sentinel, converted to None above 1e11.",
}


def _exempt(path_key: str) -> str | None:
    """An exemption may pin a whole file with :0 or a single line with :N."""
    file_key = f"{path_key.split(':')[0]}:0"
    return ALLOWED.get(path_key) or ALLOWED.get(file_key)


def _offenders() -> list[str]:
    found: list[str] = []
    for path in tracked_files(SCANNED_SUFFIXES):
        name = relative(path)
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            stripped = line.lstrip()
            if stripped.startswith("#") or stripped.startswith("//"):
                continue
            for pattern, label in SUBSTITUTIONS:
                if not pattern.search(line):
                    continue
                if _exempt(f"{name}:{number}"):
                    continue
                found.append(f"{name}:{number}: {label}: {stripped[:90]}")
    return found


def test_no_unexempted_null_substitution() -> None:
    offenders = _offenders()
    assert not offenders, (
        "A missing value is being substituted with a real one. If the value is "
        "genuinely known, add the exact location to ALLOWED with the reason. If it "
        "is not, the value is fabricated and the caller must handle absence.\n"
        + "\n".join(offenders)
    )


@pytest.mark.parametrize("location", sorted(ALLOWED))
def test_every_exemption_points_at_a_real_file(location: str) -> None:
    """An exemption for a file that no longer exists is an exemption nobody reviewed."""
    from ml.paths import ROOT

    path_part = location.split(":")[0]
    assert (ROOT / path_part).is_file(), f"{location} exempts a file that does not exist"


@pytest.mark.parametrize("location", sorted(ALLOWED))
def test_every_exemption_carries_a_reason(location: str) -> None:
    assert ALLOWED[location].strip(), f"{location} is exempt with no reason given"


def test_the_guard_actually_scans_the_repository() -> None:
    """A guard that enumerates nothing reports clean. This is the check for that."""
    scanned = tracked_files(SCANNED_SUFFIXES)
    assert len(scanned) > 50, f"only {len(scanned)} files scanned, enumeration is broken"


def test_the_recurrence_columns_are_still_features() -> None:
    """If someone deletes the columns rather than fixing a default, the guard above
    would pass. This fails instead."""
    from ml.features.matrix import FEATURE_COLUMNS

    for column in (
        "prior_count_90d",
        "prior_count_30d",
        "night_fraction_90d",
        "frp_variance_90d",
        "mean_gap_days",
    ):
        assert column in FEATURE_COLUMNS, f"{column} left FEATURE_COLUMNS"
