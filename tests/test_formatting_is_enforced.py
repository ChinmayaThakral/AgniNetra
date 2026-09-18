"""Ruff must pass over the repository, asserted here because nothing else asserts it.

`ruff check` and `ruff format --check` are in the project's verification battery and
are enforced nowhere: there is no CI workflow, no pre-commit config, no active git
hook, and no test invoked them. They ran only when somebody typed them, and
`ruff format --check` had been failing on two committed files since 9e497dc without
anyone noticing.

That is the third time this shape has appeared here. `next lint` reported success
while linting nothing for weeks because it was deprecated and silently prompted.
`scripts/check_conventions.py` covered every tracked file and no test ran it. A check
that exists as a command somebody must remember is not a check.

There is no CI in this project, so the test suite is the enforcement layer. These skip
rather than fail when ruff is absent, because a fresh clone must be able to run the
suite, which is the D72 lesson.
"""

import shutil
import subprocess

import pytest

from ml.tracked import ROOT

RUFF = shutil.which("ruff")
pytestmark = pytest.mark.skipif(RUFF is None, reason="ruff is not installed in this environment")


def _ruff(*args: str) -> subprocess.CompletedProcess[str]:
    assert RUFF is not None
    return subprocess.run([RUFF, *args], cwd=ROOT, capture_output=True, text=True, check=False)


def test_ruff_check_passes_over_the_repository() -> None:
    result = _ruff("check", ".")
    assert result.returncode == 0, f"ruff check reported findings:\n{result.stdout}"


def test_ruff_format_check_passes_over_the_repository() -> None:
    """The one that was actually failing, and the reason this file exists."""
    result = _ruff("format", "--check", ".")
    assert result.returncode == 0, (
        "ruff format --check reports files that are not formatted. Run "
        f"`uv run ruff format .` and re run.\n{result.stdout}"
    )
