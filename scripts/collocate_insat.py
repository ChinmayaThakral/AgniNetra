"""Match INSAT-3DS detections against the polar orbiting record, in space and time.

Two instruments disagreeing is not evidence against either until the disagreement is
measured. INSAT-3DS sees a 4 km pixel every 30 minutes; VIIRS sees 375 m twice a day.
A fire small enough to sit inside one INSAT pixel without lifting its brightness
temperature is invisible to the geostationary sensor and obvious to the polar one, so
a low match rate is the expected result and not a defect. What the match rate is for
is calibrating how much of the polar record the geostationary sensor can reproduce at
the moments both are looking, which is the only basis for trusting it at the moments
only one is.

The tolerance is swept rather than assumed, because a single radius quoted without the
curve beside it cannot be sized by a reader. D82.
"""

import argparse
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml.paths import DATA_DIR

EARTH_RADIUS_M = 6371008.8

# Half the 30 minute granule cadence, so every polar detection falls to exactly one
# granule and none is counted twice.
TIME_TOLERANCE = timedelta(minutes=15)

RADII_M = (2000.0, 4000.0, 6000.0, 8000.0, 10000.0, 15000.0)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2024-11-01")
    parser.add_argument("--end", default="2024-11-03")
    return parser.parse_args()


def _haversine_m(
    lat1: np.ndarray, lon1: np.ndarray, lat2: np.ndarray, lon2: np.ndarray
) -> np.ndarray:
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp = p2 - p1
    dl = np.radians(lon2 - lon1)
    a = np.sin(dp / 2.0) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2.0) ** 2
    return 2.0 * EARTH_RADIUS_M * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def _load_insat(source: Path) -> list[tuple[datetime, np.ndarray, np.ndarray]]:
    """One entry per granule: acquisition time, latitudes, longitudes."""
    granules = []
    for path in sorted(source.glob("*.npz")):
        with np.load(path, allow_pickle=False) as data:
            when = datetime.fromisoformat(str(data["acquired_utc"]))
            granules.append((when, data["latitude"].copy(), data["longitude"].copy()))
    return granules


def main() -> int:
    args = parse_args()
    source = DATA_DIR / "derived" / "insat"
    granules = _load_insat(source)
    if not granules:
        print(f"BLOCKED: no reduced granules in {source}", file=sys.stderr)
        return 2

    con = duckdb.connect(str(DATA_DIR / "agninetra.duckdb"), read_only=True)
    rows = con.execute(
        """
        select latitude, longitude, acq_ts_utc, instrument
        from detections
        where acq_date_ist between ? and ?
        order by detection_id
        """,
        [args.start, args.end],
    ).fetchall()
    con.close()
    if not rows:
        print("BLOCKED: no polar detections in that window", file=sys.stderr)
        return 2

    p_lat = np.array([r[0] for r in rows], dtype=np.float64)
    p_lon = np.array([r[1] for r in rows], dtype=np.float64)
    # DuckDB hands back a TIMESTAMPTZ rendered in the session zone, IST here, so it
    # arrives as 13:11+05:30 rather than 07:41+00:00. Stripping the offset instead of
    # converting would compare an IST wall clock against the granule's UTC one and put
    # every match 5 hours 30 minutes out, which still finds a granule within the time
    # tolerance and quietly matches the wrong half of the day.
    p_when = [r[2].astimezone(UTC) for r in rows]
    p_inst = np.array([r[3] for r in rows])

    times = np.array([g[0].astimezone(UTC) for g in granules])
    insat_total = sum(len(g[1]) for g in granules)
    print(f"INSAT granules {len(granules)}, detections {insat_total}")
    print(f"polar detections {len(rows)} over {args.start} to {args.end}")
    print()

    # Every polar detection that has a granule within the time tolerance. The rest are
    # unmatchable by construction, not unmatched, and are reported apart from the rate.
    nearest = []
    for when in p_when:
        gaps = np.abs(times - when)
        j = int(np.argmin(gaps))
        nearest.append(j if gaps[j] <= TIME_TOLERANCE else -1)
    nearest_arr = np.array(nearest)
    covered = nearest_arr >= 0
    print(f"polar detections with a granule within {TIME_TOLERANCE}: {int(covered.sum())}")
    print(f"outside any granule's time window: {int((~covered).sum())}")
    print()

    print("  radius m   polar matched   rate    by instrument")
    for radius in RADII_M:
        matched = np.zeros(len(rows), dtype=bool)
        for j in range(len(granules)):
            idx = np.nonzero(covered & (nearest_arr == j))[0]
            if idx.size == 0:
                continue
            _, g_lat, g_lon = granules[j]
            if g_lat.size == 0:
                continue
            for k in idx:
                d = _haversine_m(p_lat[k], p_lon[k], g_lat, g_lon)
                if d.min() <= radius:
                    matched[k] = True
        n_cov = int(covered.sum())
        rate = 100.0 * matched.sum() / n_cov if n_cov else 0.0
        per = []
        for inst in ("VIIRS", "MODIS"):
            m = covered & (p_inst == inst)
            if m.sum():
                per.append(f"{inst} {100.0 * (matched & m).sum() / m.sum():.1f}%")
        print(f"  {radius:8.0f}   {int(matched.sum()):13d}  {rate:5.1f}%    {'  '.join(per)}")

    # The reverse direction, which is the one that says whether an INSAT detection is
    # real. It is only askable where a polar satellite was actually overhead, and swath
    # geometry is not in the detection table, so presence of any polar detection within
    # NEARBY_M of the same granule stands in for coverage. That is a proxy: it counts a
    # region as observed when the swath clipped it, and it cannot tell an empty swath
    # from no swath. Reported separately from the rate above for that reason.
    nearby_m = 200000.0
    print()
    print("  INSAT detections corroborated by a polar detection, where the swath was")
    print(f"  within {nearby_m / 1000:.0f} km of the same granule")
    print()
    print("  radius m   checkable   corroborated   rate")
    for radius in RADII_M:
        checkable = 0
        hit = 0
        for j, (_, g_lat, g_lon) in enumerate(granules):
            if g_lat.size == 0:
                continue
            idx = np.nonzero(covered & (nearest_arr == j))[0]
            if idx.size == 0:
                continue
            for a in range(g_lat.size):
                d = _haversine_m(g_lat[a], g_lon[a], p_lat[idx], p_lon[idx])
                if d.min() > nearby_m:
                    continue
                checkable += 1
                if d.min() <= radius:
                    hit += 1
        rate = 100.0 * hit / checkable if checkable else 0.0
        print(f"  {radius:8.0f}   {checkable:9d}   {hit:12d}  {rate:5.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
