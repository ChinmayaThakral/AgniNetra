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

# Exemptions are keyed by file and by the exact expression, not by line number.
# `location` is `path:0` to exempt a whole file, or `path::<expression>` where the
# expression is the matched line with leading and trailing space stripped and internal
# runs of whitespace collapsed. It was `path:line` and that broke four times in one
# working session: every edit above an exempted line moved it and failed the build
# while nothing about the substitution had changed. Keying on the expression keeps what
# the pinning was for, since an exemption still covers one specific expression rather
# than the file around it, and survives the line moving. The cost is that the same
# expression twice in one file takes one exemption for both; no current entry does
# that, and the guard prints the expression so a second occurrence is visible.
ALLOWED: dict[str, str] = {
    "ml/features/matrix.py:0": (
        "The module documents the removed coalesce in prose so the defect stays legible. No live substitution."
    ),
    "tests/test_no_fabricated_missing.py:0": "This file names the patterns by definition.",
    # The one deliberate substitution in the repository, exempted by exact line so it
    # cannot drift. These two reproduce the superseded imputed applicability domain in
    # order to measure how wrong it was, which is the defect this guard exists to
    # prevent, performed on purpose and reported under a key that says superseded.
    # Nothing downstream reads the result. Removing the exemption is correct the moment
    # the before and after comparison leaves the report. D110.
    "scripts/conformal_aoa_b2.py::fit_filled = fit_set[columns].fillna(0.0)": (
        "Recreates the superseded imputed domain so the before figures are measured "
        "rather than transcribed."
    ),
    "scripts/conformal_aoa_b2.py::imputed_test = imputed_scaler.transform(test[columns].fillna(0.0))": (
        "Recreates the superseded imputed domain so the before figures are measured "
        "rather than transcribed."
    ),
    "scripts/verify_published_numbers.py:0": "Reports on substitutions, does not perform one.",
    "scripts/build_features_3b.py::(SELECT coalesce(nullif(s.name_en, ''), s.name)": (
        "Name fallback between two observed values."
    ),
    "scripts/diurnal_by_region.py::(select coalesce(nullif(s.name_en, ''), s.name)": (
        "Name fallback between two observed values."
    ),
    "scripts/figure_coverage_density.py::SELECT coalesce(nullif(s.name_en, ''), s.name) AS state_name,": (
        "Name fallback between two observed values."
    ),
    "scripts/figure_coverage_density.py::AND coalesce(nullif(s.name_en, ''), s.name) IS NOT NULL": (
        "Name fallback between two observed values."
    ),
    "scripts/osm_coverage_report.py::coalesce(nullif(name_en, ''), name) AS state_name,": (
        "Name fallback between two observed values."
    ),
    "scripts/osm_coverage_report.py::AND coalesce(nullif(name_en, ''), name) IS NOT NULL": (
        "Name fallback between two observed values."
    ),
    "scripts/osm_coverage_report.py::SELECT coalesce(nullif(name_en, ''), name) AS subdistrict_name, geom": (
        "Name fallback between two observed values."
    ),
    # Name fallback again, inside an ORDER BY that makes the point in polygon tie
    # break deterministic and prefers a named polygon over an unnamed one. 83 level 4
    # polygons overlap, one real detection falls inside two, and the unordered pick
    # was handing it the unnamed polygon and therefore no state at all.
    "scripts/build_features_3b.py::ORDER BY (coalesce(nullif(s.name_en, ''), s.name) IS NULL), s.osm_id": (
        "Name fallback ordering the point in polygon tie break."
    ),
    "scripts/diurnal_by_region.py::order by (coalesce(nullif(s.name_en, ''), s.name) is null), s.osm_id": (
        "Name fallback ordering the point in polygon tie break."
    ),
    'scripts/lift_with_gem.py::"least(coalesce(c.industrial_m, 1e12), coalesce(g.gem_m_temporal, 1e12))"': (
        "Distance sentinel for absent asset, discarded by least."
    ),
    'scripts/lift_with_gem.py::else "coalesce(c.industrial_m, 1e12)"': (
        "Distance sentinel for absent asset, discarded by least."
    ),
    "scripts/persistent_sources.py::coalesce(c.industrial_m, 1e12),": (
        "Distance sentinel, converted to None above 1e11."
    ),
    "scripts/persistent_sources.py::coalesce(g.gem_m_temporal, 1e12),": (
        "Distance sentinel, converted to None above 1e11."
    ),
    "scripts/persistent_sources.py::coalesce(c.flare_m, 1e12)": (
        "Distance sentinel, converted to None above 1e11."
    ),
}


def _normalise(line: str) -> str:
    """The matched line as an exemption key sees it: stripped, whitespace collapsed."""
    return re.sub(r"\s+", " ", line.strip())


def _exempt(name: str, line: str) -> str | None:
    """An exemption pins a whole file with :0 or one expression with ::<expression>."""
    return ALLOWED.get(f"{name}:0") or ALLOWED.get(f"{name}::{_normalise(line)}")


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
                if _exempt(name, line):
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


SUPERSEDED_EXEMPTIONS = (
    "scripts/conformal_aoa_b2.py::fit_filled = fit_set[columns].fillna(0.0)",
    "scripts/conformal_aoa_b2.py::imputed_test = "
    "imputed_scaler.transform(test[columns].fillna(0.0))",
)
SUPERSEDED_KEY = "superseded_imputed_outside_aoa_fraction"


def test_the_superseded_exemption_does_not_outlive_its_reason() -> None:
    """The one deliberate substitution is allowed only while something cites it.

    Its justification is that the before and after comparison in the results needs
    the imputed figures measured rather than transcribed. That justification was
    originally a comment saying to remove the exemption when the comparison leaves
    the report, which is enforcement by memory. This is the enforcement. D111.
    """
    from ml.paths import ROOT

    # docs/ exists only on the owner's machine and never in the published repository,
    # so in a clean clone the citation this test looks for cannot exist and the test
    # would fail on every checkout without protecting anything. It is enforced in full
    # wherever the report is present. Approved by the owner on 2026-09-23. D121.
    if not (ROOT / "docs").is_dir():
        pytest.skip("docs/ is local only, so the citation cannot be checked here")

    present = [key for key in SUPERSEDED_EXEMPTIONS if key in ALLOWED]
    # Only prose may serve as evidence. The tracer's own report quotes the results
    # line verbatim, so counting generated documents would let the exemption keep
    # itself alive through a document that merely echoes the thing under test. D112.
    from ml.documents import prose_documents

    cited = [
        path.relative_to(ROOT).as_posix()
        for path in prose_documents("docs")
        if SUPERSEDED_KEY in path.read_text()
    ]
    if present and not cited:
        raise AssertionError(
            "The fillna exemption in scripts/conformal_aoa_b2.py is still in ALLOWED, "
            f"but no document cites {SUPERSEDED_KEY} any more. The comparison it exists "
            "for has left the report, so delete the exemption and the imputed pass."
        )
    if cited and not present:
        raise AssertionError(
            f"A document cites {SUPERSEDED_KEY} but the exemption is gone, so the "
            "imputed pass cannot be computing it. Check what that number now refers to."
        )
