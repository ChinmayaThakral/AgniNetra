"""One definition of what a generated document is, and no local copies of it.

Two checks in this repository failed because a check read a document it generates.
The fix is structural: the document declares its own kind in its header, and every
check that scans a directory consults the single definition in ml/documents.py.

A local reimplementation is the thing that would quietly reintroduce the defect, so
this fails if one appears. D112.
"""

import re
from pathlib import Path

from ml.documents import DECLARATION, generated_documents, is_generated, prose_documents
from ml.paths import ROOT
from ml.tracked import tracked_files

CANONICAL = "ml/documents.py"
# The declaration string appearing in a check that is not the canonical module is
# almost always a second copy of the type test.
LOCAL_COPY = re.compile(r'["\']Regenerate:["\']')


def test_the_two_kinds_are_disjoint_and_cover_everything() -> None:
    prose = set(prose_documents("docs"))
    generated = set(generated_documents("docs"))
    assert not (prose & generated)
    assert prose | generated == set(
        p for p in (ROOT / "docs").rglob("*.md") if "node_modules" not in str(p)
    )


def test_no_check_reimplements_the_type_test() -> None:
    offenders = []
    for path in tracked_files((".py",)):
        relative = path.relative_to(ROOT).as_posix()
        if relative == CANONICAL:
            continue
        if LOCAL_COPY.search(path.read_text()):
            offenders.append(relative)
    assert not offenders, (
        "These files spell out the generated document declaration themselves instead "
        f"of importing it from {CANONICAL}: {offenders}. A local copy is where the "
        "definition drifts, and both failures of this kind came from a check using its "
        "own idea of what a generated document is."
    )


def test_a_document_is_classified_by_its_header_not_its_body(tmp_path: Path) -> None:
    """Quoting a regeneration command in prose must not make the prose evidence."""
    body_only = tmp_path / "quotes_it.md"
    body_only.write_text(
        "# A prose document\n\n"
        + "\n".join(f"filler line {n}" for n in range(12))
        + f"\n\nIt discusses {DECLARATION} `uv run python scripts/thing.py` in the body.\n"
    )
    assert not is_generated(body_only)

    header = tmp_path / "declares_it.md"
    header.write_text(f"# Generated\n\n{DECLARATION} `uv run python scripts/thing.py`\n")
    assert is_generated(header)
