"""Tests for the B4 support measurement and the catalogue parsing it depends on."""

import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from b4_support import _footprint_origin, _tiles_for_coverage

from ml.imagery.catalogue import _parse_footprint

SYNTHETIC_FOOTPRINT = (
    "POLYGON ((81.98629650407685 24.410215071618904, 81.97879719394643 23.41860543773055, "
    "83.05312159235007 23.40817882334798, 83.06884159555698 24.399291802536993, "
    "81.98629650407685 24.410215071618904))"
)


def test_footprint_prefix_is_stripped():
    raw = f"geography'SRID=4326;{SYNTHETIC_FOOTPRINT}'"
    assert _parse_footprint(raw) == SYNTHETIC_FOOTPRINT


def test_footprint_without_prefix_is_unchanged():
    assert _parse_footprint(SYNTHETIC_FOOTPRINT) == SYNTHETIC_FOOTPRINT


def test_missing_footprint_stays_none():
    assert _parse_footprint(None) is None


def test_origin_is_the_south_west_corner():
    lon, lat = _footprint_origin(SYNTHETIC_FOOTPRINT)
    assert lon == pytest.approx(81.97879719394643)
    assert lat == pytest.approx(23.40817882334798)


def test_coverage_counts_tiles_not_detections():
    tiles = Counter({(0, 0): 80, (1, 0): 15, (2, 0): 5})
    at_80, at_95 = _tiles_for_coverage(tiles)
    assert at_80 == 1
    assert at_95 == 2


def test_uniform_spread_needs_most_tiles():
    tiles = Counter({(i, 0): 10 for i in range(10)})
    at_80, at_95 = _tiles_for_coverage(tiles)
    assert at_80 == 8
    assert at_95 == 10


def _train_b4():
    import importlib.util
    import sys

    from ml.paths import ROOT

    spec = importlib.util.spec_from_file_location("train_b4", ROOT / "scripts" / "train_b4.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["train_b4"] = module
    spec.loader.exec_module(module)
    return module


def test_repeated_detections_at_one_site_count_once() -> None:
    """114 detections at two plants are two sites, not 114 independent chips. D124."""
    b4 = _train_b4()
    plant_a = [(82.721 + i * 0.0001, 24.131) for i in range(60)]
    plant_b = [(82.801, 24.191 + i * 0.0001) for i in range(54)]
    assert b4.distinct_sites(plant_a + plant_b) == 2


def test_the_floor_applies_to_sites_as_well_as_detections() -> None:
    b4 = _train_b4()
    spread = [(80.0 + i * 0.05, 20.0) for i in range(b4.MIN_CLASS_SUPPORT)]
    assert b4.distinct_sites(spread) == b4.MIN_CLASS_SUPPORT
