"""The exclusion list is the weak point of any convention check, so it is pinned.

A substring or glob exclusion silently stops protecting future files. These tests
assert the list is exact paths, is exactly the three recorded ones, and that every
one of them is named in CONVENTIONS.md.
"""

import importlib.util
import sys

import pytest

from ml.paths import ROOT

spec = importlib.util.spec_from_file_location(
    "check_conventions", ROOT / "scripts" / "check_conventions.py"
)
assert spec is not None and spec.loader is not None
check_conventions = importlib.util.module_from_spec(spec)
sys.modules["check_conventions"] = check_conventions
spec.loader.exec_module(check_conventions)

# Taken from the checker rather than written out, so this file never contains a
# banned phrase literally and cannot drift from the definition it tests.
PROBE_PHRASE = check_conventions.FILLER_PHRASES[0]

EXPECTED = {
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
    """An exclusion nobody wrote down is an absence rather than a decision.

    The conventions document is kept with the team, so a clean clone cannot check
    this and skips. It still runs during development, which is where an exclusion
    would actually be added.
    """
    conventions = ROOT / "context" / "CONVENTIONS.md"
    if not conventions.is_file():
        pytest.skip("the conventions document is kept outside the repository")
    text = conventions.read_text()
    for entry in check_conventions.EXCLUDED:
        assert entry in text, f"exclusion not documented in the conventions: {entry}"


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
            f"{PROBE_PHRASE} and an " + chr(0x2014) + " dash\n"
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
        probe.write_text(f"    <!-- check-conventions: off -->\n{PROBE_PHRASE}\n")
        findings, regions = check_conventions.scan("_probe_indented.md")
        assert regions == 0
        assert any("filler" in f for f in findings)
    finally:
        probe.unlink(missing_ok=True)


# Taken from the checker so this file never names a guarded function literally.
PROBE_CALL = check_conventions.BANNED_CALLS[0]

CALL_EXEMPT_EXPECTED = {
    "ml/reference/geo.py",
    "tests/test_geo_distance.py",
}


class TestSpatialCallGuard:
    """The axis order footgun returns a plausible wrong number, so a direct call
    has to fail the check rather than rely on anyone remembering D10."""

    def test_exempt_list_is_exactly_the_recorded_two(self) -> None:
        assert set(check_conventions.CALL_EXEMPT) == CALL_EXEMPT_EXPECTED

    def test_no_exemption_is_a_glob(self) -> None:
        for entry in check_conventions.CALL_EXEMPT:
            assert "*" not in entry and "?" not in entry

    def test_every_exemption_exists_on_disk(self) -> None:
        for entry in check_conventions.CALL_EXEMPT:
            assert (ROOT / entry).is_file()

    def test_a_direct_call_in_code_is_flagged(self) -> None:
        probe = ROOT / "_probe_call.py"
        try:
            probe.write_text(f"q = 'SELECT {PROBE_CALL}(a, b)'\n")
            findings, _ = check_conventions.scan("_probe_call.py")
            assert any(PROBE_CALL in f for f in findings)
        finally:
            probe.unlink(missing_ok=True)

    def test_the_same_call_in_prose_is_not_flagged(self) -> None:
        probe = ROOT / "_probe_call.md"
        try:
            probe.write_text(f"D10 explains why {PROBE_CALL} is wrapped.\n")
            findings, _ = check_conventions.scan("_probe_call.md")
            assert not any(PROBE_CALL in f for f in findings)
        finally:
            probe.unlink(missing_ok=True)

    def test_every_guarded_function_is_actually_guarded(self) -> None:
        probe = ROOT / "_probe_call.py"
        for call in check_conventions.BANNED_CALLS:
            try:
                probe.write_text(f"q = '{call}(a, b)'\n")
                findings, _ = check_conventions.scan("_probe_call.py")
                assert any(call in f for f in findings), f"{call} not guarded"
            finally:
                probe.unlink(missing_ok=True)


def test_the_checker_actually_passes_over_the_whole_repository() -> None:
    """Run the checker over every tracked file, not just over probe fixtures.

    The rest of this file tests that the checker would catch a violation. Nothing
    tested that the repository currently has none, and the two things that were
    supposed to cover that both have holes. The local write hook sees only files saved
    through the editor, so a file written through a shell heredoc never reaches it,
    and most of this repository's recent files were written that way. The checker
    itself is a script somebody has to remember to run.

    This closes both by asserting the repository state rather than the checker's
    behaviour, and it does not care how a file arrived.
    """
    offenders: list[str] = []
    for relpath in check_conventions.tracked_files():
        if relpath in check_conventions.EXCLUDED:
            continue
        found, _suppressed = check_conventions.scan(relpath)
        offenders.extend(f"{relpath}: {item}" for item in found)
    assert not offenders, "convention violations in tracked files:\n" + "\n".join(offenders)


# Prohibition 3. The rule was enabled after measuring zero violations, and a detector
# that finds nothing is indistinguishable from a broken one, so these probes prove it
# fires on each banner shape and stays quiet on the look-alikes it must not flag. D121.
BANNER_SHAPES = (
    "# " + "=" * 20,
    "=" * 12,
    "# " + "*" * 8,
    "#" * 10,
    "// " + "=" * 7,
    "=" * 3 + " Setup " + "=" * 3,
    "# " + "#" * 4 + " Results " + "#" * 4,
)
NOT_BANNERS = (
    "# A heading",
    "###### A level six heading",
    "| a | b |",
    "|---|---|",
    "x = a == b",
    'print("=" * 70)',
    "def f(*args, **kwargs):",
    "***",
)


@pytest.mark.parametrize("line", BANNER_SHAPES)
def test_checker_flags_a_decorative_banner(line: str) -> None:
    probe = ROOT / "_probe_banner.md"
    try:
        probe.write_text(line + "\n")
        findings, _ = check_conventions.scan("_probe_banner.md")
        assert any("decorative banner" in f for f in findings), line
    finally:
        probe.unlink(missing_ok=True)


@pytest.mark.parametrize("line", NOT_BANNERS)
def test_checker_ignores_banner_look_alikes(line: str) -> None:
    probe = ROOT / "_probe_not_banner.py"
    try:
        probe.write_text(line + "\n")
        findings, _ = check_conventions.scan("_probe_not_banner.py")
        assert not any("decorative banner" in f for f in findings), line
    finally:
        probe.unlink(missing_ok=True)


# Positive probes for the three checks that had none. Each marker is assembled from
# pieces so this file does not trip the scan it is testing. D121.
PROBES = (
    ("emoji", "a fire " + chr(0x1F525) + " here", "emoji"),
    ("filler", "this works " + "seam" + "lessly now", "banned filler phrase"),
    ("attribution", "Co-" + "Authored-" + "By: someone", "attribution"),
)


@pytest.mark.parametrize(("kind", "line", "expected"), PROBES, ids=[p[0] for p in PROBES])
def test_checker_flags_each_prohibited_kind(kind: str, line: str, expected: str) -> None:
    probe = ROOT / f"_probe_{kind}.md"
    try:
        probe.write_text(line + "\n")
        findings, _ = check_conventions.scan(f"_probe_{kind}.md")
        assert any(expected in f for f in findings), (kind, findings)
    finally:
        probe.unlink(missing_ok=True)
