"""Report the range a tuned constant produces, not the value that was chosen.

Three constants in this project were chosen once and published without a
sensitivity: B2's DBSCAN `eps` and `min_samples`, and `AOA_QUANTILE`. Sibling
thresholds do report one, the label radii and the persistent source clustering
radius among them, which is what made these visible.

The persistent source count already moved by 86 percent on an aggregation choice
that looked innocuous, D53, so a single published number from a tuned constant is
the shape this project has been wrong about before.

Writes docs/threshold_sensitivity.md and ml/artifacts/threshold_sensitivity.json.
"""

import json
import os

os.environ.setdefault("OMP_NUM_THREADS", "4")

import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import precision_recall_fscore_support
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml.documents import provenance_line
from ml.features.matrix import FEATURE_COLUMNS, FEATURE_SQL
from ml.labels.splits import test_rows, training_rows
from ml.labels.weak import TRAINED_CLASSES
from ml.paths import ARTIFACT_DIR, DUCKDB_PATH, ROOT, ensure_dir

SEED = 20260904
B2_SAMPLE = 60000
CHOSEN_EPS = 0.02
CHOSEN_MIN_SAMPLES = 8
CHOSEN_AOA_QUANTILE = 0.95

EPS_SWEEP = (0.005, 0.01, 0.02, 0.04, 0.08)
MIN_SAMPLES_SWEEP = (4, 6, 8, 12, 20)
AOA_SWEEP = (0.90, 0.925, 0.95, 0.975, 0.99)


def b2_score(coords, truth, eps: float, min_samples: int) -> tuple[float, float, float, int]:
    labels = DBSCAN(eps=eps, min_samples=min_samples).fit(coords).labels_
    sizes = pd.Series(labels).value_counts()
    persistent = {c for c, n in sizes.items() if c != -1 and n >= 20}
    predicted = np.where(pd.Series(labels).isin(persistent), "industrial", "not_industrial")
    precision, recall, f1, _ = precision_recall_fscore_support(
        truth, predicted, labels=["industrial"], zero_division=0
    )
    return float(precision[0]), float(recall[0]), float(f1[0]), len(persistent)


def main() -> int:
    con = duckdb.connect(str(DUCKDB_PATH))
    rows = con.execute(
        f"SELECT * FROM ({FEATURE_SQL}) ORDER BY md5(detection_id) LIMIT {B2_SAMPLE}"
    ).df()
    rows = rows[rows["weak_label"].isin(TRAINED_CLASSES)].copy()
    day = pd.to_datetime(rows["acq_date_ist"]).astype("int64") / 86_400_000_000_000
    coords = np.column_stack([rows["latitude"], rows["longitude"], day * 0.01])
    truth = np.where(rows["weak_label"] == "industrial", "industrial", "not_industrial")

    eps_rows = []
    print("B2, eps swept at the chosen min_samples:")
    for eps in EPS_SWEEP:
        p, r, f1, n = b2_score(coords, truth, eps, CHOSEN_MIN_SAMPLES)
        eps_rows.append({"eps": eps, "precision": p, "recall": r, "f1": f1, "clusters": n})
        mark = "  chosen" if eps == CHOSEN_EPS else ""
        print(f"  eps {eps:<6} P {p:.3f}  R {r:.3f}  F1 {f1:.3f}  persistent {n}{mark}")

    ms_rows = []
    print("\nB2, min_samples swept at the chosen eps:")
    for min_samples in MIN_SAMPLES_SWEEP:
        p, r, f1, n = b2_score(coords, truth, CHOSEN_EPS, min_samples)
        ms_rows.append(
            {"min_samples": min_samples, "precision": p, "recall": r, "f1": f1, "clusters": n}
        )
        mark = "  chosen" if min_samples == CHOSEN_MIN_SAMPLES else ""
        print(
            f"  min_samples {min_samples:<4} P {p:.3f}  R {r:.3f}  F1 {f1:.3f}  "
            f"persistent {n}{mark}"
        )

    # AOA_QUANTILE on group_a, assessed rows only, matching the published method.
    frame = con.execute(FEATURE_SQL).df()
    trained = frame[frame["weak_label"].isin(TRAINED_CLASSES)].copy()
    columns = list(FEATURE_COLUMNS)
    fit_set = training_rows(trained, "group_a")
    test = test_rows(trained, "group_a")
    fit_observed = fit_set[columns].notna().all(axis=1)
    test_observed = test[columns].notna().all(axis=1).to_numpy()

    scaler = StandardScaler().fit(fit_set.loc[fit_observed, columns])
    fit_scaled = scaler.transform(fit_set.loc[fit_observed, columns])
    rng = np.random.default_rng(SEED)
    index = rng.choice(len(fit_scaled), size=min(40000, len(fit_scaled)), replace=False)
    neighbours = NearestNeighbors(n_neighbors=2).fit(fit_scaled[index])
    train_distance, _ = neighbours.kneighbors(fit_scaled[index])
    test_scaled = scaler.transform(test.loc[test_observed, columns])
    test_distance, _ = neighbours.kneighbors(test_scaled, n_neighbors=1)

    model = HistGradientBoostingClassifier(
        max_iter=200, learning_rate=0.1, max_depth=None, random_state=SEED
    ).fit(fit_set[columns], fit_set["weak_label"])
    predicted = model.predict(test.loc[test_observed, columns])
    truth_labels = test["weak_label"].to_numpy()[test_observed]

    aoa_rows = []
    print("\nAOA_QUANTILE swept on group_a, assessed rows only:")
    for quantile in AOA_SWEEP:
        threshold = float(np.quantile(train_distance[:, 1], quantile))
        outside = test_distance[:, 0] > threshold
        inside_acc = (
            float((predicted[~outside] == truth_labels[~outside]).mean())
            if (~outside).sum()
            else None
        )
        outside_acc = (
            float((predicted[outside] == truth_labels[outside]).mean()) if outside.sum() else None
        )
        aoa_rows.append(
            {
                "quantile": quantile,
                "outside_fraction": float(outside.mean()),
                "accuracy_inside": inside_acc,
                "accuracy_outside": outside_acc,
            }
        )
        mark = "  chosen" if quantile == CHOSEN_AOA_QUANTILE else ""
        outside_text = "n/a" if outside_acc is None else f"{outside_acc:.3f}"
        print(
            f"  q {quantile:<6} outside {outside.mean():.2%}  inside acc "
            f"{inside_acc:.3f}  outside acc {outside_text}{mark}"
        )

    payload = {
        "seed": SEED,
        "b2_eps": eps_rows,
        "b2_min_samples": ms_rows,
        "aoa_quantile": aoa_rows,
        "chosen": {
            "eps": CHOSEN_EPS,
            "min_samples": CHOSEN_MIN_SAMPLES,
            "aoa_quantile": CHOSEN_AOA_QUANTILE,
        },
    }
    ensure_dir(ARTIFACT_DIR).joinpath("threshold_sensitivity.json").write_text(
        json.dumps(payload, indent=2, allow_nan=False)
    )

    f1s = [row["f1"] for row in eps_rows]
    ms_f1s = [row["f1"] for row in ms_rows]
    outs = [row["outside_fraction"] for row in aoa_rows]
    lines = [
        "# Sensitivity of the three tuned constants",
        "",
        f"Regenerate: `uv run python {Path('scripts/threshold_sensitivity.py')}`",
        provenance_line(__file__),
        "",
        f"Seed {SEED}, `OMP_NUM_THREADS=4`. Each sweep varies one constant and holds",
        "the others at the published value.",
        "",
        "## B2, DBSCAN eps",
        "",
        "| eps | Precision | Recall | F1 | Persistent clusters |",
        "|---|---|---|---|---|",
    ]
    for row in eps_rows:
        mark = " **chosen**" if row["eps"] == CHOSEN_EPS else ""
        lines.append(
            f"| {row['eps']}{mark} | {row['precision']:.3f} | {row['recall']:.3f} | "
            f"{row['f1']:.3f} | {row['clusters']} |"
        )
    lines += [
        "",
        f"F1 ranges {min(f1s):.3f} to {max(f1s):.3f} across a sixteenfold change in eps.",
        "",
        "## B2, DBSCAN min_samples",
        "",
        "| min_samples | Precision | Recall | F1 | Persistent clusters |",
        "|---|---|---|---|---|",
    ]
    for row in ms_rows:
        mark = " **chosen**" if row["min_samples"] == CHOSEN_MIN_SAMPLES else ""
        lines.append(
            f"| {row['min_samples']}{mark} | {row['precision']:.3f} | {row['recall']:.3f} | "
            f"{row['f1']:.3f} | {row['clusters']} |"
        )
    lines += [
        "",
        f"F1 ranges {min(ms_f1s):.3f} to {max(ms_f1s):.3f} across a fivefold change.",
        "",
        "## AOA_QUANTILE, group_a, assessed rows only",
        "",
        "| Quantile | Outside the domain | Accuracy inside | Accuracy outside |",
        "|---|---|---|---|",
    ]
    for row in aoa_rows:
        mark = " **chosen**" if row["quantile"] == CHOSEN_AOA_QUANTILE else ""
        outside_text = (
            "n/a" if row["accuracy_outside"] is None else f"{row['accuracy_outside']:.3f}"
        )
        lines.append(
            f"| {row['quantile']}{mark} | {row['outside_fraction']:.2%} | "
            f"{row['accuracy_inside']:.3f} | {outside_text} |"
        )
    lines += [
        "",
        f"The outside fraction ranges {min(outs):.2%} to {max(outs):.2%}, which is by",
        "construction: the quantile sets it. What matters is whether accuracy inside",
        "stays above accuracy outside across the sweep, because that is the claim the",
        "mask supports. It is reported above rather than asserted.",
        "",
    ]
    (ROOT / "docs" / "threshold_sensitivity.md").write_text("\n".join(lines))
    print("\nwrote docs/threshold_sensitivity.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
