"""Per-file publication; readers can see a mix of complete generations."""

import json
from pathlib import Path
from tempfile import NamedTemporaryFile

from .feed import season_stats, validate


def _atomic_write_utf8(destination: Path, text: str) -> None:
    temporary_path = None
    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(text)
        temporary_path.replace(destination)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def publish_feed(feed: dict, out_dir: Path, *, keep_latest: bool = False) -> None:
    """Preflight failures leave all published files unchanged, without generation rollback."""
    validate(feed)
    dated_path = out_dir / f"{feed['evening_ist']}.json"
    evenings = []
    for path in sorted(out_dir.glob("20??-??-??.json")):
        if path == dated_path:
            continue
        archived = json.loads(path.read_text(encoding="utf-8"))
        validate(archived)
        evenings.append(archived)
    evenings.append(feed)
    evenings.sort(key=lambda evening: evening["evening_ist"])

    text = json.dumps(feed, separators=(",", ":"), allow_nan=False)
    days_text = json.dumps([evening["evening_ist"] for evening in evenings], allow_nan=False)
    season_text = json.dumps(season_stats(evenings), separators=(",", ":"), allow_nan=False)

    out_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write_utf8(dated_path, text)
    if not keep_latest:
        _atomic_write_utf8(out_dir / "latest.json", text)
    _atomic_write_utf8(out_dir / "days.json", days_text)
    _atomic_write_utf8(out_dir / "season.json", season_text)
