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

# Pinned before any estimator library loads, as a precaution only. D59 blamed thread
# count for fits that did not reproduce from their seed; the cause was an unordered
# feature query, fixed by ordering it on detection_id, and thread count makes no
# difference once rows arrive in a fixed order. D66.
os.environ.setdefault("OMP_NUM_THREADS", "4")


import json
import sys
import zlib
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
from ml.labels.splits import HELD_OUT_GROUPS, test_rows, training_rows
from ml.labels.weak import TRAINED_CLASSES
from ml.paths import ARTIFACT_DIR, DUCKDB_PATH, ensure_dir

SEED = 20260904
NOMINAL = 0.90
AOA_QUANTILE = 0.95
B2_SAMPLE = 60000


def group_generator(group: str) -> np.random.Generator:
    """An independent stream per group, derived from the group's name.

    A single generator shared across the loop made every group's result depend on
    how many draws the groups before it happened to make, so group_b and group_c
    moved whenever anything above them changed and nothing recorded the dependency.
    Deriving the seed from the name rather than from the loop index means adding,
    removing or reordering a group does not move the others. D111.
    """
    return np.random.default_rng([SEED, zlib.crc32(group.encode())])


def main() -> int:
    con = duckdb.connect(str(DUCKDB_PATH))
    frame = con.execute(FEATURE_SQL).df()
    trained = frame[frame["weak_label"].isin(TRAINED_CLASSES)].copy()
    columns = list(FEATURE_COLUMNS)
    print(f"trained rows: {len(trained)}", flush=True)

    summary: dict[str, dict] = {}

    for group in HELD_OUT_GROUPS:
        rng = group_generator(group)
        pool = training_rows(trained, group)
        test = test_rows(trained, group)

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
        #
        # This previously called `.fillna(0.0)` on both the fit set and the test set.
        # A zero in a standardised space is a coordinate, not a neutral, so every row
        # with an unobserved recurrence feature was moved to one artificial point
        # before its distance to the training distribution was measured. On the
        # current data 60 to 73 percent of rows carry at least one such null, so the
        # mask was substantially reporting missingness rather than distance. D68.
        #
        # The applicability domain is a statement about whether a row can be
        # assessed at all, which makes imputing it self defeating. Rows with an
        # unobserved feature are not assessed and are counted instead.
        fit_observed = fit_set[columns].notna().all(axis=1).to_numpy()
        test_observed = test[columns].notna().all(axis=1).to_numpy()
        assessable = int(test_observed.sum())

        if fit_observed.sum() < 2 or assessable == 0:
            outside_fraction = None
            inside_correct = None
            outside_correct = None
            aoa_threshold = None
        else:
            fit_rows = fit_set.loc[fit_observed, columns]
            scaler = StandardScaler().fit(fit_rows)
            fit_scaled = scaler.transform(fit_rows)
            sample_index = rng.choice(
                len(fit_scaled), size=min(40000, len(fit_scaled)), replace=False
            )
            neighbours = NearestNeighbors(n_neighbors=2).fit(fit_scaled[sample_index])
            train_distance, _ = neighbours.kneighbors(fit_scaled[sample_index])
            aoa_threshold = float(np.quantile(train_distance[:, 1], AOA_QUANTILE))
            test_scaled = scaler.transform(test.loc[test_observed, columns])
            test_distance, _ = neighbours.kneighbors(test_scaled, n_neighbors=1)
            outside = test_distance[:, 0] > aoa_threshold
            outside_fraction = float(outside.mean())

            predicted = np.array(classes)[test_probs.argmax(axis=1)][test_observed]
            truth = test["weak_label"].to_numpy()[test_observed]
            inside_correct = (
                float((predicted[~outside] == truth[~outside]).mean()) if (~outside).sum() else None
            )
            outside_correct = (
                float((predicted[outside] == truth[outside]).mean()) if outside.sum() else None
            )

        # The superseded imputed variant, recomputed rather than transcribed.
        #
        # The before and after comparison in the results is evidence that the
        # imputation was adding noise whose sign varied by group, and the before
        # figures had no source of their own. Freezing them as literals would be the
        # defect D91 names, so the old behaviour is recomputed here under a name that
        # says it is superseded. Nothing downstream reads it. D110.
        imputed_outside = None
        if fit_observed.sum() >= 2:
            fit_filled = fit_set[columns].fillna(0.0)
            imputed_scaler = StandardScaler().fit(fit_filled)
            imputed_fit = imputed_scaler.transform(fit_filled)
            # Its own generator. Drawing from the shared rng advanced the stream and
            # silently moved group_b and group_c, which are downstream of it in the
            # loop: group_a was unchanged because it ran before the first draw. A
            # diagnostic that perturbs the measurement it is diagnosing is worse than
            # no diagnostic. D59 is the same class.
            imputed_rng = group_generator(f"{group}:superseded")
            imputed_sample = imputed_rng.choice(
                len(imputed_fit), size=min(40000, len(imputed_fit)), replace=False
            )
            imputed_nn = NearestNeighbors(n_neighbors=2).fit(imputed_fit[imputed_sample])
            imputed_train, _ = imputed_nn.kneighbors(imputed_fit[imputed_sample])
            imputed_threshold = float(np.quantile(imputed_train[:, 1], AOA_QUANTILE))
            imputed_test = imputed_scaler.transform(test[columns].fillna(0.0))
            imputed_distance, _ = imputed_nn.kneighbors(imputed_test, n_neighbors=1)
            imputed_outside = float((imputed_distance[:, 0] > imputed_threshold).mean())

        print(f"\n{group}")
        print(f"  conformal, nominal {NOMINAL:.0%}: empirical coverage {coverage:.4f}")
        print(f"  mean prediction set size {set_sizes.mean():.3f} of {len(classes)} classes")
        print(
            f"  singleton sets {float((set_sizes == 1).mean()):.2%}, "
            f"empty sets {float((set_sizes == 0).mean()):.2%}"
        )
        not_assessable = len(test) - assessable
        print(
            f"  applicability assessed on {assessable} of {len(test)} rows, "
            f"{not_assessable} not assessable because a feature is unobserved"
        )
        if outside_fraction is None:
            print("  outside the applicability domain: not measured, no assessable rows")
        else:
            print(f"  outside the applicability domain: {outside_fraction:.2%} of assessable")
        inside_text = "n/a" if inside_correct is None else f"{inside_correct:.3f}"
        outside_text = "n/a" if outside_correct is None else f"{outside_correct:.3f}"
        print(f"  accuracy inside the domain {inside_text}, outside {outside_text}")
        summary[group] = {
            "coverage": coverage,
            "nominal": NOMINAL,
            "mean_set_size": float(set_sizes.mean()),
            "singleton_fraction": float((set_sizes == 1).mean()),
            "empty_fraction": float((set_sizes == 0).mean()),
            "outside_aoa_fraction": outside_fraction,
            "accuracy_inside_aoa": inside_correct,
            "accuracy_outside_aoa": outside_correct,
            "aoa_assessable_rows": assessable,
            "aoa_not_assessable_rows": len(test) - assessable,
            "aoa_assessable_fraction": round(assessable / len(test), 4) if len(test) else None,
            "superseded_imputed_outside_aoa_fraction": imputed_outside,
        }
        if imputed_outside is not None:
            print(
                f"  superseded imputed variant, outside the domain: {imputed_outside:.2%} "
                f"against {outside_fraction:.2%} measured"
                if outside_fraction is not None
                else f"  superseded imputed variant: {imputed_outside:.2%}"
            )

    # B2, spatiotemporal density clustering, scored on industrial alone.
    print("\n=== B2, spatiotemporal density clustering ===", flush=True)
    # Database side randomness is not reproducible here, and the seeded form that
    # replaced the unseeded one was not either. `setseed()` plus `ORDER BY random()`
    # returned a different 60000 row sample on roughly one run in four: three
    # identical digests then a fourth that differed. It is flaky rather than
    # deterministic, which is why a small check passed and the claim was wrong. D68.
    #
    # Sampled by a stable hash of the detection identifier instead. No RNG state, no
    # ordering ambiguity, identical across machines and DuckDB versions, and the
    # selection is a pure function of the identifier and the sample size.
    b2_rows = con.execute(
        f"""
        SELECT * FROM ({FEATURE_SQL})
        ORDER BY md5(detection_id)
        LIMIT {B2_SAMPLE}
        """
    ).df()
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
