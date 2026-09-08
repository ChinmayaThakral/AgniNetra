"""Phase 5 gate: download one INSAT-3DS L1B granule and confirm it opens.

`context/phases/PHASE_5.md` requires this before any other code in the phase, so
that a format or access problem surfaces in an hour rather than after a collocation
pipeline is built against an assumption.

The granule chosen is 11:30 UTC, which is 17:00 IST, the half hour in which the
polar orbiting record carries zero detections across both burning seasons. If
geostationary observation shows activity there, that is the phase 5 result in one
file.

Credentials come from `.env` and are never read, printed or logged by this script.
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml.fusion.mosdac import (
    INSAT_3DS_L1B,
    MissingCredentialsError,
    MosdacError,
    TokenSource,
    download,
    search,
)
from ml.paths import ENV_PATH, RAW_DIR, ensure_dir

TARGET_DATE = "2024-11-01"
TARGET_SLOT = "_1130_"


def main() -> int:
    load_dotenv(ENV_PATH)

    try:
        granules = search(INSAT_3DS_L1B, TARGET_DATE, TARGET_DATE)
    except MosdacError as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2
    print(f"granules on {TARGET_DATE}: {len(granules)}")

    wanted = [g for g in granules if TARGET_SLOT in g.identifier]
    if not wanted:
        print(f"BLOCKED: no granule matching {TARGET_SLOT}", file=sys.stderr)
        return 2
    granule = wanted[0]
    print(f"target: {granule.identifier}  id {granule.granule_id}")

    destination = ensure_dir(RAW_DIR / "mosdac") / granule.identifier
    if destination.exists():
        print(f"already present, {destination.stat().st_size / 1e6:.0f} MB")
    else:
        try:
            tokens = TokenSource(
                os.environ.get("MOSDAC_USERNAME"), os.environ.get("MOSDAC_PASSWORD")
            )
        except MissingCredentialsError as exc:
            print(f"BLOCKED: {exc}", file=sys.stderr)
            return 2
        except MosdacError as exc:
            print(f"BLOCKED: {exc}", file=sys.stderr)
            return 2
        print("downloading")
        written = download(granule.granule_id, tokens, destination)
        print(f"wrote {written / 1e6:.0f} MB")

    import h5py

    with h5py.File(destination, "r") as handle:
        datasets: list[str] = []
        handle.visit(lambda name: datasets.append(name))
        print(f"\nopened. objects in file: {len(datasets)}")
        print("root attributes:")
        for key in list(handle.attrs)[:12]:
            value = handle.attrs[key]
            print(f"  {key}: {str(value)[:70]}")
        print("datasets:")
        for name in datasets[:20]:
            node = handle[name]
            if hasattr(node, "shape"):
                print(f"  {name:34s} {node.shape!s:20s} {node.dtype}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
