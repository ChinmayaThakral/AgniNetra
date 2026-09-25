"""Every decision in the log has exactly one plain English line in the companion.

A note in the working agreement asks for the line to be added with the entry. A note is a habit
rather than a check, and this project has recorded what happens to habits, so the
appendix is compared against the log in both directions.
"""

import re

import pytest

from ml.paths import ROOT

LOG = ROOT / "context" / "DECISIONS.md"
COMPANION = ROOT / "context" / "DECISIONS_EXPLAINED.md"

if not (LOG.is_file() and COMPANION.is_file()):
    pytest.skip("context is kept outside the repository", allow_module_level=True)

ENTRY = re.compile(r"^## D(\d+)\.", re.MULTILINE)
ROW = re.compile(r"^\| D(\d+) \|", re.MULTILINE)


def _appendix() -> str:
    text = COMPANION.read_text()
    marker = "## 8. Appendix"
    assert marker in text, "the companion has no appendix section"
    return text[text.index(marker) :]


def test_every_decision_has_an_appendix_line() -> None:
    logged = {int(n) for n in ENTRY.findall(LOG.read_text())}
    explained = {int(n) for n in ROW.findall(_appendix())}
    missing = sorted(logged - explained)
    assert not missing, f"decisions with no plain English line: {missing}"


def test_no_appendix_line_names_a_decision_that_does_not_exist() -> None:
    logged = {int(n) for n in ENTRY.findall(LOG.read_text())}
    explained = {int(n) for n in ROW.findall(_appendix())}
    assert not explained - logged, f"lines for unknown decisions: {sorted(explained - logged)}"


def test_each_decision_appears_exactly_once() -> None:
    rows = [int(n) for n in ROW.findall(_appendix())]
    repeated = sorted({n for n in rows if rows.count(n) > 1})
    assert not repeated, f"decisions listed more than once: {repeated}"
