"""The single enumeration every guard uses.

A guard that names the files it checks only ever catches the instance it was
written for. `tests/test_no_fabricated_missing.py` listed two paths, being the two
where the D61 defect had already been found, so the same defect in
`scripts/conformal_aoa_b2.py` and `scripts/export_console.py` was invisible to it.

Guards enumerate tracked files here and exempt by exact path, never by omission.
An exemption is a decision with a name on it; a file a guard simply never looked at
is not.
"""

import subprocess
from pathlib import Path

from ml.paths import ROOT


class TrackedFilesError(RuntimeError):
    """Raised when git cannot enumerate the working tree."""


def tracked_files(suffixes: tuple[str, ...] | None = None) -> list[Path]:
    """Return every file git tracks, optionally filtered by suffix.

    Raises TrackedFilesError rather than returning an empty list when git fails,
    because a guard that silently scans nothing reports clean.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise TrackedFilesError(f"git ls-files failed: {exc}") from exc

    paths = [ROOT / line for line in result.stdout.splitlines() if line]
    if not paths:
        raise TrackedFilesError("git ls-files returned nothing, refusing to report clean")
    if suffixes is not None:
        paths = [p for p in paths if p.suffix in suffixes]
    return sorted(paths)


def relative(path: Path) -> str:
    return str(path.relative_to(ROOT))
