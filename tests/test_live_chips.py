"""Swipe keeps fields out and names its sites without spelling out where they are.

Pure parts of the chip builder only; nothing here reaches the network.
"""

import importlib.util
import json
import re
import sys

from ml.paths import ROOT

_spec = importlib.util.spec_from_file_location(
    "live_build_chips", ROOT / "apps" / "live" / "pipeline" / "build_chips.py"
)
assert _spec is not None and _spec.loader is not None
chips = importlib.util.module_from_spec(_spec)
sys.modules["live_build_chips"] = chips
_spec.loader.exec_module(chips)

HEATLE = [{"centre": [86.40, 23.80], "answer": "coal mine"}]


def source(lon: float, lat: float, night: float | None) -> dict:
    return {"lon": lon, "lat": lat, "nightFraction": night}


def test_daytime_and_unmeasured_sites_never_reach_swipe() -> None:
    picked = chips.swipe_candidates(
        [source(80.0, 25.0, 0.9), source(81.0, 25.0, 0.2), source(82.0, 25.0, None)], HEATLE
    )
    assert len(picked) == 1
    assert picked[0]["lon"] == 80.0


def test_a_verified_heatle_site_becomes_a_gold_question() -> None:
    picked = chips.swipe_candidates([source(86.401, 23.801, 1.0), source(80.0, 25.0, 1.0)], HEATLE)
    assert [p["gold"] for p in picked] == ["factory", None]


def test_a_verified_flare_is_gold_for_the_flare_choice() -> None:
    flare = [{"centre": [72.0, 21.0], "answer": "gas flare"}]
    picked = chips.swipe_candidates([source(72.0, 21.0, 1.0)], flare)
    assert picked[0]["gold"] == "flare"


def test_item_ids_are_stable_and_carry_no_coordinates() -> None:
    a = chips.item_id(longitude=86.4, latitude=23.8)
    assert a == chips.item_id(longitude=86.4, latitude=23.8)
    assert a != chips.item_id(longitude=86.4, latitude=23.9)
    assert re.fullmatch(r"s[0-9a-f]{10}", a)


def test_a_site_only_on_swath_edge_tiles_is_still_searched(monkeypatch) -> None:
    queries = []

    class Empty:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self) -> bytes:
            return b'{"features": []}'

    def urlopen(request, timeout):
        queries.append(json.loads(request.data)["query"])
        return Empty()

    monkeypatch.setattr(chips.urllib.request, "urlopen", urlopen)
    assert chips.least_cloudy(longitude=80.0, latitude=25.0) == []
    assert all("s2:nodata_pixel_percentage" in q for q in queries[:-1])
    assert "s2:nodata_pixel_percentage" not in queries[-1]


def test_the_credit_names_each_year_once_in_order() -> None:
    credit = chips.credit_for(["2026-01-16", "2025-11-07", "2026-03-02"])
    assert credit == "Contains modified Copernicus Sentinel data 2025, 2026."
