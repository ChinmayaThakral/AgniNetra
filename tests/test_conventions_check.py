"""The exclusion list is the weak point of any convention check, so it is pinned.

A substring or glob exclusion silently stops protecting future files. These tests
assert the list is exact paths, is exactly the three recorded ones, and that every
one of them is named in CONVENTIONS.md.
"""

import importlib.util
import sys

from ml.paths import ROOT

spec = importlib.util.spec_from_file_location(
    "check_conventions", ROOT / "scripts" / "check_conventions.py"
)
assert spec is not None and spec.loader is not None
check_conventions = importlib.util.module_from_spec(spec)
sys.modules["check_conventions"] = check_conventions
spec.loader.exec_module(check_conventions)

EXPECTED = {
    "INNOVATION_DOSSIER.md",
    "PROJECT_KICKOFF.md",
    "scripts/check_conventions.py",
}


def test_exclusion_list_is_exactly_the_recorded_three() -> None:
    assert set(check_conventions.EXCLUDED) == EXPECTED


def test_no_exclusion_is_a_glob_or_wildcard() -> None:
    for entry in check_conventions.EXCLUDED:
        assert "*" not in entry
        assert "?" not in entry
        assert not entry.endswith("/")


def test_every_exclusion_exists_on_disk() -> None:
    for entry in check_conventions.EXCLUDED:
        assert (ROOT / entry).is_file(), f"excluded path does not exist: {entry}"


def test_every_exclusion_is_named_in_conventions() -> None:
    conventions = (ROOT / "context" / "CONVENTIONS.md").read_text()
    for entry in check_conventions.EXCLUDED:
        assert entry in conventions, f"exclusion not documented in CONVENTIONS.md: {entry}"


def test_checker_flags_a_banned_character() -> None:
    probe = ROOT / "_probe_check_conventions.md"
    try:
        probe.write_text("bad " + chr(0x2014) + " dash\n")
        findings, _ = check_conventions.scan("_probe_check_conventions.md")
        assert any("em dash" in f for f in findings)
    finally:
        probe.unlink(missing_ok=True)


def test_pragma_suppresses_phrases_but_never_characters() -> None:
    probe = ROOT / "_probe_pragma.md"
    try:
        probe.write_text(
            "<!-- check-conventions: off -->\n"
            "seamlessly and an " + chr(0x2014) + " dash\n"
            "<!-- check-conventions: on -->\n"
        )
        findings, regions = check_conventions.scan("_probe_pragma.md")
        assert regions == 1
        assert not any("filler" in f for f in findings)
        assert any("em dash" in f for f in findings)
    finally:
        probe.unlink(missing_ok=True)


def test_indented_pragma_example_does_not_open_a_region() -> None:
    probe = ROOT / "_probe_indented.md"
    try:
        probe.write_text("    <!-- check-conventions: off -->\nseamlessly\n")
        findings, regions = check_conventions.scan("_probe_indented.md")
        assert regions == 0
        assert any("filler" in f for f in findings)
    finally:
        probe.unlink(missing_ok=True)
