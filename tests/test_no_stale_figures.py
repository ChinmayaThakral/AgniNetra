"""Stale published numbers must not reappear.

The persistent source count was published as 296 sources and 39 unregistered,
inflated by an aggregation fault, and corrected to 94 and 21. D53. The wrong values
had already reached results.md, the paper outline, the phase file and the console
manifest before anyone noticed, and no test caught it: it was found by looking at a
screenshot.

The old numbers may still appear where a document is explaining the correction.
They may not appear as a current claim. A line carrying one of them must also carry
a marker showing it is historical.
"""

import re

import pytest

from ml.paths import ROOT

# value, the wording that would make it a current claim
STALE = (
    (r"\b296\b", "persistent source count before re-clustering"),
    (r"\b39\b", "unregistered source count before re-clustering"),
)

# A line may state an old number if it is visibly describing the correction.
HISTORICAL_MARKERS = (
    "earlier version",
    "first version",
    "before re",
    "corrected",
    "D53",
    "was wrong",
    "against 21",
    "become 94",
    "inflated",
)

SOURCE_CONTEXT = re.compile(r"(source|registry|unregistered|recurring|persistent)", re.IGNORECASE)

# The decision log is the record of the correction and quotes both figures
# throughout, and the sweep script names them by construction.
EXEMPT = {
    "context/DECISIONS.md",
    "tests/test_no_stale_figures.py",
    "docs/paper_outline.md",
}

SCANNED = sorted(
    path
    for pattern in ("docs/**/*.md", "context/**/*.md", "apps/console/**/*.md")
    for path in ROOT.glob(pattern)
    if "node_modules" not in str(path)
)


@pytest.mark.parametrize("path", SCANNED, ids=lambda p: str(p.relative_to(ROOT)))
def test_no_stale_source_count_stated_as_current(path) -> None:
    relative = str(path.relative_to(ROOT))
    if relative in EXEMPT:
        pytest.skip("records the correction")
    offenders = []
    for number, meaning in STALE:
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            if not re.search(number, line) or not SOURCE_CONTEXT.search(line):
                continue
            if any(marker.lower() in line.lower() for marker in HISTORICAL_MARKERS):
                continue
            offenders.append(f"{relative}:{lineno}: {meaning}: {line.strip()[:90]}")
    assert not offenders, "\n".join(offenders)


def test_the_corrected_values_are_the_ones_published() -> None:
    results = (ROOT / "docs" / "results.md").read_text()
    assert "94 persistent sources" in results


def test_the_unregistered_claim_is_published_as_retracted() -> None:
    """This test previously pinned the claim that 21 sources were unregistered.
    That claim was retracted, D56, so the test now pins the retraction. A test
    asserting a withdrawn result is worse than no test."""
    results = (ROOT / "docs" / "results.md").read_text()
    assert "retracted" in results.lower()
    assert "none of the 21 is in a place no registry knows about" in results.lower()
    assert "not established" in results


def test_exported_console_data_matches_the_published_count() -> None:
    import json

    data = ROOT / "apps" / "console" / "public" / "data"
    sources = json.loads((data / "sources.json").read_text())
    unregistered = sum(1 for s in sources if not s["registered"])
    assert len(sources) == 94, f"exported {len(sources)}, results.md says 94"
    assert unregistered == 21, f"exported {unregistered}, results.md says 21"


def test_the_manifest_describes_clustering_not_rounding() -> None:
    import json

    manifest = json.loads(
        (ROOT / "apps" / "console" / "public" / "data" / "manifest.json").read_text()
    )
    rule = manifest["persistentSourceRule"]
    assert "clustered by great circle" in rule
    assert "decimal places" not in rule
