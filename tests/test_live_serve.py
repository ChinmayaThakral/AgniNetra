"""The Live server builds on the evening schedule, never serves outside its folders, and
keeps no record of who visited."""

from datetime import datetime
from http.server import BaseHTTPRequestHandler
from pathlib import Path

import pytest

from apps.live import serve
from apps.live.pipeline.feed import IST


def at(hour: int, minute: int, day: int = 20) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=IST)


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (at(9, 0), at(16, 37)),
        (at(16, 37), at(17, 7)),
        (at(18, 10), at(18, 37)),
        (at(21, 40), at(23, 37)),
        (at(23, 50), at(16, 37, day=21)),
    ],
)
def test_the_next_build_is_the_first_scheduled_time_after_now(now, expected) -> None:
    assert serve.next_run(now) == expected


def test_a_time_in_another_zone_is_read_as_the_same_instant() -> None:
    utc_morning = datetime.fromisoformat("2026-10-20T03:30:00+00:00")
    assert serve.next_run(utc_morning) == at(16, 37)


@pytest.fixture
def routes(tmp_path: Path) -> tuple[tuple[str, Path], ...]:
    dist, feed, social = tmp_path / "dist", tmp_path / "feed", tmp_path / "social"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("app")
    (dist / "assets" / "app.js").write_text("js")
    feed.mkdir()
    (feed / "latest.json").write_text("{}")
    (social / "2026-10-20").mkdir(parents=True)
    (tmp_path / "secret.txt").write_text("outside")
    return (("/feed/", feed), ("/social/", social), ("/", dist))


def test_requests_reach_the_app_and_the_feed(routes) -> None:
    feed, dist = routes[0][1], routes[2][1]
    assert serve.resolve("/", routes) == (dist / "index.html").resolve()
    assert serve.resolve("/?wrapped", routes) == (dist / "index.html").resolve()
    assert serve.resolve("/assets/app.js", routes) == (dist / "assets" / "app.js").resolve()
    assert serve.resolve("/feed/latest.json", routes) == (feed / "latest.json").resolve()


def test_nothing_outside_the_served_folders_is_reachable(routes) -> None:
    for path in ("/../secret.txt", "/feed/../../secret.txt", "/%2e%2e/secret.txt", "/missing.js"):
        assert serve.resolve(path, routes) is None


def test_only_the_social_kit_lists_its_folders(routes, monkeypatch) -> None:
    social = routes[1][1]
    monkeypatch.setattr(serve, "LISTED", (social,))
    assert serve.resolve("/social/2026-10-20/", routes) == (social / "2026-10-20").resolve()
    assert serve.resolve("/feed/", routes) is None


def test_no_request_is_logged() -> None:
    assert serve.Handler.log_message is not BaseHTTPRequestHandler.log_message


def test_only_hashed_assets_are_cached_for_long() -> None:
    assert "immutable" in serve.cache_control("/assets/app-euDPXx79.js")
    for path in ("/", "/sw.js", "/feed/latest.json", "/chips/s1.webp"):
        assert serve.cache_control(path) == "no-cache"
