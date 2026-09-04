#!/usr/bin/env python3
"""Export precomputed phase 4 results for the console.

The console runs no model. Everything it displays is produced here, including the
class posterior, the conformal prediction set, the applicability domain status and
the recurrence history. Metrics come from the phase 4 artifacts rather than being
recomputed, so a number shown in the interface and a number in docs/results.md
have one source.

The detection sample is bounded because the full record is 601941 rows and the
browser is not the place for it. The sampling rule is exported alongside the data
and the console states it, rather than presenting a sample as the whole.

Usage:
    uv run python scripts/export_console.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import duckdb
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import StandardScaler

from ml.features.matrix import FEATURE_COLUMNS, FEATURE_SQL
from ml.labels.splits import EXTERNAL_EXTENTS, HELD_OUT_GROUPS, split_for
from ml.labels.weak import TRAINED_CLASSES
from ml.paths import ARTIFACT_DIR, DUCKDB_PATH, ROOT, ensure_dir

OUT = ROOT / "apps" / "console" / "public" / "data"
SEED = 20260904
SAMPLE_PER_CLASS = 4000
NOMINAL = 0.90
AOA_QUANTILE = 0.95
PERSISTENT_MIN_PRIORS = 20


def optional_number(value: object, digits: int = 0) -> float | int | None:
    """Round a value, returning None for a missing one.

    pandas represents a missing numeric as NaN rather than None, and NaN is not
    None, so an is None check passes it straight through to round() and fails.
    """
    if value is None or pd.isna(value):
        return None
    return round(float(value), digits) if digits else round(float(value))


def main() -> int:
    rng = np.random.default_rng(SEED)
    con = duckdb.connect(str(DUCKDB_PATH))
    frame = con.execute(FEATURE_SQL).df()
    trained = frame[frame["weak_label"].isin(TRAINED_CLASSES)].copy()
    columns = list(FEATURE_COLUMNS)

    _, test_states = split_for("group_a")
    fit_pool = trained[~trained["state_name"].isin(test_states)]
    mask = rng.random(len(fit_pool)) < 0.2
    calibration, fit_set = fit_pool[mask], fit_pool[~mask]

    model = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.1, random_state=SEED)
    model.fit(fit_set[columns], fit_set["weak_label"])
    classes = list(model.classes_)
    print(f"fitted on {len(fit_set)} rows, classes {classes}", flush=True)

    cal_probs = model.predict_proba(calibration[columns])
    true_index = [classes.index(v) for v in calibration["weak_label"]]
    scores = 1.0 - cal_probs[np.arange(len(calibration)), true_index]
    level = min(1.0, np.ceil((len(scores) + 1) * NOMINAL) / len(scores))
    threshold = float(np.quantile(scores, level))

    scaler = StandardScaler().fit(fit_set[columns].fillna(0.0))
    fit_scaled = scaler.transform(fit_set[columns].fillna(0.0))
    index = rng.choice(len(fit_scaled), size=min(40000, len(fit_scaled)), replace=False)
    neighbours = NearestNeighbors(n_neighbors=2).fit(fit_scaled[index])
    train_distance, _ = neighbours.kneighbors(fit_scaled[index])
    aoa_threshold = float(np.quantile(train_distance[:, 1], AOA_QUANTILE))

    # Stratified sample of the held out group, so every class is visible in the
    # interface even though flare is 1.16 percent of the record.
    held_out = trained[trained["state_name"].isin(test_states)]
    parts = [
        held_out[held_out["weak_label"] == name].sample(
            n=min(SAMPLE_PER_CLASS, int((held_out["weak_label"] == name).sum())),
            random_state=SEED,
        )
        for name in TRAINED_CLASSES
    ]
    sample = pd.concat(parts).reset_index(drop=True)

    probs = model.predict_proba(sample[columns])
    included = probs >= (1.0 - threshold)
    sample_scaled = scaler.transform(sample[columns].fillna(0.0))
    distance, _ = neighbours.kneighbors(sample_scaled, n_neighbors=1)
    outside = distance[:, 0] > aoa_threshold

    records = []
    for i in range(len(sample)):
        row = sample.iloc[i]
        posterior = {classes[j]: round(float(probs[i, j]), 4) for j in range(len(classes))}
        prediction_set = [classes[j] for j in range(len(classes)) if included[i, j]]
        records.append(
            {
                "id": str(row["detection_id"])[:12],
                "lon": round(float(row["longitude"]), 5),
                "lat": round(float(row["latitude"]), 5),
                "date": str(row["acq_date_ist"]),
                "state": row["state_name"],
                "frpMw": optional_number(row["frp"], 2),
                "isNight": bool(row["is_night"]),
                "weakLabel": row["weak_label"],
                "predicted": classes[int(probs[i].argmax())],
                "posterior": posterior,
                "predictionSet": prediction_set,
                "outsideApplicability": bool(outside[i]),
                "priorCount90d": int(row["prior_count_90d"]),
                "priorCount30d": int(row["prior_count_30d"]),
                "nightFraction90d": optional_number(row["night_fraction_90d"], 3),
                "meanGapDays": optional_number(row["mean_gap_days"], 2),
                "nearestFlareM": optional_number(row["flare_m"]),
                "nearestIndustrialM": optional_number(row["industrial_m"]),
                "nearestGemM": optional_number(row["gem_m_temporal"]),
            }
        )
    print(f"detections exported: {len(records)}", flush=True)

    # Persistent sources: recurring locations, flagged by whether any registry
    # knows about them. The unregistered ones are the product.
    persistent = con.execute(
        f"""
        SELECT round(d.longitude, 3) AS lon, round(d.latitude, 3) AS lat,
               c.state_name,
               count(*) AS detections,
               max(r.prior_count_90d) AS max_priors,
               avg(coalesce(r.night_fraction_90d, 0)) AS night_fraction,
               min(coalesce(c.industrial_m, 1e12)) AS nearest_osm_m,
               min(coalesce(g.gem_m_temporal, 1e12)) AS nearest_gem_m,
               min(coalesce(c.flare_m, 1e12)) AS nearest_flare_m
        FROM detections d
        JOIN detection_context c USING (detection_id)
        LEFT JOIN detection_recurrence r USING (detection_id)
        LEFT JOIN detection_gem g USING (detection_id)
        WHERE c.state_name IS NOT NULL AND r.prior_count_90d >= {PERSISTENT_MIN_PRIORS}
        GROUP BY 1, 2, 3
        HAVING count(*) >= 5
        ORDER BY detections DESC
        LIMIT 400
        """
    ).fetchall()
    sources = []
    for lon, lat, state, detections, max_priors, night, osm_m, gem_m, flare_m in persistent:
        nearest = min(float(osm_m), float(gem_m), float(flare_m))
        sources.append(
            {
                "lon": float(lon),
                "lat": float(lat),
                "state": state,
                "detections": int(detections),
                "maxPriors": int(max_priors),
                "nightFraction": round(float(night), 3),
                "nearestAssetM": None if nearest > 1e11 else round(nearest),
                "registered": bool(nearest <= 1000),
            }
        )
    unregistered = sum(1 for s in sources if not s["registered"])
    print(f"persistent sources: {len(sources)}, unregistered {unregistered}", flush=True)

    b1 = json.loads((ARTIFACT_DIR / "b1_results.json").read_text())
    uncertainty = json.loads((ARTIFACT_DIR / "conformal_aoa_b2.json").read_text())

    metrics = {
        "source": "ml/artifacts/b1_results.json and conformal_aoa_b2.json, phase 4",
        "seed": SEED,
        "resampling": "option A, no class weighting, fitted on the true prior. D32",
        "trainedClasses": list(TRAINED_CLASSES),
        "wildfire": "not measured. No weak label rule produces it; the baselines "
        "structurally cannot recover it. D33",
        "leakageMacroF1": b1["leakage_macro_f1"],
        "cleanMacroF1": b1["clean_macro_f1"],
        "perGroup": {
            group: {
                "macroF1": b1["option_a"][group]["macro avg"]["f1-score"],
                "classes": {
                    name: {
                        "precision": b1["option_a"][group][name]["precision"],
                        "recall": b1["option_a"][group][name]["recall"],
                        "f1": b1["option_a"][group][name]["f1-score"],
                        "support": int(b1["option_a"][group][name]["support"]),
                    }
                    for name in TRAINED_CLASSES
                },
            }
            for group in b1["option_a"]
        },
        "uncertainty": {
            group: uncertainty[group] for group in uncertainty if group.startswith("group")
        },
        "b2Industrial": uncertainty["b2_industrial"],
        "notMeasured": {
            "B3 INSAT-3DS contextual thresholds": "blocked on MOSDAC access",
            "B4 foundation model probe": "encoder verified, 768 dimensional embedding; "
            "imagery blocked on Copernicus registration",
            "KAALCHAKRA against B1 and B2": "phase 6, not started",
            "diurnal shift 2020 to 2024": "2020 not ingested",
            "flare kernel family": "unresolved, not confirmed. D42",
        },
    }

    manifest = {
        "generatedBy": "scripts/export_console.py",
        "heldOutGroup": "group_a",
        "heldOutStates": sorted(HELD_OUT_GROUPS["group_a"]),
        "samplingRule": (
            f"Stratified sample of up to {SAMPLE_PER_CLASS} detections per class from the "
            "group_a held out states. Flare is 1.16 percent of the record, so an unstratified "
            "sample would show almost none. This is a sample, not the whole record."
        ),
        "totalDetectionsInStore": int(con.execute("SELECT count(*) FROM detections").fetchone()[0]),
        "indiaAssignedDetections": int(
            con.execute(
                "SELECT count(*) FROM detection_context WHERE state_name IS NOT NULL"
            ).fetchone()[0]
        ),
        "sampledDetections": len(records),
        "windows": [
            "2023-10-01 to 2023-11-30",
            "2024-10-01 to 2024-11-30",
            "2026-06-06 to 2026-09-03",
        ],
        "snapshots": {
            "FIRMS": "VIIRS S-NPP, NOAA-20, NOAA-21 and MODIS, standard processing and "
            "near real time as availability dictated",
            "OpenStreetMap": "Geofabrik India extract 2026-09-02T20:20:51Z, sequence 4895",
            "Global Energy Monitor": "power and coal August 2026, cement July 2026, "
            "steel June 2026",
            "ESA WorldCover": "v200, 2021",
            "EOG flare catalogue": "annual, 2019 to 2024",
        },
        "conformalNominal": NOMINAL,
        "applicabilityQuantile": AOA_QUANTILE,
        "persistentSourceRule": (
            f"Locations with at least {PERSISTENT_MIN_PRIORS} prior detections in a trailing "
            "90 days and at least 5 detections in the record, grouped to 3 decimal places of "
            "coordinate, roughly 110 m. Registered means within 1 km "
            "of an OSM industrial feature, a GEM asset operating on the date, or a "
            "catalogued flare."
        ),
        "attribution": [
            {
                "name": "NASA FIRMS",
                "detail": "MODIS and VIIRS active fire data from NASA "
                "FIRMS, part of NASA's Earth Science Data and Information System",
                "url": "https://firms.modaps.eosdis.nasa.gov/",
            },
            {
                "name": "Global Energy Monitor",
                "detail": "Power, coal mine, iron and steel "
                "and cement trackers, licensed CC BY 4.0",
                "url": "https://globalenergymonitor.org/",
            },
            {
                "name": "OpenStreetMap",
                "detail": "Industrial features and administrative "
                "boundaries, copyright OpenStreetMap contributors, licensed ODbL 1.0",
                "url": "https://www.openstreetmap.org/copyright",
            },
            {
                "name": "ESA WorldCover",
                "detail": "ESA WorldCover 10 m 2021 v200, licensed CC BY 4.0",
                "url": "https://esa-worldcover.org/",
            },
            {
                "name": "EOG",
                "detail": "VIIRS global gas flaring catalogue, Earth "
                "Observation Group, Colorado School of Mines",
                "url": "https://eogdata.mines.edu/products/vnf/",
            },
        ],
        "externalExtents": {k: list(v) for k, v in EXTERNAL_EXTENTS.items()},
    }

    ensure_dir(OUT)
    # allow_nan=False so a missing value that slipped through as NaN fails here,
    # where the message names the field, rather than in the browser as a JSON parse
    # error. Bare NaN is valid Python json output and is not valid JSON.
    (OUT / "detections.json").write_text(
        json.dumps(records, separators=(",", ":"), allow_nan=False)
    )
    (OUT / "sources.json").write_text(json.dumps(sources, separators=(",", ":"), allow_nan=False))
    (OUT / "metrics.json").write_text(json.dumps(metrics, indent=1, default=float, allow_nan=False))
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1, allow_nan=False))
    for name in ("detections.json", "sources.json", "metrics.json", "manifest.json"):
        print(f"  {name}: {(OUT / name).stat().st_size / 1024:.0f} KB")
    print(f"\nwritten to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
