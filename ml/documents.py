"""Which documents a check may read, decided by the document's own declaration.

A generated document declares itself in its header with a regeneration command.
That declaration, not a path list, is what separates the two kinds, because a path
list silently omits the next generated document somebody adds.

Two checks in this repository have already failed on this. The number tracer
admitted prose into its backing tier, so `paper_outline.md` could back its own
claims. Then the exemption lifetime test scanned `docs/` for a citation and found
it inside the tracer's own generated report, so it could never fail. Both have the
same root: a check read a document it generates.

The distinction that matters is evidence against subject. A generated document may
be the **subject** of a check, since a generator emitting a stale number is a real
defect. It may never be the **evidence** for one, because then the check is reading
its own output. D112.
"""

from pathlib import Path
from typing import Final

from ml.paths import ROOT

HEADER_LINES: Final[int] = 10
DECLARATION: Final[str] = "Regenerate:"


def is_generated(path: Path) -> bool:
    """True when a script wrote this document, declared in its own header.

    The header rather than the whole text: a prose document quoting a regeneration
    command is still prose, and testing the body admitted the audit reports and
    paper_outline.md as evidence.
    """
    return DECLARATION in "\n".join(path.read_text().splitlines()[:HEADER_LINES])


def markdown_under(*directories: str) -> list[Path]:
    """Every markdown file under the given repository relative directories."""
    found: list[Path] = []
    for directory in directories:
        root = ROOT / directory
        if root.is_dir():
            found.extend(p for p in root.rglob("*.md") if "node_modules" not in str(p))
    return sorted(found)


def prose_documents(*directories: str) -> list[Path]:
    """Documents a person wrote. The only ones that may serve as evidence."""
    return [p for p in markdown_under(*directories) if not is_generated(p)]


def generated_documents(*directories: str) -> list[Path]:
    """Documents a script wrote."""
    return [p for p in markdown_under(*directories) if is_generated(p)]


# A generated document goes stale in two ways. The data under it can change, which the
# ingest date check catches, or the code that produced it can change, which it cannot.
# m1_prototype.md was stale the second way and nothing noticed, D117. So each generator
# records a digest of its own code in the document it writes, and the freshness check
# recomputes it.
#
# The digest covers the script and every repository module it imports, transitively,
# because the M1 documents went stale through ml/labels/weak.py rather than through their
# own scripts. It excludes this module, which records digests and does not shape any
# result, so that editing the recorder does not mark every document stale. D121.
DIGEST_LABEL: Final[str] = "Generator digest:"
_EXCLUDED_FROM_DIGEST: Final[frozenset[str]] = frozenset({"ml/documents.py"})


def _repo_imports(path: Path) -> set[Path]:
    """Repository modules imported by one file, resolved to paths."""
    import ast

    found: set[Path] = set()
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names = [node.module] + [f"{node.module}.{alias.name}" for alias in node.names]
        for name in names:
            if not name.startswith("ml"):
                continue
            base = ROOT / Path(*name.split("."))
            for candidate in (base.with_suffix(".py"), base / "__init__.py"):
                if candidate.is_file():
                    found.add(candidate)
    return found


def generator_closure(script: Path) -> list[Path]:
    """The script and every repository module it reaches, in a stable order."""
    seen: set[Path] = set()
    pending = [script.resolve()]
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        pending.extend(p.resolve() for p in _repo_imports(current))
    return sorted(
        (p for p in seen if p.relative_to(ROOT).as_posix() not in _EXCLUDED_FROM_DIGEST),
        key=lambda p: p.relative_to(ROOT).as_posix(),
    )


def generator_digest(script: Path) -> str:
    """Sixteen hex characters of SHA-256 over the generator's closure."""
    import hashlib

    digest = hashlib.sha256()
    for path in generator_closure(script):
        digest.update(path.relative_to(ROOT).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()[:16]


def provenance_line(script: str | Path) -> str:
    """The header line a generator writes into its document."""
    return f"{DIGEST_LABEL} `{generator_digest(Path(script))}`"


def declared_generator(document: Path) -> Path | None:
    """The script a generated document names in its regeneration command."""
    import re

    header = "\n".join(document.read_text().splitlines()[:HEADER_LINES])
    match = re.search(r"scripts/([A-Za-z0-9_]+\.py)", header)
    return ROOT / "scripts" / match.group(1) if match else None


def recorded_digest(document: Path) -> str | None:
    """The digest a generated document carries, or None if it carries none."""
    import re

    for line in document.read_text().splitlines()[: HEADER_LINES + 4]:
        match = re.search(rf"{re.escape(DIGEST_LABEL)} `([0-9a-f]{{16}})`", line)
        if match:
            return match.group(1)
    return None
