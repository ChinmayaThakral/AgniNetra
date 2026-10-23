"""The social kit's captions are templates filled from the feed and always carry credits."""

import importlib.util
import sys
from types import SimpleNamespace

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


def feed(polar, insat, pm25=None, polar_last="13:54") -> dict:
    return {
        "evening_ist": "2026-10-20",
        "match": {"polar_share": polar, "insat_share": insat, "polar_last_seen_ist": polar_last},
        "netu": [],
        "tomorrow": {"city": "Delhi", "pm25_24h_mean": pm25, "cpcb_category": "Poor"},
    }


def test_a_match_caption_reports_shares_and_credits() -> None:
    text = kit.caption(feed(0.2, 0.9, pm25=110.4))
    assert "20 percent" in text and "90 percent" in text
    assert "Last polar fire detection in this feed: 13:54" in text
    assert "pass" not in text.lower()
    assert "afternoon" not in text.lower()
    assert "PM2.5 forecast about 110" in text
    assert "Not an official count" in text or "not an official count" in text
    assert "MOSDAC/SAC/ISRO" in text and "ODbL" in text


def test_an_empty_feed_reports_no_detections_and_still_credits() -> None:
    text = kit.caption(feed(None, None, polar_last=None))
    assert "No fire cells detected in this feed" in text
    assert "quiet sky" not in text.lower()
    assert "MOSDAC/SAC/ISRO" in text


def test_no_polar_detections_means_no_invented_afternoon_time() -> None:
    text = kit.caption(feed(0.0, 1.0, polar_last=None))
    assert "Last polar fire detection in this feed: none recorded" in text
    assert "afternoon" not in text.lower()
    assert "pass" not in text.lower()


@pytest.mark.parametrize("polar_last", ["19:40", None])
def test_story_reports_fire_detections_not_passes(monkeypatch, tmp_path, polar_last) -> None:
    lines = []
    figure = SimpleNamespace(savefig=lambda *args, **kwargs: None)
    monkeypatch.setattr(kit, "canvas", lambda *args: (figure, object()))
    monkeypatch.setattr(kit, "draw_netu", lambda *args: None)
    monkeypatch.setattr(kit, "text", lambda ax, x, y, text, *args: lines.append(text))
    monkeypatch.setattr(kit.plt, "close", lambda *args: None)
    kit.story(
        feed(0.0 if polar_last is None else 0.2, 1.0, polar_last=polar_last), tmp_path / "story.png"
    )
    text = " ".join(lines)
    if polar_last:
        assert f"Last polar fire detection in feed {polar_last}" in text
    else:
        assert "Last polar" not in text
    assert "pass" not in text.lower()
    assert "afternoon" not in text.lower()


def test_no_forecast_means_no_forecast_sentence() -> None:
    assert "PM2.5" not in kit.caption(feed(0.5, 0.5, pm25=None))
