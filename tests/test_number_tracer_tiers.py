"""The number tracer's two tiers must stay disjoint, by construction not by blocklist.

Evidence is what a script wrote. Claims are prose. A document is one or the other,
decided by whether its own header declares a regenerate command, and nothing may be
both its own claim and its own proof.

This exists because the tiers were not disjoint and nothing noticed. The backing tier
admitted any document containing the string `Regenerate:` anywhere in its body, so the
audit reports, which quote the numbers they audit, and `paper_outline.md`, which quotes
regenerate commands, both became evidence. The outline backed its own claims, the pool
reached 5205 values, and the tracer reported 99.5 percent reproduced and 7 unbacked
against a true figure of 86. It was caught by a person refusing an implausible
improvement, not by any check. D95.

The report is the reason this is a test rather than a note. It will be prose
that quotes every number in the project, and when it enters the checked tier something
will eventually try to admit it to the backing tier too.
"""

import importlib.util
import re
import sys

from ml.documents import is_generated
from ml.tracked import ROOT

_spec = importlib.util.spec_from_file_location(
    "verify_published_numbers", ROOT / "scripts" / "verify_published_numbers.py"
)
assert _spec is not None and _spec.loader is not None
tracer = importlib.util.module_from_spec(_spec)
sys.modules["verify_published_numbers"] = tracer
_spec.loader.exec_module(tracer)


def _evidence() -> set[str]:
    return {p.relative_to(ROOT).as_posix() for p in tracer.evidence_documents()}


def test_the_two_tiers_never_intersect() -> None:
    both = set(tracer.documents()) & _evidence()
    assert not both, (
        "these documents are both a claim and its own proof, which is how the tracer "
        f"came to report 99.5 percent while measuring nothing: {sorted(both)}"
    )


# The synthesis documents, and the report when it exists. These are prose by nature:
# they quote every number in the project, so admitting any of them as evidence lets the
# project prove itself. Pinned by name because that is the regression worth catching,
# and a name is what changes when somebody adds a Regenerate header to one of them.
NEVER_EVIDENCE = (
    "docs/results.md",
    "docs/paper_outline.md",
    "docs/report_outline.md",
    "docs/dataset_card.md",
    "docs/evaluation_protocol.md",
    "docs/report.md",
)


def test_the_synthesis_documents_are_never_evidence() -> None:
    """The regression that actually happened, asserted directly.

    An earlier version of this file tested that evidence documents carry a regenerate
    header, which cannot fail: evidence documents are defined as those carrying one.
    Adding the header to results.md promoted it to evidence and the suite stayed green,
    which is the failure class this file exists to guard against, committed inside the
    guard itself. This assertion names the documents instead, so promoting one fails.
    """
    promoted = sorted(set(NEVER_EVIDENCE) & _evidence())
    assert not promoted, (
        "prose documents admitted as evidence, so the project is proving itself with "
        f"its own prose: {promoted}"
    )


def test_every_evidence_document_names_a_script_that_exists() -> None:
    """Weaker than proving the script wrote it, and still falsifiable.

    Filenames are often built dynamically, so a literal search for the document name
    inside the script gives false positives. What can be checked is that the declared
    producer exists at all, which catches a renamed or deleted script leaving a document
    claiming a provenance it no longer has.
    """
    missing = []
    for relative in sorted(_evidence()):
        header = "\n".join((ROOT / relative).read_text().splitlines()[:10])
        named = re.findall(r"scripts/([A-Za-z0-9_]+\.py)", header)
        if not named:
            missing.append(f"{relative}: header names no script")
        elif not (ROOT / "scripts" / named[0]).is_file():
            missing.append(f"{relative}: names scripts/{named[0]}, which does not exist")
    assert not missing, "evidence with an unverifiable producer:\n" + "\n".join(missing)


def test_audit_reports_are_never_evidence() -> None:
    """They quote the numbers they audit, so admitting them is circular by definition."""
    audit = [d for d in _evidence() if "/audit/" in d]
    assert not audit, f"audit reports admitted as evidence: {sorted(audit)}"


def test_every_prose_document_is_actually_prose() -> None:
    for relative in tracer.documents():
        assert not is_generated(ROOT / relative), (
            f"{relative} declares a regenerate command but is being checked as a claim. "
            "A generated document is evidence; checking it asserts nothing."
        )
