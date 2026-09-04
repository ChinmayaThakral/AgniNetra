#!/usr/bin/env python3
"""B1: gradient boosted trees, evaluated on four held out groups.

Contract, D32. Option A is the headline: fit on the true prior with no class
weighting. Option C, capping the majority class, is a reported ablation. Per class
precision, recall and F1 with precision recall curves; macro F1 is not the headline
on a class holding 1.16 percent of rows.

Three trained classes, D33. Wildfire has no weak label and cannot be recovered.

Before any of that, a leakage demonstration. The weak label is a deterministic
function of the reference distances and the land cover class, so a model given
those recovers the rule rather than learning attribution. It is fitted once to show
the number and never evaluated as a baseline. D43.

Usage:
    uv run python scripts/train_b1.py
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
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import classification_report, confusion_matrix

from ml.features.matrix import EXTERNAL_SQL, FEATURE_COLUMNS, FEATURE_SQL
from ml.labels.splits import HELD_OUT_GROUPS, split_for, validate_groups
from ml.labels.weak import TRAINED_CLASSES
from ml.paths import ARTIFACT_DIR, DUCKDB_PATH, ROOT, ensure_dir

SEED = 20260904
OUT = ROOT / "docs" / "b1_results.md"
MAJORITY_CAP = 0.40


def load() -> tuple[pd.DataFrame, pd.DataFrame]:
    con = duckdb.connect(str(DUCKDB_PATH))
    inside = con.execute(FEATURE_SQL).df()
    outside = con.execute(EXTERNAL_SQL).df()
    return inside, outside


def fit(train: pd.DataFrame, columns: list[str], seed: int = SEED):
    model = HistGradientBoostingClassifier(
        max_iter=200, learning_rate=0.1, max_depth=None, random_state=seed
    )
    model.fit(train[columns], train["weak_label"])
    return model


def evaluate(model, frame: pd.DataFrame, columns: list[str]) -> dict:
    if frame.empty:
        return {}
    predicted = model.predict(frame[columns])
    report = classification_report(
        frame["weak_label"],
        predicted,
        labels=list(TRAINED_CLASSES),
        output_dict=True,
        zero_division=0,
    )
    return report


def main() -> int:
    np.random.seed(SEED)
    validate_groups()
    inside, outside = load()
    print(f"India assigned rows: {len(inside)}, external rows: {len(outside)}", flush=True)

    trained = inside[inside["weak_label"].isin(TRAINED_CLASSES)].copy()
    external = outside[outside["weak_label"].isin(TRAINED_CLASSES)].copy()
    print(f"trained class rows: {len(trained)}, external trained class rows: {len(external)}")
    print("\nclass prior on the trained rows:")
    for name, count in trained["weak_label"].value_counts().items():
        print(f"  {name:14s} {count:7d}  {count / len(trained):.2%}")

    columns = list(FEATURE_COLUMNS)

    # Leakage demonstration. Fitted, reported, and never used as a baseline.
    leak_columns = [*columns, "flare_m", "industrial_m", "gem_m_temporal", "landcover_code"]
    _, test_states = split_for("group_a")
    leak_train = trained[~trained["state_name"].isin(test_states)]
    leak_test = trained[trained["state_name"].isin(test_states)]
    leak_model = fit(leak_train, leak_columns)
    leak_report = evaluate(leak_model, leak_test, leak_columns)
    clean_model = fit(leak_train, columns)
    clean_report = evaluate(clean_model, leak_test, columns)
    print("\nleakage demonstration on group_a, macro F1:")
    print(f"  with the label defining columns: {leak_report['macro avg']['f1-score']:.4f}")
    print(f"  without them, the real baseline:  {clean_report['macro avg']['f1-score']:.4f}")

    results: dict[str, dict] = {}
    print("\n=== option A, no class weighting, per group ===", flush=True)
    for group in HELD_OUT_GROUPS:
        _, test_states = split_for(group)
        train = trained[~trained["state_name"].isin(test_states)]
        test = trained[trained["state_name"].isin(test_states)]
        model = fit(train, columns)
        report = evaluate(model, test, columns)
        results[group] = report
        print(f"\n{group}: train {len(train)}, test {len(test)}")
        for name in TRAINED_CLASSES:
            row = report[name]
            print(
                f"  {name:14s} P {row['precision']:.3f}  R {row['recall']:.3f}  "
                f"F1 {row['f1-score']:.3f}  n {int(row['support'])}"
            )
        print(f"  macro F1 {report['macro avg']['f1-score']:.3f}")

    # External group: trained on every Indian state, tested outside India.
    model_all = fit(trained, columns)
    ext_report = evaluate(model_all, external, columns)
    results["group_d_external"] = ext_report
    print(f"\ngroup_d_external: train {len(trained)}, test {len(external)}")
    for name in TRAINED_CLASSES:
        row = ext_report[name]
        print(
            f"  {name:14s} P {row['precision']:.3f}  R {row['recall']:.3f}  "
            f"F1 {row['f1-score']:.3f}  n {int(row['support'])}"
        )
    print(f"  macro F1 {ext_report['macro avg']['f1-score']:.3f}")

    state_f1 = [results[g]["macro avg"]["f1-score"] for g in HELD_OUT_GROUPS]
    spread = max(state_f1) - min(state_f1)
    ext_f1 = ext_report["macro avg"]["f1-score"]
    drop = float(np.mean(state_f1)) - ext_f1
    print(f"\nstate group macro F1: mean {np.mean(state_f1):.3f}, spread {spread:.3f}")
    print(f"external macro F1: {ext_f1:.3f}, drop below the state mean {drop:.3f}")
    print(f"drop exceeds the state spread: {drop > spread}")

    # Option C ablation: cap the majority class.
    print("\n=== option C ablation, majority capped ===", flush=True)
    capped_results: dict[str, float] = {}
    for group in HELD_OUT_GROUPS:
        _, test_states = split_for(group)
        train = trained[~trained["state_name"].isin(test_states)]
        test = trained[trained["state_name"].isin(test_states)]
        minority_n = len(train[train["weak_label"] != "agricultural"])
        target = int(MAJORITY_CAP / (1 - MAJORITY_CAP) * minority_n)
        majority = train[train["weak_label"] == "agricultural"]
        keep = majority.sample(n=min(target, len(majority)), random_state=SEED)
        capped = pd.concat([train[train["weak_label"] != "agricultural"], keep])
        model = fit(capped, columns)
        report = evaluate(model, test, columns)
        capped_results[group] = report["macro avg"]["f1-score"]
        print(
            f"  {group}: macro F1 {report['macro avg']['f1-score']:.3f} "
            f"(option A {results[group]['macro avg']['f1-score']:.3f}), "
            f"train {len(capped)}"
        )

    ensure_dir(ARTIFACT_DIR)
    (ARTIFACT_DIR / "b1_results.json").write_text(
        json.dumps(
            {
                "option_a": results,
                "option_c_macro_f1": capped_results,
                "leakage_macro_f1": leak_report["macro avg"]["f1-score"],
                "clean_macro_f1": clean_report["macro avg"]["f1-score"],
                "seed": SEED,
            },
            indent=1,
            default=float,
        )
    )
    # Confusion matrix on group_a for the figure stage.
    predicted = clean_model.predict(leak_test[columns])
    matrix = confusion_matrix(leak_test["weak_label"], predicted, labels=list(TRAINED_CLASSES))
    np.save(ARTIFACT_DIR / "b1_confusion_group_a.npy", matrix)
    print(f"\nartifacts written to {ARTIFACT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
