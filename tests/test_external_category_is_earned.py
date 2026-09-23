"""The external category must require both halves of its justification.

A figure quoted from another paper is not a defect, so it is separated from
unbacked. That separation is only honest if it cannot be obtained by writing a
number near a DOI, or by writing the word unverified next to an awkward figure.
Both a resolvable citation and a recorded read depth are required, and these tests
fail if either requirement is dropped. D109.
"""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "verify_published_numbers", ROOT / "scripts" / "verify_published_numbers.py"
)
assert spec and spec.loader
vp = importlib.util.module_from_spec(spec)
sys.modules["verify_published_numbers"] = vp
spec.loader.exec_module(vp)

CITATION_ONLY = "Ma and colleagues, `doi:10.1002/gdj3.259`, report 4410 records.\n"
DEPTH_ONLY = "Read at full text, the survey reports 4410 records at 95.08 percent.\n"
BOTH = "Ma and colleagues, `doi:10.1002/gdj3.259`. Read at full text: 4410 records.\n"


def test_a_citation_without_a_read_depth_does_not_qualify() -> None:
    assert vp.external_lines(CITATION_ONLY) == set()


def test_a_read_depth_without_a_citation_does_not_qualify() -> None:
    assert vp.external_lines(DEPTH_ONLY) == set()


def test_both_together_qualify() -> None:
    assert vp.external_lines(BOTH) == {1}


def test_qualification_does_not_leak_across_a_blank_line() -> None:
    """A neighbouring paragraph must not inherit the citation.

    Paragraph scoping is what lets a wrapped citation cover the figures it
    supports. Without a boundary it would let any number in the document claim the
    nearest citation several paragraphs away.
    """
    text = BOTH + "\nAn unrelated paragraph claiming 0.9999 accuracy.\n"
    qualified = vp.external_lines(text)
    assert 1 in qualified
    assert 3 not in qualified


def test_the_live_report_has_no_external_claim_without_both_markers() -> None:
    """Every external claim in the real documents survives the stated rule."""
    for relative in vp.documents():
        text = (ROOT / relative).read_text()
        for line_number in vp.external_lines(text):
            paragraph = _paragraph_containing(text, line_number)
            assert vp.EXTERNAL_CITATION.search(paragraph), relative
            assert vp.READ_DEPTH.search(paragraph), relative


def _paragraph_containing(text: str, line_number: int) -> str:
    lines = text.splitlines()
    start = line_number - 1
    while start > 0 and lines[start - 1].strip():
        start -= 1
    end = line_number - 1
    while end + 1 < len(lines) and lines[end + 1].strip():
        end += 1
    return "\n".join(lines[start : end + 1])
