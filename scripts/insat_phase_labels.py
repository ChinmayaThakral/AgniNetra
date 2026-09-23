#!/usr/bin/env python3
"""Run the weak label phase profile on INSAT detections rather than polar ones.

D100 measured that hour of day does not separate flare from industrial, but it
measured that on polar data, whose six sampling points fall into a day group and a
night group. A measurement made where phase cannot be observed cannot settle
whether phase separates anything, so that result is a bound rather than a
conclusion.

This closes the argument from the other side. The weak label rule audited in D100
has four inputs, all spatial or categorical and none of them sensor specific, so
the same rule applies unchanged to INSAT detections. Running the profile there
tests the question over hours the polar constellation never visits.

Two bounds belong on any reading of the output. INSAT detections are
overwhelmingly daytime, so this does not test the night where flares dominate in
the polar record. And the pixel is 4 km against 375 m for VIIRS, so a 500 m flare
radius and a 1 km industrial radius are small relative to the footprint. A null
here is weak evidence, not negative evidence.

Usage:
    uv run python scripts/insat_phase_labels.py
"""

import json
import math
import random
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import duckdb

from ml.labels.weak import weak_label_sql
from ml.paths import ARTIFACT_DIR, DATA_DIR, DUCKDB_PATH, ROOT
from ml.reference import landcover

SOURCES = ("insat", "insat_rabi")
PERMUTATIONS = 300
SEED = 20260918


def load_points() -> list[dict]:
    points: list[dict] = []
    for source in SOURCES:
        for path in sorted((DATA_DIR / "derived" / source).glob("*.npz")):
            with np.load(path, allow_pickle=False) as data:
                if data["longitude"].size == 0:
                    continue
                hour = int(data["hour_ist"])
                stamp = str(data["acquired_utc"])[:10]
                for lon, lat in zip(data["longitude"], data["latitude"], strict=True):
                    points.append(
                        {
                            "source": source,
                            "longitude": float(lon),
                            "latitude": float(lat),
                            "hour": hour,
                            "date": stamp,
                        }
                    )
    return points


def attach_distances(con: duckdb.DuckDBPyConnection, points: list[dict]) -> None:
    con.execute(
        "CREATE OR REPLACE TEMP TABLE insat_pts "
        "(idx INTEGER, longitude DOUBLE, latitude DOUBLE, year INTEGER)"
    )
    con.executemany(
        "INSERT INTO insat_pts VALUES (?, ?, ?, ?)",
        [(i, p["longitude"], p["latitude"], int(p["date"][:4])) for i, p in enumerate(points)],
    )
    window = 0.5
    rows = con.execute(
        f"""
        SELECT p.idx,
          (SELECT min(geo_distance_m(p.longitude, p.latitude, f.longitude, f.latitude))
             FROM ref_flares f
            WHERE f.longitude BETWEEN p.longitude - {window} AND p.longitude + {window}
              AND f.latitude BETWEEN p.latitude - {window} AND p.latitude + {window}),
          (SELECT min(geo_distance_m(p.longitude, p.latitude, i.longitude, i.latitude))
             FROM ref_osm_industrial i
            WHERE i.longitude BETWEEN p.longitude - {window} AND p.longitude + {window}
              AND i.latitude BETWEEN p.latitude - {window} AND p.latitude + {window}),
          (SELECT min(geo_distance_m(p.longitude, p.latitude, g.longitude, g.latitude))
             FROM ref_gem_assets g
            WHERE g.longitude BETWEEN p.longitude - {window} AND p.longitude + {window}
              AND g.latitude BETWEEN p.latitude - {window} AND p.latitude + {window}
              AND (g.start_year IS NULL OR g.start_year <= p.year)
              AND (g.retired_year IS NULL OR g.retired_year >= p.year))
        FROM insat_pts p ORDER BY p.idx
        """
    ).fetchall()
    for idx, flare, industrial, gem in rows:
        points[idx]["flare_m"] = None if flare is None else float(flare)
        points[idx]["industrial_m"] = None if industrial is None else float(industrial)
        points[idx]["gem_m"] = None if gem is None else float(gem)


def attach_landcover(points: list[dict]) -> int:
    """Sample WorldCover for each point, from disk where possible, else remotely.

    An earlier version of this script passed (latitude, longitude) pairs and every
    sample came back None, which was then written up as the remote sampler being
    broken. It was the axis order trap this repository documents elsewhere, committed
    in the one place that had no test. D116. The land cover functions now take the two
    axes as separately named keyword arguments and refuse a tile that contains none of
    its points, so that call can no longer be written silently. D121.
    """
    lons = [p["longitude"] for p in points]
    lats = [p["latitude"] for p in points]
    coordinates = list(zip(lons, lats, strict=True))
    cache_path = ARTIFACT_DIR / "insat_landcover_cache.json"
    cache: dict[str, str | None] = {}
    if cache_path.is_file():
        cache = json.loads(cache_path.read_text())
    key = [f"{lon:.6f},{lat:.6f}" for lon, lat in coordinates]
    if all(k in cache for k in key):
        for i, k in enumerate(key):
            points[i]["landcover_class"] = cache[k]
        absent = sum(1 for k in key if cache[k] is None)
        print(f"  landcover from cache, {absent} points unsampled")
        return absent
    tiles = landcover.group_by_tile(longitudes=lons, latitudes=lats)
    root = DATA_DIR / "raw" / "worldcover"
    missing = 0
    for position, (name, idxs) in enumerate(sorted(tiles.items()), start=1):
        sub_lons = [lons[i] for i in idxs]
        sub_lats = [lats[i] for i in idxs]
        local = root / name
        try:
            if local.is_file():
                codes = landcover.sample_tile(local, longitudes=sub_lons, latitudes=sub_lats)
            else:
                codes = landcover.sample_tile_remote(name, longitudes=sub_lons, latitudes=sub_lats)
        except (landcover.TileNotAvailableError, OSError, RuntimeError) as exc:
            # Network reads fail transiently. A tile that cannot be read is recorded
            # as unsampled rather than aborting, so one reset does not discard the
            # tiles already fetched. The cache below makes a retry cheap.
            print(f"  landcover tile {name} unavailable: {type(exc).__name__}")
            missing += len(idxs)
            for i in idxs:
                points[i]["landcover_class"] = None
            continue
        for i, code in zip(idxs, codes, strict=True):
            points[i]["landcover_class"] = landcover.class_name(code)
            if code is None:
                missing += 1
        cache_path.write_text(
            json.dumps({k: points[i].get("landcover_class") for i, k in enumerate(key)}, indent=0)
            + "\n",
            encoding="utf-8",
        )
        if position % 20 == 0:
            print(f"  landcover {position}/{len(tiles)} tiles", flush=True)
    cache_path.write_text(
        json.dumps({k: points[i]["landcover_class"] for i, k in enumerate(key)}, indent=0) + "\n",
        encoding="utf-8",
    )
    return missing


def attach_labels(con: duckdb.DuckDBPyConnection, points: list[dict]) -> None:
    """Label every point with the project's one weak label rule, not a copy of it.

    An earlier version reimplemented the rule here in Python. It agreed with the rule
    B1 trains on, but a hand copy agreeing today is how the stored label column came
    to disagree with it on 74742 rows. The INSAT points are loaded into a table shaped
    like the context and GEM columns and labelled by `weak_label_sql`. D120.
    """
    con.execute(
        "CREATE OR REPLACE TEMP TABLE insat_ctx (idx INTEGER, flare_m DOUBLE, "
        "industrial_m DOUBLE, gem_m_temporal DOUBLE, landcover_class VARCHAR)"
    )
    con.executemany(
        "INSERT INTO insat_ctx VALUES (?, ?, ?, ?, ?)",
        [
            (i, q.get("flare_m"), q.get("industrial_m"), q.get("gem_m"), q.get("landcover_class"))
            for i, q in enumerate(points)
        ],
    )
    labelled = con.execute(
        f"SELECT idx, {weak_label_sql('t', 't')} FROM insat_ctx t ORDER BY idx"
    ).fetchall()
    for idx, name in labelled:
        points[idx]["label"] = name


def cramers_v(table: dict[str, Counter], levels: list[int]) -> float:
    rows = sorted(table)
    n = sum(sum(table[r].values()) for r in rows)
    if n == 0:
        return 0.0
    row_tot = {r: sum(table[r].values()) for r in rows}
    col_tot = {c: sum(table[r][c] for r in rows) for c in levels}
    chi2 = 0.0
    for r in rows:
        for c in levels:
            expected = row_tot[r] * col_tot[c] / n
            if expected > 0:
                chi2 += (table[r][c] - expected) ** 2 / expected
    k = min(len(rows), len([c for c in levels if col_tot[c] > 0]))
    return math.sqrt(chi2 / (n * (k - 1))) if k > 1 else 0.0


def permuted(table: dict[str, Counter], pairs: list[tuple[str, int]], levels, observed: float):
    """Null distribution, returned with the empirical p value rather than only a z.

    A z assumes the null is normal. On this sample it is not safe: the largest of 300
    permutations exceeded the observed statistic, which a z of 2.28 would have hidden
    entirely. The proportion of permutations reaching the observed value is the
    statistic a permutation test actually licenses. D118.
    """
    rng = random.Random(SEED)
    labels = [a for a, _ in pairs]
    hours = [h for _, h in pairs]
    null = []
    for _ in range(PERMUTATIONS):
        rng.shuffle(labels)
        perm: dict[str, Counter] = {}
        for lab, h in zip(labels, hours, strict=True):
            perm.setdefault(lab, Counter())[h] += 1
        null.append(cramers_v(perm, levels))
    mu = sum(null) / len(null)
    sd = math.sqrt(sum((v - mu) ** 2 for v in null) / len(null))
    at_least = sum(1 for v in null if v >= observed)
    p_value = (at_least + 1) / (len(null) + 1)
    return mu, sd, max(null), p_value


def main() -> int:
    points = load_points()
    if not points:
        print("BLOCKED: no INSAT detections found", file=sys.stderr)
        return 2
    print(f"INSAT detections loaded: {len(points)}")

    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    con.execute("INSTALL spatial; LOAD spatial;")
    attach_distances(con, points)
    missing = attach_landcover(points)
    if missing:
        print(f"  landcover unavailable for {missing} points, tile not on disk")

    attach_labels(con, points)

    counts = Counter(p["label"] for p in points)
    print("  labels:", dict(counts))

    pairs = [(p["label"], p["hour"]) for p in points if p["label"] != "unlabelled"]
    levels = sorted({h for _, h in pairs})
    table: dict[str, Counter] = {}
    for lab, h in pairs:
        table.setdefault(lab, Counter())[h] += 1

    profile = {}
    for lab in sorted(table):
        total = sum(table[lab].values())
        peak = max(table[lab], key=lambda h: table[lab][h])
        afternoon = sum(table[lab][h] for h in range(14, 19))
        profile[lab] = {
            "n": total,
            "peak_hour_ist": peak,
            "share_at_peak": round(table[lab][peak] / total, 4),
            "share_1400_to_1859": round(afternoon / total, 4),
            "shares": {str(h): round(table[lab][h] / total, 5) for h in levels},
        }
        print(f"  {lab:13s} n={total:5d} peak {peak:2d} afternoon share {afternoon / total:5.1%}")

    # The flare radius is swept because a single radius cannot distinguish a class
    # that is absent from a class whose radius is too small for a 4 km pixel.
    sweep = {}
    for flare_r, ind_r in ((500, 1000), (1000, 2000), (2000, 4000), (4000, 4000)):
        n_flare = sum(1 for q in points if q.get("flare_m") is not None and q["flare_m"] <= flare_r)
        n_ind = sum(
            1
            for q in points
            if not (q.get("flare_m") is not None and q["flare_m"] <= flare_r)
            and min(
                [d for d in (q.get("industrial_m"), q.get("gem_m")) if d is not None],
                default=float("inf"),
            )
            <= ind_r
        )
        sweep[f"flare<={flare_r}m industrial<={ind_r}m"] = {
            "flare": n_flare,
            "industrial": n_ind,
        }
        print(
            f"  radius sweep flare {flare_r:5d} m industrial {ind_r:5d} m: "
            f"flare {n_flare}, industrial {n_ind}"
        )

    nearest_flare = min(
        (q["flare_m"] for q in points if q.get("flare_m") is not None),
        default=None,
    )

    out: dict[str, object] = {
        "n_detections": len(points),
        "sources": list(SOURCES),
        "label_counts": dict(counts),
        "landcover_available": len(points) - missing,
        "landcover_missing": missing,
        "profile": profile,
        "hours_present": levels,
        "radius_sweep": sweep,
        "nearest_flare_m": None if nearest_flare is None else round(nearest_flare, 1),
        "night_share_hours_19_to_06": round(
            sum(1 for q in points if q["hour"] >= 19 or q["hour"] <= 6) / len(points), 4
        ),
    }

    if len(table) > 1:
        observed = cramers_v(table, levels)
        mu, sd, mx, p_value = permuted(table, pairs, levels, observed)
        z = (observed - mu) / sd if sd > 0 else float("nan")
        out["all_classes"] = {
            "cramers_v": round(observed, 5),
            "null_mean": round(mu, 5),
            "null_sd": round(sd, 6),
            "null_max": round(mx, 5),
            "z": round(z, 2),
            "empirical_p": round(p_value, 4),
        }
        print(
            f"  all classes V {observed:.4f}  null {mu:.4f} sd {sd:.5f}  "
            f"z {z:.1f}  empirical p {p_value:.4f}"
        )

    if "flare" in table and "industrial" in table:
        sub = {"flare": table["flare"], "industrial": table["industrial"]}
        sub_pairs = [(a, h) for a, h in pairs if a in sub]
        sub_levels = sorted({h for _, h in sub_pairs})
        observed = cramers_v(sub, sub_levels)
        mu, sd, mx = permuted(sub, sub_pairs, sub_levels)
        z = (observed - mu) / sd if sd > 0 else float("nan")
        out["flare_vs_industrial"] = {
            "n_flare": sum(sub["flare"].values()),
            "n_industrial": sum(sub["industrial"].values()),
            "cramers_v": round(observed, 5),
            "null_mean": round(mu, 5),
            "null_sd": round(sd, 6),
            "null_max": round(mx, 5),
            "z": round(z, 2),
        }
        print(f"  flare vs industrial V {observed:.4f}  null {mu:.4f} sd {sd:.5f}  z {z:.1f}")

    path = ARTIFACT_DIR / "insat_phase_labels.json"
    path.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
