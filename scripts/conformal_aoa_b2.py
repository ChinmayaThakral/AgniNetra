#!/usr/bin/env python3
"""Split conformal prediction sets, the applicability domain mask, and B2.

Conformal. Calibrated on a held out slice of the training states, never on the test
group, so coverage is a genuine out of sample guarantee. The nonconformity score is
one minus the predicted probability of the true class. Empirical coverage is
measured against the nominal level and reported whether or not it matches.

Applicability domain. Meyer and Pebesma style: distance in standardised feature
space from each test point to its nearest training point, thresholded at a quantile
of the training set's own nearest neighbour distances. Points beyond it are outside
the domain and the system should abstain rather than guess.

B2. Spatiotemporal density clustering, the published prior art. It is unsupervised
and binary by construction: a cell in a dense persistent cluster is industrial, a
cell that is not is not. It is scored on the industrial class alone, because that
is the only claim it makes.

Usage:
    uv run python scripts/conformal_aoa_b2.py
"""

import os

# Pinned before any estimator library loads. Thread count changes the floating
# point reduction order inside sklearn's histogram builders, and random_state does
# not constrain it, so a fixed seed alone does not reproduce a fit. D59.
os.environ.setdefault("OMP_NUM_THREADS", "4")


import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import duckdb
import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import precision_recall_fscore_support
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import StandardScaler

from ml.features.matrix import FEATURE_COLUMNS, FEATURE_SQL
from ml.labels.splits import HELD_OUT_GROUPS, split_for
from ml.labels.weak import TRAINED_CLASSES
from ml.paths import ARTIFACT_DIR, DUCKDB_PATH, ensure_dir

SEED = 20260904
NOMINAL = 0.90
AOA_QUANTILE = 0.95
B2_SAMPLE = 60000


def main() -> int:
    rng = np.random.default_rng(SEED)
    con = duckdb.connect(str(DUCKDB_PATH))
    frame = con.execute(FEATURE_SQL).df()
    trained = frame[frame["weak_label"].isin(TRAINED_CLASSES)].copy()
    columns = list(FEATURE_COLUMNS)
    print(f"trained rows: {len(trained)}", flush=True)

    summary: dict[str, dict] = {}

    for group in HELD_OUT_GROUPS:
        _, test_states = split_for(group)
        pool = trained[~trained["state_name"].isin(test_states)]
        test = trained[trained["state_name"].isin(test_states)]

        # Calibration split, taken from the training states only.
        mask = rng.random(len(pool)) < 0.2
        calibration = pool[mask]
        fit_set = pool[~mask]

        model = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.1, random_state=SEED)
        model.fit(fit_set[columns], fit_set["weak_label"])
        classes = list(model.classes_)

        cal_probs = model.predict_proba(calibration[columns])
        true_index = [classes.index(label) for label in calibration["weak_label"]]
        scores = 1.0 - cal_probs[np.arange(len(calibration)), true_index]
        n = len(scores)
        level = min(1.0, np.ceil((n + 1) * NOMINAL) / n)
        threshold = float(np.quantile(scores, level))

        test_probs = model.predict_proba(test[columns])
        included = test_probs >= (1.0 - threshold)
        test_true = np.array([classes.index(label) for label in test["weak_label"]])
        covered = included[np.arange(len(test)), test_true]
        coverage = float(covered.mean())
        set_sizes = included.sum(axis=1)

        # Applicability domain in standardised feature space.
        scaler = StandardScaler().fit(fit_set[columns].fillna(0.0))
        fit_scaled = scaler.transform(fit_set[columns].fillna(0.0))
        sample_index = rng.choice(len(fit_scaled), size=min(40000, len(fit_scaled)), replace=False)
        neighbours = NearestNeighbors(n_neighbors=2).fit(fit_scaled[sample_index])
        train_distance, _ = neighbours.kneighbors(fit_scaled[sample_index])
        aoa_threshold = float(np.quantile(train_distance[:, 1], AOA_QUANTILE))
        test_scaled = scaler.transform(test[columns].fillna(0.0))
        test_distance, _ = neighbours.kneighbors(test_scaled, n_neighbors=1)
        outside = test_distance[:, 0] > aoa_threshold
        outside_fraction = float(outside.mean())

        inside_correct = None
        if (~outside).sum() > 0:
            predicted = np.array(classes)[test_probs.argmax(axis=1)]
            inside_correct = float(
                (predicted[~outside] == test["weak_label"].to_numpy()[~outside]).mean()
            )
            outside_correct = (
                float((predicted[outside] == test["weak_label"].to_numpy()[outside]).mean())
                if outside.sum()
                else None
            )

        print(f"\n{group}")
        print(f"  conformal, nominal {NOMINAL:.0%}: empirical coverage {coverage:.4f}")
        print(f"  mean prediction set size {set_sizes.mean():.3f} of {len(classes)} classes")
        print(
            f"  singleton sets {float((set_sizes == 1).mean()):.2%}, "
            f"empty sets {float((set_sizes == 0).mean()):.2%}"
        )
        print(f"  outside the applicability domain: {outside_fraction:.2%}")
        outside_text = "n/a" if outside_correct is None else f"{outside_correct:.3f}"
        print(f"  accuracy inside the domain {inside_correct:.3f}, outside {outside_text}")
        summary[group] = {
            "coverage": coverage,
            "nominal": NOMINAL,
            "mean_set_size": float(set_sizes.mean()),
            "singleton_fraction": float((set_sizes == 1).mean()),
            "empty_fraction": float((set_sizes == 0).mean()),
            "outside_aoa_fraction": outside_fraction,
            "accuracy_inside_aoa": inside_correct,
            "accuracy_outside_aoa": outside_correct,
        }

    # B2, spatiotemporal density clustering, scored on industrial alone.
    print("\n=== B2, spatiotemporal density clustering ===", flush=True)
    b2_rows = con.execute(FEATURE_SQL + " ORDER BY random() LIMIT " + str(B2_SAMPLE)).df()
    b2_rows = b2_rows[b2_rows["weak_label"].isin(TRAINED_CLASSES)].copy()
    day = pd.to_datetime(b2_rows["acq_date_ist"]).astype("int64") / 86_400_000_000_000
    # Scale time so one day is comparable to about 1 km of space at these latitudes.
    coords = np.column_stack([b2_rows["latitude"], b2_rows["longitude"], day * 0.01])
    clustering = DBSCAN(eps=0.02, min_samples=8).fit(coords)
    b2_rows["cluster"] = clustering.labels_
    sizes = b2_rows["cluster"].value_counts()
    persistent = {c for c, n in sizes.items() if c != -1 and n >= 20}
    predicted = np.where(b2_rows["cluster"].isin(persistent), "industrial", "not_industrial")
    truth = np.where(b2_rows["weak_label"] == "industrial", "industrial", "not_industrial")
    precision, recall, f1, _ = precision_recall_fscore_support(
        truth, predicted, labels=["industrial"], zero_division=0
    )
    print(f"  sample {len(b2_rows)}, clusters {len(sizes) - 1}, persistent {len(persistent)}")
    print(f"  industrial: P {precision[0]:.3f}  R {recall[0]:.3f}  F1 {f1[0]:.3f}")
    summary["b2_industrial"] = {
        "precision": float(precision[0]),
        "recall": float(recall[0]),
        "f1": float(f1[0]),
        "sample": len(b2_rows),
        "clusters": int(len(sizes) - 1),
        "persistent_clusters": len(persistent),
    }

    ensure_dir(ARTIFACT_DIR)
    (ARTIFACT_DIR / "conformal_aoa_b2.json").write_text(json.dumps(summary, indent=1))
    print(f"\nwritten to {ARTIFACT_DIR / 'conformal_aoa_b2.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
