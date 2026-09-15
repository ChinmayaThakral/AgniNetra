"""The two diurnal scripts must agree on what the evening window is.

A report that quotes a 49.5 percent evening share from one script beside a per state
share from another is only readable if both mean the same hours by evening. The
constants are defined twice because the scripts do not import each other, so the
agreement is asserted here rather than hoped for.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = (
    ROOT / "scripts" / "diurnal_profile.py",
    ROOT / "scripts" / "diurnal_by_region.py",
)


def _constants(path: Path) -> dict[str, str]:
    text = path.read_text()
    found = {}
    polar = re.search(r"^POLAR_HOURS.*?=\s*(\(.*?\))", text, re.MULTILINE)
    window = re.search(r"^EVENING_START,\s*EVENING_END\s*=\s*(.+)$", text, re.MULTILINE)
    assert polar, f"{path.name} does not define POLAR_HOURS"
    assert window, f"{path.name} does not define EVENING_START, EVENING_END"
    found["POLAR_HOURS"] = polar.group(1).replace(" ", "")
    found["EVENING"] = window.group(1).strip().replace(" ", "")
    return found


def test_both_scripts_define_the_same_windows() -> None:
    first, second = (_constants(p) for p in SCRIPTS)
    assert first == second, (
        f"{SCRIPTS[0].name} says {first} and {SCRIPTS[1].name} says {second}. "
        "Two scripts reporting different evening windows into one report is a defect."
    )


def test_the_evening_window_excludes_the_polar_overpass_hours() -> None:
    """The comparison is meaningless if the two ranges overlap."""
    values = _constants(SCRIPTS[0])
    start, end = (int(v) for v in values["EVENING"].split(","))
    polar = [int(v) for v in values["POLAR_HOURS"].strip("()").rstrip(",").split(",")]
    overlap = [h for h in polar if start <= h < end]
    assert not overlap, f"hours {overlap} are counted as both evening and polar overpass"
