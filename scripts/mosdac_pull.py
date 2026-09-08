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
    return parser.parse_args()


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
            total += 1
            target = out / f"{granule.identifier.replace('.h5', '')}.npz"
            if target.exists():
                kept += 1
                continue

            local = staging / granule.identifier
            try:
                if not local.exists():
                    download(granule.granule_id, tokens, local)
                window = read_india(local)
                found = detect(window)
                np.savez_compressed(
                    target,
                    longitude=found.longitude,
                    latitude=found.latitude,
                    mir=found.mir,
                    diff=found.diff,
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
