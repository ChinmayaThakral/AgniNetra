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

import os

# Pinned before any estimator library loads. Thread count changes the floating
# point reduction order inside sklearn's histogram builders, and random_state does
# not constrain it, so a fixed seed alone does not reproduce a fit. D59.
os.environ.setdefault("OMP_NUM_THREADS", "4")


import json
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import duckdb
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import StandardScaler

from ml.features.matrix import FEATURE_COLUMNS, FEATURE_SQL
from ml.labels.splits import EXTERNAL_EXTENTS, HELD_OUT_GROUPS, test_rows, training_rows
from ml.labels.weak import TRAINED_CLASSES
from ml.paths import ARTIFACT_DIR, DUCKDB_PATH, ROOT, ensure_dir

OUT = ROOT / "apps" / "console" / "public" / "data"
SEED = 20260904
SAMPLE_PER_CLASS = 4000
NOMINAL = 0.90
AOA_QUANTILE = 0.95
PERSISTENT_MIN_PRIORS = 20


# The EOG flare catalogue is recorded in `reference_layers` as
# redistributable=False, "attribution required, redistribution not confirmed".
#
# Publishing an exact distance to the nearest flare for every detection does not
# merely derive from that layer, it partially reconstructs it: distances from many
# known points to a common unknown point are trilaterable, and the export carries
# thousands of them. Coarse bands keep the analytical meaning, which is whether a
# detection sits on or near a catalogued flare, while destroying the geometry that
# makes reconstruction possible. D69.
FLARE_BANDS: tuple[tuple[float, str], ...] = (
    (1000.0, "under 1 km"),
    (5000.0, "1 to 5 km"),
    (20000.0, "5 to 20 km"),
)


def distance_band(value) -> str | None:
    """Return the coarse band for a distance in metres, or None if unmeasured."""
    number = optional_number(value)
    if number is None:
        return None
    for edge, label in FLARE_BANDS:
        if number < edge:
            return label
    return "over 20 km"


def optional_number(value: object, digits: int = 0) -> float | int | None:
    """Round a value, returning None for a missing one.

    pandas represents a missing numeric as NaN rather than None, and NaN is not
    None, so an is None check passes it straight through to round() and fails.
    """
    if value is None or pd.isna(value):
        return None
    return round(float(value), digits) if digits else round(float(value))


def stage_generator(purpose: str) -> np.random.Generator:
    """An independent stream per stage, derived from what the stage is for.

    Two stages sharing one generator makes the second depend on how many values the
    first drew, so changing the calibration split silently moved the applicability
    sample with nothing recording the link. Naming the stream after its purpose means
    a stage's result depends only on its own inputs. D111.
    """
    return np.random.default_rng([SEED, zlib.crc32(purpose.encode())])


def main() -> int:
    con = duckdb.connect(str(DUCKDB_PATH))
    frame = con.execute(FEATURE_SQL).df()
    trained = frame[frame["weak_label"].isin(TRAINED_CLASSES)].copy()
    columns = list(FEATURE_COLUMNS)

    fit_pool = training_rows(trained, "group_a")
    mask = stage_generator("calibration split").random(len(fit_pool)) < 0.2
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

    # Fitted only on rows whose features are observed. Filling nulls with zero put
    # every such row at one artificial coordinate in standardised space, which made
    # the mask report missingness rather than distance. D68.
    fit_observed = fit_set[columns].notna().all(axis=1)
    fit_rows = fit_set.loc[fit_observed, columns]
    scaler = StandardScaler().fit(fit_rows)
    fit_scaled = scaler.transform(fit_rows)
    index = stage_generator("applicability sample").choice(
        len(fit_scaled), size=min(40000, len(fit_scaled)), replace=False
    )
    neighbours = NearestNeighbors(n_neighbors=2).fit(fit_scaled[index])
    train_distance, _ = neighbours.kneighbors(fit_scaled[index])
    aoa_threshold = float(np.quantile(train_distance[:, 1], AOA_QUANTILE))

    # Stratified sample of the held out group, so every class is visible in the
    # interface even though flare is 1.16 percent of the record.
    held_out = test_rows(trained, "group_a")
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
    # A row with an unobserved feature is not assessable, and the console must say
    # so rather than show it as inside or outside the domain. None, not a boolean.
    sample_observed = sample[columns].notna().all(axis=1).to_numpy()
    outside: list[bool | None] = [None] * len(sample)
    if sample_observed.any():
        sample_scaled = scaler.transform(sample.loc[sample_observed, columns])
        distance, _ = neighbours.kneighbors(sample_scaled, n_neighbors=1)
        flags = distance[:, 0] > aoa_threshold
        for position, index_of_row in enumerate(np.flatnonzero(sample_observed)):
            outside[index_of_row] = bool(flags[position])
    print(
        f"applicability assessed on {int(sample_observed.sum())} of {len(sample)} "
        f"exported rows, {len(sample) - int(sample_observed.sum())} not assessable"
    )

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
                # None where the row is not assessable. Coercing that to False
                # would publish "inside the domain" for a row never assessed. D68.
                "outsideApplicability": None if outside[i] is None else bool(outside[i]),
                "priorCount90d": int(row["prior_count_90d"]),
                "priorCount30d": int(row["prior_count_30d"]),
                "nightFraction90d": optional_number(row["night_fraction_90d"], 3),
                "meanGapDays": optional_number(row["mean_gap_days"], 2),
                "nearestFlareBand": distance_band(row["flare_m"]),
                "nearestIndustrialM": optional_number(row["industrial_m"]),
                "nearestGemM": optional_number(row["gem_m_temporal"]),
            }
        )
    print(f"detections exported: {len(records)}", flush=True)

    # Persistent sources come from scripts/persistent_sources.py, which clusters by
    # great circle distance rather than rounding coordinates. Rounding to three
    # decimal places is about 110 m, smaller than a VIIRS pixel, so it fragmented
    # single sites and inflated the unregistered count from 21 to 39. D53.
    source_artifact = json.loads((ARTIFACT_DIR / "persistent_sources.json").read_text())
    sources = source_artifact["sources"]
    unregistered = sum(1 for s in sources if not s["registered"])
    print(f"persistent sources: {len(sources)}, unregistered {unregistered}", flush=True)

    b1 = json.loads((ARTIFACT_DIR / "b1_results.json").read_text())
    uncertainty = json.loads((ARTIFACT_DIR / "conformal_aoa_b2.json").read_text())
    b4 = json.loads((ARTIFACT_DIR / "b4_results.json").read_text())
    b4_support = json.loads((ARTIFACT_DIR / "b4_support.json").read_text())
    b4_rows = sum(group["rows"] for group in b4["groups"].values())

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
        # These are published in the interface, so they drift the moment a phase
        # closes and nobody rereads them. Three of the five were stale here: B4 now
        # runs end to end, phase 6 is decided rather than not started, and the
        # applicability domain is assessed on observed rows only. The B4 figures are
        # read from its artifacts because the typed ones went stale a second time.
        "notMeasured": {
            "B3 INSAT-3DS contextual thresholds": "not measured as a baseline. The "
            "contextual detector is built and drives the geostationary window, but it "
            "was never scored against B1 and B2 on the held out groups",
            "B4 foundation model probe": f"{b4['b4_status']}. The pipeline runs end to "
            f"end on real imagery; one scene reaches {b4_rows} held out detections and "
            f"no flare at all. Lifting it needs {b4_support['tiles_for_80_percent']} "
            "tiles",
            "KAALCHAKRA against B1 and B2": "not measured, and not estimable from a "
            "polar orbiting record. Phase 6 ships as specification, prototype and "
            "observability argument",
            "diurnal shift 2020 to 2024": "not measured, 2020 not ingested",
            "flare kernel family": "unresolved, not confirmed. Three tests failed "
            "for three different reasons",
            "reference coverage propensity model": "not built. Coverage is measured "
            "and reported, not modelled",
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
            "90 days and at least 5 detections, clustered by great circle distance at a "
            f"{source_artifact['chosen_radius_m']:.0f} m radius. A VIIRS detection is 375 m "
            "across, so that allows about one pixel of positional spread without merging "
            "separate sites. Registered means within 1 km of an OSM industrial feature, a GEM "
            "asset operating on the detection date, or a catalogued flare."
        ),
        "persistentSourceScope": (
            "Computed over the whole record, all Indian states and all three windows, not "
            "only the held out group. The detections layer is a group_a sample. The two "
            "layers therefore have different scopes and the legend says so."
        ),
        "detectionScope": (
            "Stratified sample from the group_a held out states only: Karnataka, Meghalaya, "
            "Odisha and Punjab."
        ),
        "clusterRadiusSweep": source_artifact["sweep"],
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
                # Absent from every attribution surface until 2026-09-05, despite a
                # scene having been downloaded, embedded and its derived metrics
                # published in section 10. D70.
                "name": "Copernicus Sentinel-2",
                "detail": "Contains modified Copernicus Sentinel data 2024, "
                "processed by the AgniNetra team. Used for the B4 site embedding",
                "url": "https://dataspace.copernicus.eu/",
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
