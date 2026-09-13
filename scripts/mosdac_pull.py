"""Pull INSAT-3DS L1C granules, reduce each to India, and discard the granule.

Storage is not the constraint if the reduction is streamed. A granule is 24 MB, the
India window that matters is a few hundred detections, and keeping the granule
after it has been read buys nothing. Peak footprint is one file.

Bandwidth is the constraint. A day is 47 granules and 1.1 GB, and a full 61 day
burning season is 66 GB. Three days is enough to show whether the evening signal
exists, which is the decision this run exists to inform. D78.

Writes one npz of detections per granule under data/derived/insat/.
"""

import argparse
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml.fusion.detect import detect
from ml.fusion.granule import GranuleError, read_india
from ml.fusion.mosdac import (
    INSAT_3DS_L1C_ASIA,
    MissingCredentialsError,
    MosdacError,
    TokenSource,
    download,
    search,
)
from ml.paths import DATA_DIR, ENV_PATH, RAW_DIR, ensure_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2024-11-01", help="first date, YYYY-MM-DD")
    parser.add_argument("--days", type=int, default=3, help="consecutive days to pull")
    parser.add_argument("--keep", action="store_true", help="do not delete granules")
    parser.add_argument(
        "--slots",
        default=None,
        help="comma separated UTC HHMM slots to process; other slots found by search are "
        "skipped without a network call",
    )
    parser.add_argument(
        "--refetch-raw",
        action="store_true",
        help="download the raw granule even when its npz already exists, without rerunning "
        "detection or touching the npz; combine with --keep and --slots to retain specific "
        "raw granules for inspection",
    )
    return parser.parse_args()


def _slot(identifier: str) -> str:
    """Return the UTC HHMM slot embedded in a granule identifier."""
    return identifier.split("_")[2]


def main() -> int:
    args = parse_args()
    load_dotenv(ENV_PATH)

    out = ensure_dir(DATA_DIR / "derived" / "insat")
    staging = ensure_dir(RAW_DIR / "mosdac")
    first = date.fromisoformat(args.start)
    days = [first + timedelta(days=n) for n in range(args.days)]

    try:
        tokens = TokenSource(os.environ.get("MOSDAC_USERNAME"), os.environ.get("MOSDAC_PASSWORD"))
        tokens.get()
    except (MissingCredentialsError, MosdacError) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2

    requested_slots: set[str] | None = set(args.slots.split(",")) if args.slots else None

    # Retaining the raw granule is the whole point of refetching one whose npz already
    # exists. Without this the finally clause below deletes it the moment it lands, and
    # the "raw retained" line prints for a file that is already gone.
    args.keep = args.keep or args.refetch_raw

    total, kept, failed = 0, 0, 0
    for day in days:
        stamp = day.isoformat()
        try:
            granules = search(INSAT_3DS_L1C_ASIA, stamp, stamp)
        except MosdacError as exc:
            print(f"  {stamp}: search failed, {exc}", file=sys.stderr)
            failed += 1
            continue
        print(f"{stamp}: {len(granules)} granules")

        for granule in granules:
            if requested_slots is not None and _slot(granule.identifier) not in requested_slots:
                continue
            total += 1
            target = out / f"{granule.identifier.replace('.h5', '')}.npz"
            raw_only = target.exists() and args.refetch_raw
            if target.exists() and not raw_only:
                kept += 1
                continue

            local = staging / granule.identifier
            try:
                if not local.exists():
                    download(granule.granule_id, tokens, local)
                if raw_only:
                    kept += 1
                    print(f"  {granule.identifier[:34]}  raw retained, npz already present")
                    continue
                window = read_india(local)
                found = detect(window)
                np.savez_compressed(
                    target,
                    longitude=found.longitude,
                    latitude=found.latitude,
                    mir=found.mir,
                    diff=found.diff,
                    solar_zenith=found.solar_zenith,
                    valid_pixels=np.int64(found.valid_pixels),
                    acquired_utc=np.str_(window.acquired_utc.isoformat()),
                    hour_ist=np.int64(window.hour_ist),
                    minute_ist=np.int64(window.acquired_ist.minute),
                )
                kept += 1
                print(
                    f"  {granule.identifier[:34]}  {window.acquired_ist:%H:%M} IST  "
                    f"{len(found):4d} detections"
                )
            except (MosdacError, GranuleError, OSError) as exc:
                failed += 1
                print(f"  {granule.identifier[:34]}: {exc}", file=sys.stderr)
            finally:
                if local.exists() and not args.keep:
                    local.unlink()

    print(f"\n{kept} of {total} granules reduced, {failed} failed")
    print(f"written to {out}")
    return 0 if kept else 2


if __name__ == "__main__":
    raise SystemExit(main())
