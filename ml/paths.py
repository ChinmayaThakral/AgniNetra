"""Single resolver for every path the project reads or writes.

No absolute path appears anywhere else in the source. Every path is derived from
the repository root, which is located by walking up from this file until a
directory containing pyproject.toml is found.
"""

from pathlib import Path


def repo_root() -> Path:
    """Return the repository root.

    Raises RuntimeError if pyproject.toml is not found in any parent, which means
    the package has been installed somewhere detached from the repository.
    """
    for candidate in [Path(__file__).resolve(), *Path(__file__).resolve().parents]:
        if (candidate / "pyproject.toml").is_file():
            return candidate
    raise RuntimeError("repository root not found: no pyproject.toml in any parent directory")


ROOT = repo_root()

DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
REFERENCE_DIR = DATA_DIR / "reference"
EXPORT_DIR = DATA_DIR / "export"

ARTIFACT_DIR = ROOT / "ml" / "artifacts"
FIGURE_DIR = ROOT / "docs" / "figures"

DUCKDB_PATH = DATA_DIR / "agninetra.duckdb"
ENV_PATH = ROOT / ".env"


def ensure_dir(path: Path) -> Path:
    """Create the directory if absent and return it, so callers can chain."""
    path.mkdir(parents=True, exist_ok=True)
    return path
