from pathlib import Path

from ml.paths import DATA_DIR, ROOT, ensure_dir


def test_repo_root_contains_pyproject() -> None:
    assert (ROOT / "pyproject.toml").is_file()


def test_data_dir_is_under_root() -> None:
    assert DATA_DIR.parent == ROOT


def test_ensure_dir_is_idempotent(tmp_path: Path) -> None:
    target = tmp_path / "a" / "b"
    assert ensure_dir(target) == target
    assert ensure_dir(target) == target
    assert target.is_dir()
