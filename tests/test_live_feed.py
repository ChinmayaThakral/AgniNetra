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
        "heatle": {
            "clues": [{"kind": "place", "centre": [75.55, 30.55]}],
            "answer": "coal mine",
            "choices": ["coal mine", "cannot tell"],
        },
        "attribution": [feed.MOSDAC_CREDIT + ". Test."],
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
        lambda f: f.update(attribution=["NASA FIRMS only"]),
        lambda f: f["cells"][0].update(centre=[75.5512, 30.5534]),
        lambda f: f["cells"][0].update(**{"class": "wildfire"}),
        lambda f: f["heatle"]["clues"][0].update(centre=[73.4678, 26.9272]),
        lambda f: f["heatle"].update(answer="a named company"),
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


def test_netu_says_only_insat_watches_when_it_saw_something_later() -> None:
    late = feed.build_match(
        [fire(75.55, 30.55, 8, 0, "polar"), fire(75.95, 30.95, 11, 30, "insat")]
    )
    early = feed.build_match(
        [fire(75.55, 30.55, 10, 30, "polar"), fire(75.95, 30.95, 10, 0, "insat")]
    )
    assert "only INSAT-3DS is watching" in feed.netu_lines(late, None, False)[0]["text"]
    assert all("only INSAT-3DS" not in line["text"] for line in feed.netu_lines(early, None, False))


def test_each_cell_carries_the_half_hour_it_was_first_seen(reference) -> None:
    fires = [fire(75.55, 30.55, 11, 40, "insat"), fire(75.56, 30.56, 8, 5, "polar")]
    cells = feed.build_cells(fires, reference, lambda **_: ("Punjab", "Ludhiana"))
    assert cells[0]["first_seen_ist"] == "13:30"


def test_validate_refuses_an_impossible_wind(reference) -> None:
    broken = _minimal_feed(reference)
    broken["wind"] = {"points": [[75.0, 30.0, [[12.0, 400]]]]}
    with pytest.raises(ValueError):
        feed.validate(broken)


def test_commentary_follows_each_over_and_never_runs_ahead_of_the_data() -> None:
    match = feed.build_match(
        [fire(75.55, 30.55, 8, 0, "polar"), fire(75.95, 30.95, 11, 0, "insat")]
    )
    lines = {line["over"]: line for line in feed.commentary(match, insat_newest_ist="17:00")}
    assert lines["16:00"]["template"] == "polar_in_pavilion"
    assert lines["16:30"]["template"] == "insat_up"
    assert lines["17:00"]["template"] == "maiden"
    assert lines["17:30"]["template"] == "not_yet"
    later = {line["over"]: line for line in feed.commentary(match, insat_newest_ist="19:30")}
    assert later["17:30"]["template"] == "maiden"
    assert [line["template"] for line in later.values()].count("polar_in_pavilion") == 1
    assert all(line["template"] in feed.COMMENTARY for line in lines.values())


def test_validate_refuses_commentary_outside_the_templates(reference) -> None:
    broken = _minimal_feed(reference)
    broken["commentary"] = [{"over": "16:00", "template": "hype", "text": "What a blaze!"}]
    with pytest.raises(ValueError):
        feed.validate(broken)


def test_a_past_evening_with_no_wind_still_validates(reference) -> None:
    ok = _minimal_feed(reference)
    ok["wind"] = None
    feed.validate(ok)


def test_the_app_schema_knows_every_template_the_pipeline_can_say() -> None:
    schema = (ROOT / "apps" / "live" / "web" / "src" / "schema.ts").read_text()
    for name in [*feed.TEMPLATES, *feed.COMMENTARY]:
        assert f'"{name}"' in schema, name


def test_day_mean_needs_every_hour_of_the_day() -> None:
    times = [f"2026-10-07T{h:02d}:00" for h in range(24)] + ["2026-10-08T00:00"]
    full: list[float | None] = [float(h) for h in range(24)] + [999.0]
    assert feed.day_mean(times, full, "2026-10-07") == 11.5
    gap = list(full)
    gap[5] = None
    assert feed.day_mean(times, gap, "2026-10-07") is None


@pytest.mark.parametrize(
    "air",
    [
        [{"city": "Gotham", "pm25_24h_mean": 50.0, "cpcb_category": "Satisfactory"}],
        [{"city": "Delhi", "pm25_24h_mean": 50.0, "cpcb_category": "Satisfactory"}] * 2,
        [{"city": "Delhi", "pm25_24h_mean": -1.0, "cpcb_category": None}],
        [{"city": "Delhi", "pm25_24h_mean": 50.0, "cpcb_category": "Hazardous"}],
    ],
)
def test_validate_refuses_city_air_it_cannot_vouch_for(reference, air) -> None:
    broken = _minimal_feed(reference)
    broken["air"] = air
    with pytest.raises(ValueError):
        feed.validate(broken)


def test_validate_accepts_every_city_with_values_not_measured(reference) -> None:
    ok = _minimal_feed(reference)
    ok["air"] = [
        {"city": name, "pm25_24h_mean": None, "cpcb_category": None}
        for name, _lon, _lat in feed.AIR_CITIES
    ]
    feed.validate(ok)


def _with_picture(reference, src: str, credit: bool) -> dict:
    f = _minimal_feed(reference)
    f["heatle"]["clues"].insert(0, {"kind": "image", "src": src, "span_km": 2.56})
    if credit:
        f["attribution"].append("Contains modified Copernicus Sentinel data 2026.")
    return f


def test_a_heatle_picture_is_one_of_the_apps_own_chips(reference) -> None:
    feed.validate(_with_picture(reference, "chips/s0123456789_close.webp", credit=True))
    with pytest.raises(ValueError):
        feed.validate(_with_picture(reference, "https://example.com/x.webp", credit=True))
    with pytest.raises(ValueError):
        feed.validate(_with_picture(reference, "chips/../feed/latest.json", credit=True))


def test_a_heatle_picture_travels_with_its_copernicus_credit(reference) -> None:
    with pytest.raises(ValueError):
        feed.validate(_with_picture(reference, "chips/s0123456789_close.webp", credit=False))


def _evening(day: str, insat: float | None, cells: list[dict], air: list[dict]) -> dict:
    return {
        "evening_ist": day,
        "match": {"insat_share": insat, "polar_share": None if insat is None else 1 - insat},
        "tomorrow": {"forecast_date": day},
        "cells": cells,
        "air": air,
    }


def test_the_season_counts_bad_air_days_and_the_fire_hour_near_each_city() -> None:
    near_delhi = {"centre": [77.25, 28.65], "evening": True, "first_seen_ist": "16:30"}
    far_away = {"centre": [88.35, 22.55], "evening": False, "first_seen_ist": "13:00"}
    poor = [{"city": "Delhi", "pm25_24h_mean": 100.0, "cpcb_category": "Poor"}]
    fine = [{"city": "Delhi", "pm25_24h_mean": 40.0, "cpcb_category": "Good"}]
    season = feed.season_stats(
        [
            _evening("2026-10-21", 0.6, [near_delhi, far_away], poor),
            _evening("2026-10-20", 0.4, [near_delhi], fine),
            _evening("2026-10-22", None, [], poor),
        ]
    )
    delhi = next(c for c in season["cities"] if c["city"] == "Delhi")
    assert delhi == {"city": "Delhi", "bad_air_days": 2, "cells_near": 2, "fire_hour_ist": "16:30"}
    assert season["first_evening"] == "2026-10-20" and season["evenings"] == 3
    assert season["insat_share_mean"] == 0.5
    assert season["evening_fire_cells"] == 2


def test_an_empty_season_has_nothing_to_report() -> None:
    season = feed.season_stats([])
    assert season["evenings"] == 0 and season["insat_share_mean"] is None
    assert all(c["fire_hour_ist"] is None for c in season["cities"])
