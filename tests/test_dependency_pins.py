"""Every declared dependency is pinned, and the lock agrees with the declaration.

There were three dependency lists. `requirements.txt` drifted from the other two and
the README pointed new members at it, so a clean install lacked h5py, rasterio and
scikit-learn and passed only because `uv run` quietly re-synced from pyproject. That
file is gone. What remains are two lists with different jobs: `pyproject.toml`
declares the direct dependencies, and `requirements.lock.txt` freezes the environment
the results were produced in. This holds them together.
"""

import re
import tomllib

from ml.tracked import ROOT

PIN = re.compile(r"^([A-Za-z0-9_.\-]+)==([^\s;]+)$")


def _normalise(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _declared() -> list[str]:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    declared = list(project["dependencies"])
    for extra in project.get("optional-dependencies", {}).values():
        declared.extend(extra)
    return declared


def _locked() -> dict[str, str]:
    locked = {}
    for line in (ROOT / "requirements.lock.txt").read_text().splitlines():
        match = PIN.match(line.strip())
        if match:
            locked[_normalise(match.group(1))] = match.group(2)
    return locked


def test_every_declared_dependency_is_pinned_exactly() -> None:
    loose = [spec for spec in _declared() if not PIN.match(spec)]
    assert not loose, f"declared without an exact pin: {loose}"


def test_the_lock_carries_every_declared_pin_at_the_same_version() -> None:
    locked = _locked()
    disagreements = []
    for spec in _declared():
        name, version = PIN.match(spec).groups()
        if locked.get(_normalise(name)) != version:
            disagreements.append(f"{spec} against {locked.get(_normalise(name), 'absent')}")
    assert not disagreements, f"pyproject and the lock disagree: {disagreements}"


def test_there_is_no_third_list_to_drift() -> None:
    assert not (ROOT / "requirements.txt").exists()
