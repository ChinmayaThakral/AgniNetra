#!/usr/bin/env python3
"""Measure whether diurnal phase is resolvable from polar orbiting data.

Two parts, neither of which loads the model.

Part A asks what phase a sun synchronous constellation can see at all. MODIS and
VIIRS hold a fixed local solar time, so the constellation samples the day at a
small number of points rather than continuously. If the sampled points leave a
wide gap, then a phase that falls in the gap is not merely unused in the
literature, it is unobservable from this class of sensor.

Part B asks whether hour of day separates the weak label classes. It profiles the
labels directly rather than a classifier's predictions, because hour_sin, hour_cos,
is_night and night_fraction_90d are all inputs to B1 and profiling its output by
hour would read back its own features. The labelling rule itself was audited and
uses only distance to a flare, distance to an industrial site, distance to a GEM
asset gated by operating year, and land cover class, none of which carry hour.

The label query is ordered. A seeded permutation test is only reproducible if the
rows arrive in a fixed order, and an unordered DuckDB scan does not guarantee one.
Without the ORDER BY the null mean and the z drifted between two runs of the same
seed, which was observed rather than anticipated.

Local solar time rather than IST is the variable that matters for part A. A sun
synchronous orbit is fixed in local solar time, while IST is one offset applied
across about fourteen degrees of longitude, which smears the crossing by roughly
an hour. Both are reported.

Usage:
    uv run python scripts/phase_resolvability.py
"""

import json
import math
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import duckdb

from ml.documents import provenance_line
from ml.labels.weak import weak_label_sql
from ml.paths import ARTIFACT_DIR, DUCKDB_PATH, ROOT
from ml.population import analysis_where

# IST is UTC+5:30, whose central meridian is 82.5 degrees east.
IST_MERIDIAN_DEG = 82.5
PERMUTATIONS = 300
SEED = 20260918

# Nominal equator crossing local solar times for the constellation, used only as a
# published cross check against the cluster centres derived from the data.
NOMINAL = {
    "Terra day": 10.5,
    "Aqua day": 13.5,
    "VIIRS day": 13.42,
    "Terra night": 22.5,
    "Aqua night": 1.5,
    "VIIRS night": 1.42,
}

LABEL_SQL = f"""
SELECT
  {weak_label_sql("c", "g")} AS weak_label,
  d.acq_hour_ist
FROM detections d
JOIN detection_context c USING (detection_id)
LEFT JOIN detection_gem g USING (detection_id)
WHERE c.state_name IS NOT NULL
ORDER BY d.detection_id
"""


def circular_mean(angles: list[float]) -> float:
    """Mean direction in hours, over angles already expressed in hours."""
    s = sum(math.sin(2 * math.pi * a / 24.0) for a in angles)
    c = sum(math.cos(2 * math.pi * a / 24.0) for a in angles)
    return (math.degrees(math.atan2(s, c)) / 15.0) % 24.0


def axial_resultant(angles: list[float]) -> float:
    """Resultant length on doubled angles.

    The ordinary resultant length cancels on bimodal data, where a day and a night
    cluster sit opposite each other, and would report concentrated sampling as
    uniform. Doubling the angle maps both clusters onto one and removes the
    cancellation, so this is the statistic that answers the question asked.
    """
    n = len(angles)
    s = sum(math.sin(2 * 2 * math.pi * a / 24.0) for a in angles)
    c = sum(math.cos(2 * 2 * math.pi * a / 24.0) for a in angles)
    return math.hypot(s, c) / n


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


def main() -> None:
    con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
    out: dict[str, object] = {}

    rows = con.execute(
        "SELECT family, satellite, daynight, longitude, "
        "hour(acq_ts_ist) + minute(acq_ts_ist) / 60.0 AS ist_h "
        f"FROM detections d {analysis_where('d')}"
    ).fetchall()
    print(f"part A: {len(rows)} polar detections")

    lst_all: list[float] = []
    ist_all: list[float] = []
    per_pass: dict[str, list[float]] = {}
    for _family, satellite, daynight, lon, ist_h in rows:
        lst = (ist_h + (lon - IST_MERIDIAN_DEG) / 15.0) % 24.0
        lst_all.append(lst)
        ist_all.append(ist_h % 24.0)
        key = f"{satellite} {'night' if daynight == 'N' else 'day'}"
        per_pass.setdefault(key, []).append(lst)

    passes = {}
    for key in sorted(per_pass):
        vals = per_pass[key]
        centre = circular_mean(vals)
        within = sum(1 for v in vals if min(abs(v - centre), 24 - abs(v - centre)) <= 0.5)
        passes[key] = {
            "n": len(vals),
            "centre_lst": round(centre, 3),
            "within_30_min_of_centre": round(within / len(vals), 4),
        }
        print(
            f"  {key:16s} n={len(vals):7d} centre LST {centre:5.2f}  "
            f"within 30 min {within / len(vals):6.1%}"
        )

    centres = sorted({round(v["centre_lst"], 1) for v in passes.values()})
    near_centre = 0
    for v in lst_all:
        if any(min(abs(v - c), 24 - abs(v - c)) <= 1.0 for c in centres):
            near_centre += 1

    ring = sorted(centres)
    gaps = [(ring[(i + 1) % len(ring)] - ring[i]) % 24.0 for i in range(len(ring))]
    widest = max(gaps)
    gap_start = ring[gaps.index(widest)]

    hist_lst = Counter(int(v) for v in lst_all)
    hist_ist = Counter(int(v) for v in ist_all)

    out["part_a"] = {
        "n_detections": len(rows),
        "passes": passes,
        "distinct_sampling_points": ring,
        "fraction_within_1h_of_a_sampling_point": round(near_centre / len(lst_all), 4),
        "widest_unsampled_gap_hours": round(widest, 2),
        "widest_gap_starts_lst": round(gap_start, 2),
        "axial_resultant_lst": round(axial_resultant(lst_all), 4),
        "axial_resultant_ist": round(axial_resultant(ist_all), 4),
        "histogram_lst": {str(h): hist_lst.get(h, 0) for h in range(24)},
        "histogram_ist": {str(h): hist_ist.get(h, 0) for h in range(24)},
        "nominal_crossing_lst": NOMINAL,
    }
    print(f"  sampling points (LST): {ring}")
    print(f"  within 1 h of a sampling point: {near_centre / len(lst_all):.2%}")
    print(f"  widest unsampled gap: {widest:.2f} h starting at LST {gap_start:.2f}")
    print(
        f"  axial resultant LST {axial_resultant(lst_all):.4f}  IST {axial_resultant(ist_all):.4f}"
    )

    labelled = con.execute(LABEL_SQL).fetchall()
    print(f"\npart B: {len(labelled)} labelled detections")
    table: dict[str, Counter] = {}
    for label, hour in labelled:
        table.setdefault(label, Counter())[int(hour)] += 1
    levels = list(range(24))

    profile = {}
    for label in sorted(table):
        total = sum(table[label].values())
        shares = {str(h): round(table[label][h] / total, 5) for h in levels}
        peak = max(levels, key=lambda h: table[label][h])
        profile[label] = {"n": total, "peak_hour_ist": peak, "shares": shares}
        print(
            f"  {label:13s} n={total:7d} peak hour IST {peak:2d} "
            f"share {table[label][peak] / total:6.1%}"
        )

    observed_v = cramers_v(table, levels)
    rng = random.Random(SEED)
    labels = [r[0] for r in labelled]
    hours = [int(r[1]) for r in labelled]
    null_v = []
    for _ in range(PERMUTATIONS):
        rng.shuffle(labels)
        perm: dict[str, Counter] = {}
        for label, hour in zip(labels, hours, strict=True):
            perm.setdefault(label, Counter())[hour] += 1
        null_v.append(cramers_v(perm, levels))
    mu = sum(null_v) / len(null_v)
    sd = math.sqrt(sum((v - mu) ** 2 for v in null_v) / len(null_v))
    z = (observed_v - mu) / sd if sd > 0 else float("inf")

    pairwise = {}
    named = [c for c in ("agricultural", "flare", "industrial") if c in table]
    for i, a in enumerate(named):
        for b in named[i + 1 :]:
            pairwise[f"{a} vs {b}"] = round(cramers_v({a: table[a], b: table[b]}, levels), 4)
    for key, value in pairwise.items():
        print(f"  pairwise V  {key:32s} {value:.4f}")

    night_share = {}
    night_hours = set(range(0, 6)) | set(range(20, 24))
    for label in named:
        total = sum(table[label].values())
        night_share[label] = round(sum(table[label][h] for h in night_hours) / total, 4)
        print(f"  night share {label:13s} {night_share[label]:6.1%}")

    out["part_b"] = {
        "n_labelled": len(labelled),
        "profile": profile,
        "cramers_v_observed": round(observed_v, 5),
        "null_permutations": PERMUTATIONS,
        "null_mean": round(mu, 5),
        "null_sd": round(sd, 6),
        "z": round(z, 2),
        "null_max": round(max(null_v), 5),
        "pairwise_cramers_v": pairwise,
        "night_share": night_share,
    }
    print(f"  Cramers V observed {observed_v:.5f}  null mean {mu:.5f} sd {sd:.6f}  z {z:.1f}")

    # Part C exists because a prediction was put on record before part A ran, that
    # hour_sin and hour_cos would be near constant columns and the contamination of
    # B1 by time of day would therefore be small in practice. It is measured here
    # rather than asserted, and it is refuted.
    variance = con.execute(
        "SELECT stddev_pop(sin(2 * pi() * acq_hour_ist / 24.0)), "
        "stddev_pop(cos(2 * pi() * acq_hour_ist / 24.0)), "
        "stddev_pop(CASE WHEN daynight = 'N' THEN 1.0 ELSE 0.0 END), "
        "avg(CASE WHEN daynight = 'N' THEN 1.0 ELSE 0.0 END) "
        f"FROM detections d {analysis_where('d')}"
    ).fetchone()
    uniform_reference = 1.0 / math.sqrt(2.0)
    out["part_c"] = {
        "sd_hour_sin": round(variance[0], 4),
        "sd_hour_cos": round(variance[1], 4),
        "sd_is_night": round(variance[2], 4),
        "mean_is_night": round(variance[3], 4),
        "sd_reference_uniform_phase": round(uniform_reference, 4),
        "sd_reference_binary_max": 0.5,
    }
    print(
        f"\npart C: sd(hour_sin) {variance[0]:.4f}  sd(hour_cos) {variance[1]:.4f}  "
        f"sd(is_night) {variance[2]:.4f}"
    )
    print(f"  uniform phase reference {uniform_reference:.4f}, binary maximum 0.5")

    # Part D compares the two sensor classes on identical days, so the difference
    # cannot be an artefact of comparing different weeks or different seasons.
    insat_path = ARTIFACT_DIR / "insat_diurnal.json"
    part_d = None
    if insat_path.exists():
        insat = json.loads(insat_path.read_text(encoding="utf-8"))
        days = sorted(insat["days"])
        rows_d = con.execute(
            "SELECT d.acq_hour_ist, count(*) FROM detections d "
            "JOIN detection_context c USING (detection_id) "
            "LEFT JOIN detection_gem g USING (detection_id) "
            "WHERE c.state_name IS NOT NULL "
            "AND d.acq_date_ist BETWEEN ? AND ? "
            f"AND {weak_label_sql('c', 'g')} = 'agricultural' "
            "GROUP BY 1 ORDER BY 1",
            [days[0], days[-1]],
        ).fetchall()
        firms = {int(h): n for h, n in rows_d}
        firms_total = sum(firms.values())
        geo = insat["mean_by_hour"]
        geo_total = sum(geo.values())
        blind = range(14, 22)
        part_d = {
            "days": days,
            "class": "agricultural",
            "firms_n": firms_total,
            "firms_peak_hour_ist": max(firms, key=lambda h: firms[h]),
            "insat_peak_hour_ist": max(range(24), key=lambda h: geo[str(h)]),
            "firms_share_by_hour": {
                str(h): round(firms.get(h, 0) / firms_total, 5) for h in range(24)
            },
            "insat_share_by_hour": {str(h): round(geo[str(h)] / geo_total, 5) for h in range(24)},
            "firms_share_1400_to_2159": round(sum(firms.get(h, 0) for h in blind) / firms_total, 4),
            "insat_share_1400_to_2159": round(sum(geo[str(h)] for h in blind) / geo_total, 4),
            "firms_share_1500_to_1759": round(
                sum(firms.get(h, 0) for h in range(15, 18)) / firms_total, 4
            ),
            "insat_share_1500_to_1759": round(
                sum(geo[str(h)] for h in range(15, 18)) / geo_total, 4
            ),
        }
        out["part_d"] = part_d
        print(f"\npart D: same days {days[0]} to {days[-1]}, agricultural class")
        print(
            f"  FIRMS peak hour {part_d['firms_peak_hour_ist']}, "
            f"INSAT peak hour {part_d['insat_peak_hour_ist']}"
        )
        print(
            f"  IST 15:00 to 17:59 share, FIRMS "
            f"{part_d['firms_share_1500_to_1759']:.1%} against INSAT "
            f"{part_d['insat_share_1500_to_1759']:.1%}"
        )

    path = ARTIFACT_DIR / "phase_resolvability.json"
    path.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"\nwrote {path.relative_to(ROOT)}")

    doc = ROOT / "docs" / "phase_resolvability.md"
    a = out["part_a"]
    b = out["part_b"]
    c = out["part_c"]
    lines = [
        "# Phase resolvability from polar orbiting data",
        "",
        "Regenerate: `uv run python scripts/phase_resolvability.py`",
        provenance_line(__file__),
        "",
        "Generated by `scripts/phase_resolvability.py`.",
        "",
        "## Part A. What phase a sun synchronous constellation can see",
        "",
        f"Measured over {a['n_detections']} detections. Local solar time is IST corrected",
        f"for longitude about the {IST_MERIDIAN_DEG} degree meridian.",
        "",
        "| pass | n | centre LST | within 30 min of centre |",
        "| --- | --- | --- | --- |",
    ]
    for key, value in a["passes"].items():
        lines.append(
            f"| {key} | {value['n']} | {value['centre_lst']:.2f} | "
            f"{value['within_30_min_of_centre']:.1%} |"
        )
    lines += [
        "",
        f"Distinct sampling points in local solar time: {a['distinct_sampling_points']}.",
        "",
        f"{a['fraction_within_1h_of_a_sampling_point']:.2%} of detections fall within one "
        "hour of one of those points.",
        "",
        f"**Widest unsampled gap: {a['widest_unsampled_gap_hours']} hours, beginning at "
        f"local solar time {a['widest_gap_starts_lst']}.**",
        "",
        f"Axial resultant length {a['axial_resultant_lst']} on local solar time and "
        f"{a['axial_resultant_ist']} on IST. The statistic is computed on doubled angles "
        "because the ordinary resultant cancels on data with a day and a night cluster "
        "sitting opposite each other, and would report concentrated sampling as uniform.",
        "",
        "## Part B. Whether hour of day separates the weak label classes",
        "",
        f"Measured over {b['n_labelled']} labelled detections, profiling the weak labels "
        "directly with no model in the loop.",
        "",
        "| class | n | peak hour IST | share at peak | night share |",
        "| --- | --- | --- | --- | --- |",
    ]
    for label, value in b["profile"].items():
        peak = str(value["peak_hour_ist"])
        night = b["night_share"].get(label)
        lines.append(
            f"| {label} | {value['n']} | {peak} | {value['shares'][peak]:.1%} | "
            + (f"{night:.1%} |" if night is not None else "not applicable |")
        )
    lines += [
        "",
        f"Cramers V {b['cramers_v_observed']} against a permuted null over "
        f"{b['null_permutations']} permutations with mean {b['null_mean']} and standard "
        f"deviation {b['null_sd']}, giving z {b['z']}.",
        "",
        "| pair | Cramers V |",
        "| --- | --- |",
    ]
    for key, value in b["pairwise_cramers_v"].items():
        lines.append(f"| {key} | {value} |")
    lines += [
        "",
        "## Part C. Variance of the time derived features in B1",
        "",
        "| feature | standard deviation |",
        "| --- | --- |",
        f"| hour_sin | {c['sd_hour_sin']} |",
        f"| hour_cos | {c['sd_hour_cos']} |",
        f"| is_night | {c['sd_is_night']} |",
        "",
        f"Reference values: {c['sd_reference_uniform_phase']} for a sine or cosine of a "
        f"phase spread uniformly over the day, {c['sd_reference_binary_max']} for the "
        "maximum of a binary variable.",
        "",
    ]
    if part_d is not None:
        d = part_d
        lines += [
            "## Part D. The two sensor classes on identical days",
            "",
            f"Agricultural class only, {d['days'][0]} to {d['days'][-1]}, so the "
            "difference cannot come from comparing different weeks or seasons. FIRMS "
            f"contributes {d['firms_n']} detections.",
            "",
            "| hour IST | FIRMS polar | INSAT geostationary |",
            "| --- | --- | --- |",
        ]
        for h in range(24):
            f = d["firms_share_by_hour"][str(h)]
            g = d["insat_share_by_hour"][str(h)]
            if f > 0.001 or g > 0.001:
                lines.append(f"| {h} | {f:.1%} | {g:.1%} |")
        lines += [
            "",
            f"Peak hour: FIRMS {d['firms_peak_hour_ist']}, INSAT {d['insat_peak_hour_ist']}.",
            "",
            f"Share in IST 15:00 to 17:59: FIRMS {d['firms_share_1500_to_1759']:.1%}, "
            f"INSAT {d['insat_share_1500_to_1759']:.1%}.",
            "",
            f"Share in IST 14:00 to 21:59: FIRMS {d['firms_share_1400_to_2159']:.1%}, "
            f"INSAT {d['insat_share_1400_to_2159']:.1%}.",
            "",
        ]
    doc.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {doc.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
