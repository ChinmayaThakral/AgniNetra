#!/usr/bin/env python3
"""Publication checklist, checks 2 to 4 and 6, run as a command rather than by hand.

Scans every git tracked file. Reports prohibited characters, emoji, banned filler
phrases and attribution lines. Exits 1 if anything is found.

The exclusion list is exact repository relative paths, never a glob and never a
substring. A substring exclusion silently stops protecting any future file whose
path happens to contain it, which is the failure mode this script exists to
prevent. Every exclusion is named here and in context/CONVENTIONS.md, and a test
asserts the two lists agree.

The banned characters are held as codepoint integers rather than literals so this
file does not match its own scan.
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml.paths import ROOT

EXCLUDED: frozenset[str] = frozenset(
    {
        # Imported documents that predate the conventions. Decision D5.
        "INNOVATION_DOSSIER.md",
        "PROJECT_KICKOFF.md",
        # This file holds the banned phrase list by definition.
        "scripts/check_conventions.py",
    }
)

BANNED_CODEPOINTS: dict[int, str] = {
    0x2014: "em dash",
    0x2013: "en dash",
    0x2018: "curly left quote",
    0x2019: "curly right quote",
    0x201C: "curly left double quote",
    0x201D: "curly right double quote",
}

EMOJI_RANGES: tuple[tuple[int, int], ...] = (
    (0x1F300, 0x1FAFF),
    (0x2600, 0x27BF),
    (0x2B00, 0x2BFF),
    (0xFE0F, 0xFE0F),
)

FILLER_PHRASES: tuple[str, ...] = (
    "it is worth noting",
    "in today's fast paced world",
    "leveraging cutting edge",
    "seamlessly",
    "robust and scalable",
    "delve into",
    "game changing",
    "unlock the power of",
)

PRAGMA_OFF_LINE = "<!-- check-conventions: off -->"
PRAGMA_ON_LINE = "<!-- check-conventions: on -->"

# Spatial functions that read ST_Point(latitude, longitude), the reverse of the
# storage order. Called directly they return a plausible wrong number or NaN, with
# no error. Everything goes through the macros in ml/reference/geo.py. See D10.
BANNED_CALLS: tuple[str, ...] = (
    "ST_Distance_Sphere",
    "ST_Distance_Spheroid",
    "ST_Area_Spheroid",
)

# Exact paths allowed to name those functions: the macro definitions, and the
# tests that deliberately pin the broken behaviour.
CALL_EXEMPT: frozenset[str] = frozenset(
    {
        "ml/reference/geo.py",
        "tests/test_geo_distance.py",
    }
)

# The call check applies to code, not prose. A decision entry describing the trap
# must be able to name the function it is about.
CODE_SUFFIXES: frozenset[str] = frozenset({".py", ".ts", ".tsx", ".sql"})

# Attribution footers and co-author trailers. Authorship is the bracketed name
# on each commit subject, so neither belongs in a tracked file.
ATTRIBUTION_MARKERS: tuple[str, ...] = (
    "generated with",
    "co-authored-by:",
)


def tracked_files() -> list[str]:
    """Return git tracked paths, repository relative, sorted."""
    out = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files"],
        capture_output=True,
        text=True,
        check=True,
    )
    return sorted(line for line in out.stdout.splitlines() if line)


def read_text(path: Path) -> str | None:
    """Return decoded text, or None when the file is binary."""
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


def scan(relpath: str) -> tuple[list[str], int]:
    """Return findings and the number of suppressed regions in this file.

    A file may switch off the phrase and attribution checks for a bounded region
    with the pragma comments, so that the documents defining the prohibitions can
    quote them without whitelisting the whole file. The pragma is recognised only
    at column zero, so a documented example of it inside an indented code block
    does not open a region. Character and emoji checks are
    never suppressed, and every suppressed region is counted in the output so a
    region cannot be added without the count changing.
    """
    text = read_text(ROOT / relpath)
    if text is None:
        return [], 0

    findings: list[str] = []
    suppressed_regions = 0
    suppressed = False
    is_code = Path(relpath).suffix in CODE_SUFFIXES

    for lineno, line in enumerate(text.splitlines(), start=1):
        if line.startswith(PRAGMA_OFF_LINE):
            suppressed = True
            suppressed_regions += 1
            continue
        if line.startswith(PRAGMA_ON_LINE):
            suppressed = False
            continue

        for char in line:
            code = ord(char)
            if code in BANNED_CODEPOINTS:
                findings.append(f"{relpath}:{lineno}: {BANNED_CODEPOINTS[code]} U+{code:04X}")
            elif any(low <= code <= high for low, high in EMOJI_RANGES):
                findings.append(f"{relpath}:{lineno}: emoji U+{code:04X}")

        if suppressed:
            continue

        lowered = line.lower()

        if is_code and relpath not in CALL_EXEMPT:
            for call in BANNED_CALLS:
                if call.lower() in lowered:
                    findings.append(
                        f"{relpath}:{lineno}: calls {call} directly. It reads "
                        f"ST_Point(latitude, longitude), the reverse of storage order, and "
                        f"returns a plausible wrong number. Use the geo_ macros. See D10."
                    )

        for phrase in FILLER_PHRASES:
            if phrase in lowered:
                findings.append(f"{relpath}:{lineno}: banned filler phrase '{phrase}'")
        for marker in ATTRIBUTION_MARKERS:
            if marker in lowered:
                findings.append(f"{relpath}:{lineno}: attribution '{marker}'")

    if suppressed:
        findings.append(f"{relpath}: unclosed suppression region, add the closing pragma")

    return findings, suppressed_regions


def main() -> int:
    scanned = 0
    regions = 0
    findings: list[str] = []
    for relpath in tracked_files():
        if relpath in EXCLUDED:
            continue
        scanned += 1
        file_findings, file_regions = scan(relpath)
        findings.extend(file_findings)
        regions += file_regions

    print(f"scanned {scanned} tracked files")
    print(f"excluded {len(EXCLUDED)} by exact path: {', '.join(sorted(EXCLUDED))}")
    print(f"suppressed regions honoured: {regions}")
    print(f"spatial call exemptions: {', '.join(sorted(CALL_EXEMPT))}")

    if findings:
        print(f"\n{len(findings)} violations:")
        for finding in findings:
            print(f"  {finding}")
        return 1

    print("no violations")
    return 0


if __name__ == "__main__":
    sys.exit(main())
