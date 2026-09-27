"""The Live feed keeps the app's promises on fixed inputs, with no network.

Each test names the rule it holds: cells never points, shares never counts, templates
never free text, and no weak label stated as high confidence.
"""

import importlib.util
import sys
from datetime import UTC, datetime

import pytest

from ml.paths import ROOT

_spec = importlib.util.spec_from_file_location(
    "live_feed", ROOT / "apps" / "live" / "pipeline" / "feed.py"
)
assert _spec is not None and _spec.loader is not None
feed = importlib.util.module_from_spec(_spec)
sys.modules["live_feed"] = feed
_spec.loader.exec_module(feed)

PACK = {
    "attribution": ["test"],
    "osm": {"industrial": [[82.70, 24.10]], "flare": [[72.90, 21.60]]},
    "gem": [[86.40, 23.80, "coal_mine", 2030, None]],
    "cropland": [[755, 305, 50, 0.9], [760, 300, 5, 0.6]],
}


def utc(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, 1, hour, minute, tzinfo=UTC)


def fire(lon: float, lat: float, hour: int, minute: int, team: str):
    return feed.Fire(longitude=lon, latitude=lat, when_utc=utc(hour, minute), team=team)


@pytest.fixture
def reference():
    return feed.Reference(PACK, year=2026)


def test_a_fire_near_an_industrial_point_seen_by_a_polar_pixel_is_medium(reference) -> None:
    fires = [fire(82.702, 24.101, 8, 0, "polar")]
    assert feed.classify_cell(fires, reference, (827, 241)) == ("industrial", "medium")


def test_the_same_cell_seen_only_by_insat_is_low(reference) -> None:
    fires = [fire(82.702, 24.101, 11, 0, "insat")]
    assert feed.classify_cell(fires, reference, (827, 241)) == ("industrial", "low")


def test_a_gem_asset_not_yet_built_labels_nothing(reference) -> None:
    fires = [fire(86.401, 23.801, 8, 0, "polar")]
    assert feed.classify_cell(fires, reference, (864, 238))[0] == "unclassified"


def test_cropland_share_decides_agricultural_and_its_confidence(reference) -> None:
    rich = feed.classify_cell([fire(75.55, 30.55, 11, 0, "insat")], reference, (755, 305))
    thin = feed.classify_cell([fire(76.05, 30.05, 11, 0, "insat")], reference, (760, 300))
    assert rich == ("agricultural", "medium")
    assert thin == ("agricultural", "low")


def test_the_match_is_shares_and_the_polar_team_is_all_out() -> None:
    fires = [
        fire(75.55, 30.55, 8, 0, "polar"),  # 13:30 IST
        fire(75.55, 30.55, 11, 0, "insat"),  # 16:30 IST, same cell
        fire(75.95, 30.95, 11, 30, "insat"),  # 17:00 IST, a new cell
    ]
    match = feed.build_match(fires)
    assert match["polar_share"] == 0.5
    assert match["insat_share"] == 1.0
    assert match["polar_last_seen_ist"] == "13:30"
    over_1700 = next(o for o in match["overs"] if o["over"] == "17:00")
    assert over_1700 == {
        "over": "17:00",
        "polar_share": 0.5,
        "insat_share": 1.0,
        "polar_new": False,
        "insat_new": True,
    }


def test_fires_outside_the_match_window_do_not_score() -> None:
    fires = [fire(75.55, 30.55, 20, 0, "polar")]  # 01:30 IST
    assert feed.build_match(fires)["polar_share"] is None


def test_cells_are_never_points(reference) -> None:
    fires = [fire(75.5512, 30.5534, 11, 0, "insat")]
    cells = feed.build_cells(fires, reference, lambda **_: ("Punjab", "Ludhiana"))
    assert cells[0]["centre"] == [75.55, 30.55]
    assert 75.5512 not in cells[0]["centre"]


def test_netu_only_speaks_in_templates() -> None:
    match = feed.build_match([fire(75.55, 30.55, 11, 0, "insat")])
    for line in feed.netu_lines(match, insat_delay_hours=72, heavy=True):
        assert line["template"] in feed.TEMPLATES
    assert any("3 days ago" in line["text"] for line in feed.netu_lines(match, 72, False))


def test_pm25_uses_the_cpcb_breakpoints() -> None:
    assert feed.pm25_category(60) == "Satisfactory"
    assert feed.pm25_category(60.1) == "Moderate"
    assert feed.pm25_category(251) == "Severe"
    assert feed.pm25_category(None) is None


def _minimal_feed(reference) -> dict:
    fires = [fire(75.55, 30.55, 11, 0, "insat")]
    match = feed.build_match(fires)
    return {
        "schema": feed.SCHEMA,
        "cells": feed.build_cells(fires, reference, lambda **_: ("Punjab", "Ludhiana")),
        "match": match,
        "netu": feed.netu_lines(match, None, False),
        "attribution": ["x"],
        "caveats": list(feed.CAVEATS),
    }


def test_validate_passes_a_well_formed_feed(reference) -> None:
    feed.validate(_minimal_feed(reference))


@pytest.mark.parametrize(
    "breakage",
    [
        lambda f: f["cells"][0].update(how_sure="high"),
        lambda f: f["cells"][0].update(longitude=75.5512),
        lambda f: f["match"].update(insat_share=3),
        lambda f: f["netu"].append({"template": "freeform", "text": "farmers are to blame"}),
        lambda f: f.update(attribution=[]),
    ],
)
def test_validate_refuses_a_feed_that_breaks_a_rule(reference, breakage) -> None:
    broken = _minimal_feed(reference)
    breakage(broken)
    with pytest.raises(ValueError):
        feed.validate(broken)


def test_a_district_with_no_state_polygon_does_not_break_the_summary(reference) -> None:
    fires = [fire(75.55, 30.55, 11, 0, "insat"), fire(76.55, 30.55, 11, 0, "insat")]
    lookup = iter([("Punjab", "Ludhiana"), (None, "Border district")])
    cells = feed.build_cells(fires, reference, lambda **_: next(lookup))
    names = [d["district"] for d in feed.build_districts(cells)]
    assert names == ["Border district", "Ludhiana"]


def test_fires_outside_india_are_dropped_before_scoring() -> None:
    india = fire(75.55, 30.55, 11, 0, "insat")
    pakistan = fire(72.05, 30.05, 11, 0, "insat")

    def locate(*, longitude: float, latitude: float):
        return ("Punjab", "Ludhiana") if longitude > 74 else (None, None)

    kept, _ = feed.restrict_to_india([india, pakistan], locate)
    assert kept == [india]
    assert feed.build_match(kept)["insat_share"] == 1.0


def test_netu_says_still_batting_only_when_insat_caught_something_later() -> None:
    late = feed.build_match(
        [fire(75.55, 30.55, 8, 0, "polar"), fire(75.95, 30.95, 11, 30, "insat")]
    )
    early = feed.build_match(
        [fire(75.55, 30.55, 10, 30, "polar"), fire(75.95, 30.95, 10, 0, "insat")]
    )
    assert "still batting" in feed.netu_lines(late, None, False)[0]["text"]
    assert all("still batting" not in line["text"] for line in feed.netu_lines(early, None, False))


def test_each_cell_carries_the_half_hour_it_was_first_seen(reference) -> None:
    fires = [fire(75.55, 30.55, 11, 40, "insat"), fire(75.56, 30.56, 8, 5, "polar")]
    cells = feed.build_cells(fires, reference, lambda **_: ("Punjab", "Ludhiana"))
    assert cells[0]["first_seen_ist"] == "13:30"


def test_validate_refuses_an_impossible_wind(reference) -> None:
    broken = _minimal_feed(reference)
    broken["wind"] = {"points": [[75.0, 30.0, [[12.0, 400]]]]}
    with pytest.raises(ValueError):
        feed.validate(broken)
