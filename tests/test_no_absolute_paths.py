"""No source file names a location on one person's machine.

The rule is stated in the Python conventions: every data file is read through the
path resolver in ml/paths.py, which anchors on the repository root, and a source file
containing a string that begins with a home directory or a drive letter is a defect.
It was stated and never enforced. Measured before being enforced: zero violations
across every tracked source file. D121.

The patterns are assembled from pieces so this file cannot match its own scan.
"""

import re

import pytest

from ml.paths import ROOT
from ml.tracked import tracked_files

SOURCE_SUFFIXES = (".py", ".ts", ".tsx", ".js", ".mjs", ".cjs", ".sh", ".toml", ".json")
_SLASH, _BACK = "/", "\\"
ABSOLUTE = re.compile(
    "("
    + re.escape(_SLASH + "Users" + _SLASH)
    + "|"
    + re.escape(_SLASH + "home" + _SLASH)
    + "[a-z]"
    + "|"
    + "[A-Za-z]:"
    + re.escape(_BACK * 2)
    + ")"
)


def offending_lines(text: str) -> list[int]:
    return [n for n, line in enumerate(text.splitlines(), start=1) if ABSOLUTE.search(line)]


@pytest.mark.parametrize(
    "line",
    [
        "DATA = '" + _SLASH + "Users" + _SLASH + "someone" + _SLASH + "data.csv'",
        "p = Path('" + _SLASH + "home" + _SLASH + "user" + _SLASH + "x')",
        "raw = r'C:" + _BACK * 2 + "Users" + _BACK * 2 + "x'",
    ],
)
def test_the_matcher_recognises_an_absolute_path(line: str) -> None:
    assert offending_lines(line) == [1]


def test_the_matcher_ignores_relative_and_resolved_paths() -> None:
    text = "ROOT / 'data' / 'raw'\nPath(__file__).resolve().parents[1]\n'docs/figures'\n"
    assert offending_lines(text) == []


def test_no_tracked_source_file_names_an_absolute_path() -> None:
    offenders = []
    for path in tracked_files(SOURCE_SUFFIXES):
        relative = path.relative_to(ROOT).as_posix()
        if relative.startswith("apps/console/node_modules"):
            continue
        for line in offending_lines(path.read_text(errors="replace")):
            offenders.append(f"{relative}:{line}")
    assert not offenders, (
        "absolute paths in source, read through ml/paths.py instead: " + ", ".join(offenders)
    )
