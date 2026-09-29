"""The social kit's captions are templates filled from the feed and always carry credits."""

import importlib.util
import sys

import pytest

from ml.paths import ROOT

pytest.importorskip("matplotlib")
_spec = importlib.util.spec_from_file_location(
    "live_social_kit", ROOT / "apps" / "live" / "pipeline" / "social_kit.py"
)
assert _spec is not None and _spec.loader is not None
kit = importlib.util.module_from_spec(_spec)
sys.modules["live_social_kit"] = kit
_spec.loader.exec_module(kit)


def feed(polar, insat, pm25=None) -> dict:
    return {
        "evening_ist": "2026-10-20",
        "match": {"polar_share": polar, "insat_share": insat, "polar_last_seen_ist": "13:54"},
        "netu": [],
        "tomorrow": {"city": "Delhi", "pm25_24h_mean": pm25, "cpcb_category": "Poor"},
    }


def test_a_match_caption_reports_shares_and_credits() -> None:
    text = kit.caption(feed(0.2, 0.9, pm25=110.4))
    assert "20 percent" in text and "90 percent" in text
    assert "all out by 13:54" in text
    assert "PM2.5 forecast about 110" in text
    assert "Not an official count" in text or "not an official count" in text
    assert "MOSDAC/SAC/ISRO" in text and "ODbL" in text


def test_a_quiet_day_says_so_and_still_credits() -> None:
    text = kit.caption(feed(None, None))
    assert "quiet sky" in text
    assert "MOSDAC/SAC/ISRO" in text


def test_no_forecast_means_no_forecast_sentence() -> None:
    assert "PM2.5" not in kit.caption(feed(0.5, 0.5, pm25=None))
