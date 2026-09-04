"""The paper outline's pointers must resolve, in both directions.

The outline's whole discipline is that every claim points at a figure, a table or a
decision number. A pointer to a file that does not exist, or a figure nobody cites,
breaks that silently and would only be found by a reader following a reference.
"""

import re

import pytest

from ml.paths import ROOT

OUTLINE = ROOT / "docs" / "paper_outline.md"
TEXT = OUTLINE.read_text()


def referenced(pattern: str) -> set[str]:
    return set(re.findall(pattern, TEXT))


def test_outline_exists() -> None:
    assert OUTLINE.is_file()


@pytest.mark.parametrize("relative", sorted(referenced(r"figures/[a-z0-9_]+\.png")))
def test_every_referenced_figure_exists(relative: str) -> None:
    assert (ROOT / "docs" / relative).is_file(), relative


@pytest.mark.parametrize("relative", sorted(referenced(r"scripts/[a-z0-9_]+\.py")))
def test_every_regeneration_script_exists(relative: str) -> None:
    assert (ROOT / relative).is_file(), relative


@pytest.mark.parametrize("relative", sorted(referenced(r"docs/[a-z0-9_]+\.md")))
def test_every_referenced_table_exists(relative: str) -> None:
    assert (ROOT / relative).is_file(), relative


def test_no_figure_is_uncited() -> None:
    """A figure in the directory that the outline never mentions is either an
    orphan or a missing claim. Either way somebody should look at it."""
    on_disk = {path.name for path in (ROOT / "docs" / "figures").glob("*.png")}
    cited = {name.split("/")[-1] for name in referenced(r"figures/[a-z0-9_]+\.png")}
    assert on_disk == cited, f"uncited: {sorted(on_disk - cited)}"


def test_every_referenced_decision_exists() -> None:
    decisions = (ROOT / "context" / "DECISIONS.md").read_text()
    numbered = set(re.findall(r"^## (D\d+)\.", decisions, flags=re.M))
    cited = set(re.findall(r"\bD(\d+)\b", TEXT))
    missing = {f"D{n}" for n in cited} - numbered
    assert not missing, f"outline cites decisions that do not exist: {sorted(missing)}"


def test_assertions_are_counted_honestly() -> None:
    """The outline states how many unsupported claims it contains. The count in the
    prose and the number of marked claims must agree, or the honesty is decorative."""
    marked = TEXT.count("ASSERTION")
    listed = len(re.findall(r"^\d+\. Section", TEXT, flags=re.M))
    # One occurrence explains the marker itself. A claim resolved by retraction
    # loses its inline marker, because it is no longer an open assertion, and is
    # recorded under its own heading instead. So the arithmetic stays simple.
    assert marked - 1 == listed, f"{marked - 1} marked, {listed} listed outstanding"
