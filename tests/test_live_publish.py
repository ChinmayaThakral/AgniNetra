"""Publication checks use valid fixed feeds and temporary output directories only."""

import json
from collections.abc import Callable
from contextlib import ExitStack
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from apps.live.pipeline import feed, publish


def _evening(day: str = "2026-10-22", *, team: str = "insat") -> dict:
    reference = feed.Reference(
        {
            "attribution": ["test"],
            "osm": {"industrial": [], "flare": []},
            "gem": [],
            "cropland": [[755, 305, 50, 0.9]],
        },
        year=2026,
    )
    when = datetime.fromisoformat(day).replace(hour=11, tzinfo=UTC)
    fires = [feed.Fire(longitude=75.55, latitude=30.55, when_utc=when, team=team)]
    match = feed.build_match(fires)
    cells = feed.build_cells(fires, reference, lambda **_: ("Punjab", "Ludhiana"))
    return {
        "schema": feed.SCHEMA,
        "generated_utc": when.isoformat(),
        "evening_ist": day,
        "latency": {
            "insat_newest_utc": when.isoformat() if team == "insat" else None,
            "insat_delay_hours": 0.0 if team == "insat" else None,
            "polar_newest_utc": when.isoformat() if team == "polar" else None,
        },
        "cells": cells,
        "districts": feed.build_districts(cells),
        "match": match,
        "netu": feed.netu_lines(match, None, False),
        "commentary": feed.commentary(match, "16:30" if team == "insat" else None),
        "tomorrow": {
            "city": "Delhi",
            "forecast_date": str(date.fromisoformat(day) + timedelta(days=1)),
            "pm25_24h_mean": 100.0,
            "cpcb_category": "Poor",
            "evening_fire_cells": 1,
            "school_hybrid": "not measured",
            "source": "test",
        },
        "air": [
            {
                "city": "Delhi",
                "lon": 77.21,
                "lat": 28.61,
                "pm25_24h_mean": 100.0,
                "cpcb_category": "Poor",
            }
        ],
        "heatle": {
            "clues": [{"kind": "place", "centre": [75.55, 30.55]}],
            "answer": "coal mine",
            "choices": ["coal mine", "cannot tell"],
        },
        "wind": None,
        "attribution": [feed.MOSDAC_CREDIT + ". Test."],
        "caveats": list(feed.CAVEATS),
    }


@pytest.fixture
def candidate() -> dict:
    value = _evening()
    feed.validate(value)
    return value


def _snapshot(out_dir: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in out_dir.iterdir() if path.is_file()}


def _expected_outputs(candidate: dict, evenings: list[dict]) -> dict[str, bytes]:
    ordered = sorted(evenings, key=lambda evening: evening["evening_ist"])
    text = json.dumps(candidate, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return {
        f"{candidate['evening_ist']}.json": text,
        "latest.json": text,
        "days.json": json.dumps(
            [evening["evening_ist"] for evening in ordered], allow_nan=False
        ).encode("utf-8"),
        "season.json": json.dumps(
            feed.season_stats(ordered), separators=(",", ":"), allow_nan=False
        ).encode("utf-8"),
    }


class _CheckedTemporary:
    def __init__(self, handle, *, observe: Callable[[], None] | None = None, failure=None):
        self.handle = handle
        self.name = handle.name
        self.observe = observe
        self.failure = failure

    def __enter__(self):
        self.handle.__enter__()
        return self

    def write(self, text):
        midpoint = len(text) // 2
        self.handle.write(text[:midpoint])
        self.handle.flush()
        if self.observe:
            self.observe()
        if self.failure == "write":
            raise OSError("injected write failure")
        self.handle.write(text[midpoint:])
        self.handle.flush()
        if self.observe:
            self.observe()
        return len(text)

    def __exit__(self, exc_type, exc_value, traceback):
        result = self.handle.__exit__(exc_type, exc_value, traceback)
        if self.observe:
            self.observe()
        if self.failure == "close":
            raise OSError("injected close failure")
        return result


def test_valid_outputs_include_the_sorted_candidate_overlay(
    candidate: dict, tmp_path: Path
) -> None:
    out_dir = tmp_path / "nested" / "feed"
    out_dir.mkdir(parents=True)
    archives = [_evening("2026-10-23"), _evening("2026-10-21")]
    for archived in archives:
        feed.validate(archived)
        (out_dir / f"{archived['evening_ist']}.json").write_text(
            json.dumps(archived), encoding="utf-8"
        )
    (out_dir / "unrelated.json").write_text("not a feed", encoding="utf-8")

    publish.publish_feed(candidate, out_dir)

    for name, expected in _expected_outputs(candidate, [*archives, candidate]).items():
        assert (out_dir / name).read_bytes() == expected
    feed.validate(json.loads((out_dir / "latest.json").read_text(encoding="utf-8")))
    assert json.loads((out_dir / "days.json").read_text(encoding="utf-8")) == [
        "2026-10-21",
        "2026-10-22",
        "2026-10-23",
    ]
    assert not list(out_dir.glob("*.tmp"))


def test_publication_creates_a_missing_output_directory(candidate: dict, tmp_path: Path) -> None:
    out_dir = tmp_path / "nested" / "feed"
    publish.publish_feed(candidate, out_dir)
    assert _snapshot(out_dir) == _expected_outputs(candidate, [candidate])


@pytest.mark.parametrize("damaged_same_date", [False, True])
def test_same_date_rebuild_does_not_read_or_doublecount_the_old_candidate(
    candidate: dict, tmp_path: Path, damaged_same_date: bool
) -> None:
    publish.publish_feed(candidate, tmp_path)
    if damaged_same_date:
        (tmp_path / "2026-10-22.json").write_text("{incomplete", encoding="utf-8")
    replacement = _evening(team="polar")

    publish.publish_feed(replacement, tmp_path)

    assert _snapshot(tmp_path) == _expected_outputs(replacement, [replacement])
    season = json.loads((tmp_path / "season.json").read_text(encoding="utf-8"))
    assert season["evenings"] == 1
    assert season["evening_fire_cells"] == 1
    assert season["insat_share_mean"] == 0.0


def test_keep_latest_preserves_its_exact_bytes(candidate: dict, tmp_path: Path) -> None:
    publish.publish_feed(candidate, tmp_path)
    latest = (json.dumps(candidate, indent=2) + "\n").encode("utf-8")
    (tmp_path / "latest.json").write_bytes(latest)
    past = _evening("2026-10-21", team="polar")

    publish.publish_feed(past, tmp_path, keep_latest=True)

    expected = _expected_outputs(past, [past, candidate])
    expected["latest.json"] = latest
    expected["2026-10-22.json"] = json.dumps(
        candidate, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    assert _snapshot(tmp_path) == expected


def test_keep_latest_does_not_create_a_missing_latest(candidate: dict, tmp_path: Path) -> None:
    publish.publish_feed(candidate, tmp_path, keep_latest=True)
    expected = _expected_outputs(candidate, [candidate])
    del expected["latest.json"]
    assert _snapshot(tmp_path) == expected


@pytest.mark.parametrize("keep_latest", [False, True])
def test_readers_only_see_complete_files_during_writes_and_replacements(
    candidate: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, keep_latest: bool
) -> None:
    publish.publish_feed(candidate, tmp_path)
    before = _snapshot(tmp_path)
    replacement = _evening(team="polar")
    after = _expected_outputs(replacement, [replacement])
    if keep_latest:
        after["latest.json"] = before["latest.json"]
    real_temporary = publish.NamedTemporaryFile
    real_replace = Path.replace
    handles = []
    temporary_names = []
    published = []
    observations = []

    def observe():
        for name in before:
            current = (tmp_path / name).read_bytes()
            assert current in (before[name], after[name])
            json.loads(current)
        assert [path.name for path in tmp_path.glob("20??-??-??.json")] == ["2026-10-22.json"]
        observations.append(True)

    def open_temporary(**kwargs):
        assert kwargs["encoding"] == "utf-8"
        assert kwargs["dir"] == tmp_path
        assert kwargs["suffix"] == ".tmp"
        handle = real_temporary(**kwargs)
        handles.append(handle)
        temporary_names.append(handle.name)
        assert Path(handle.name).parent == tmp_path
        assert Path(handle.name).suffix == ".tmp"
        return _CheckedTemporary(handle, observe=observe)

    def replace(source, destination):
        assert handles[-1].closed
        assert Path(source).read_bytes() == after[Path(destination).name]
        assert Path(destination).read_bytes() == before[Path(destination).name]
        observe()
        result = real_replace(source, destination)
        published.append(Path(destination).name)
        assert Path(destination).read_bytes() == after[Path(destination).name]
        observe()
        return result

    monkeypatch.setattr(publish, "NamedTemporaryFile", open_temporary)
    monkeypatch.setattr(Path, "replace", replace)
    with ExitStack() as stack:
        readers = {name: stack.enter_context((tmp_path / name).open("rb")) for name in before}
        publish.publish_feed(replacement, tmp_path, keep_latest=keep_latest)
        assert {name: reader.read() for name, reader in readers.items()} == before

    assert published == [
        "2026-10-22.json",
        *([] if keep_latest else ["latest.json"]),
        "days.json",
        "season.json",
    ]
    assert len(set(temporary_names)) == len(published)
    assert observations
    assert _snapshot(tmp_path) == after


@pytest.mark.parametrize("failure", ["write", "close", "replace"])
@pytest.mark.parametrize("existing", [False, True])
def test_atomic_failures_clean_up_and_preserve_the_affected_destination(
    candidate: dict,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
    existing: bool,
) -> None:
    if existing:
        publish.publish_feed(candidate, tmp_path)
    before = _snapshot(tmp_path)
    real_temporary = publish.NamedTemporaryFile
    handles = []

    def open_temporary(**kwargs):
        handle = real_temporary(**kwargs)
        handles.append(handle)
        return _CheckedTemporary(handle, failure=failure)

    def replace(source, destination):
        assert handles[-1].closed
        raise OSError("injected replace failure")

    monkeypatch.setattr(publish, "NamedTemporaryFile", open_temporary)
    if failure == "replace":
        monkeypatch.setattr(Path, "replace", replace)

    with pytest.raises(OSError, match=f"injected {failure} failure"):
        publish.publish_feed(_evening(team="polar"), tmp_path)

    assert handles and all(handle.closed for handle in handles)
    assert _snapshot(tmp_path) == before


@pytest.mark.parametrize(
    ("failure", "error"),
    [
        ("candidate", ValueError),
        ("archive_json", ValueError),
        ("archive_feed", ValueError),
        ("archive_read", OSError),
        ("aggregation", RuntimeError),
        ("candidate_nan", ValueError),
        ("candidate_type", TypeError),
        ("days_serialization", TypeError),
        ("season_serialization", ValueError),
    ],
)
def test_preflight_failures_happen_before_any_publication(
    candidate: dict,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
    error: type[Exception],
) -> None:
    archive = _evening("2026-10-21")
    publish.publish_feed(archive, tmp_path)
    publish.publish_feed(candidate, tmp_path)
    archive_path = tmp_path / "2026-10-21.json"
    replacement = _evening(team="polar")

    if failure == "candidate":
        replacement["cells"][0]["how_sure"] = "high"
    elif failure == "archive_json":
        archive_path.write_text("{incomplete", encoding="utf-8")
    elif failure == "archive_feed":
        archive["cells"][0]["how_sure"] = "high"
        archive_path.write_text(json.dumps(archive), encoding="utf-8")
    elif failure == "archive_read":
        real_read = Path.read_text

        def read_text(path, *args, **kwargs):
            if path == archive_path:
                raise OSError("injected archive read failure")
            return real_read(path, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", read_text)
    elif failure == "aggregation":

        def aggregate(evenings):
            raise RuntimeError("injected aggregation failure")

        monkeypatch.setattr(publish, "season_stats", aggregate)
    elif failure == "candidate_nan":
        replacement["nonfinite"] = float("nan")
    elif failure == "candidate_type":
        replacement["not_json"] = object()
    elif failure == "days_serialization":
        real_dumps = json.dumps

        def dumps(value, *args, **kwargs):
            if isinstance(value, list):
                raise TypeError("injected days serialization failure")
            return real_dumps(value, *args, **kwargs)

        monkeypatch.setattr(publish.json, "dumps", dumps)
    elif failure == "season_serialization":
        real_stats = feed.season_stats

        def nonfinite_stats(evenings):
            return {**real_stats(evenings), "insat_share_mean": float("inf")}

        monkeypatch.setattr(publish, "season_stats", nonfinite_stats)

    before = _snapshot(tmp_path)

    def unexpected_publication(*args, **kwargs):
        raise AssertionError("publication started before preflight finished")

    monkeypatch.setattr(publish, "NamedTemporaryFile", unexpected_publication)
    monkeypatch.setattr(Path, "replace", unexpected_publication)

    with pytest.raises(error):
        publish.publish_feed(replacement, tmp_path)

    assert _snapshot(tmp_path) == before


@pytest.mark.parametrize("failed_position", [2, 3, 4])
def test_midpublication_failure_leaves_mixed_complete_generations_without_rollback(
    candidate: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failed_position: int
) -> None:
    publish.publish_feed(candidate, tmp_path)
    before = _snapshot(tmp_path)
    replacement = _evening("2026-10-23", team="polar")
    after = _expected_outputs(replacement, [candidate, replacement])
    real_replace = Path.replace
    attempted = []
    completed = []

    def replace(source, destination):
        attempted.append(Path(destination).name)
        if len(attempted) == failed_position:
            raise OSError("injected midpublication failure")
        result = real_replace(source, destination)
        completed.append(Path(destination).name)
        return result

    monkeypatch.setattr(Path, "replace", replace)

    with pytest.raises(OSError, match="injected midpublication failure"):
        publish.publish_feed(replacement, tmp_path)

    assert (
        attempted
        == ["2026-10-23.json", "latest.json", "days.json", "season.json"][:failed_position]
    )
    assert _snapshot(tmp_path) == {**before, **{name: after[name] for name in completed}}
    for value in _snapshot(tmp_path).values():
        json.loads(value)
