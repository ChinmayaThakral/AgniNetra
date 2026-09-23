"""The background rates a weak label lift divides by, read from their measurement.

Lift is a class's labelled share over the share a detection placed uniformly inside
India would pick up. Three scripts carried the industrial background as a typed copy,
0.0175, which is the OpenStreetMap only rate, while the label of record also matches
GEM assets. Every with GEM lift therefore divided a GEM inclusive share by a GEM
exclusive background and read high. The rate is now read from the artifact
`scripts/label_radius_sensitivity.py` writes, per window year because GEM assets are
gated by operating year. D122.
"""

import json
from functools import cache

from ml.paths import ARTIFACT_DIR

ARTIFACT = ARTIFACT_DIR / "label_background.json"


class BackgroundMissingError(FileNotFoundError):
    """The background artifact has not been generated."""


@cache
def _load() -> dict:
    if not ARTIFACT.is_file():
        raise BackgroundMissingError(
            f"{ARTIFACT.name} is absent. Run scripts/label_radius_sensitivity.py first."
        )
    return json.loads(ARTIFACT.read_text())


def industrial_background(*, year: int | None, with_gem: bool = True) -> float:
    """Share of uniform probes within the industrial radius, for one definition."""
    data = _load()
    if not with_gem:
        return float(data["industrial_osm"])
    if year is None:
        raise ValueError("the GEM inclusive background depends on the operating year")
    return float(data["industrial_with_gem_by_year"][str(year)])


def flare_background() -> float:
    return float(_load()["flare"])


def weighted_industrial_background(year_shares: dict[int, float]) -> float:
    """The GEM inclusive background for a population spread over several years."""
    total = sum(year_shares.values())
    return sum(
        share / total * industrial_background(year=year) for year, share in year_shares.items()
    )
