"""Settle two counterfactuals that results.md asserted without measuring.

Section 6 said a random split "would have shown coverage near nominal and hidden"
the conformal failure. Section 7 said holding out a northeastern state "lowers the
reported score relative to a split drawn from well mapped states". Neither split was
ever fitted. Both are one fit each.

A counterfactual is the easiest kind of claim to leave unmeasured, because it reads
as reasoning rather than as a result. These two are cheap, so they are measured.

Writes docs/counterfactual_splits.md and ml/artifacts/counterfactuals.json.
"""

import json
import os

# D59.
os.environ.setdefault("OMP_NUM_THREADS", "4")

import sys
from pathlib import Path

import duckdb
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import f1_score

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml.documents import provenance_line
from ml.features.matrix import FEATURE_COLUMNS, FEATURE_SQL
from ml.labels.splits import HELD_OUT_GROUPS
from ml.labels.weak import TRAINED_CLASSES
from ml.paths import ARTIFACT_DIR, DUCKDB_PATH, ROOT, ensure_dir

SEED = 20260904
NOMINAL = 0.90
# The northeastern state each held out group carries, which section 7 claimed
# depresses the score.
NORTHEASTERN = {"group_a": "Meghalaya", "group_b": "Assam", "group_c": "Mizoram"}


def fit(train, columns):
    model = HistGradientBoostingClassifier(
        max_iter=200, learning_rate=0.1, max_depth=None, random_state=SEED
    )
    model.fit(train[columns], train["weak_label"])
    return model


def conformal_coverage(model, calibrate, test, columns) -> tuple[float, float]:
    """Split conformal at 90 percent nominal. Returns coverage and empty set share."""
    classes = list(model.classes_)
    probabilities = model.predict_proba(calibrate[columns])
    truth = np.array([classes.index(label) for label in calibrate["weak_label"]])
    scores = 1.0 - probabilities[np.arange(len(truth)), truth]
    n = len(scores)
    level = min(1.0, np.ceil((n + 1) * NOMINAL) / n)
    threshold = float(np.quantile(scores, level, method="higher"))

    test_probabilities = model.predict_proba(test[columns])
    included = (1.0 - test_probabilities) <= threshold
    test_truth = np.array([classes.index(label) for label in test["weak_label"]])
    covered = included[np.arange(len(test_truth)), test_truth]
    empty = included.sum(axis=1) == 0
    return float(covered.mean()), float(empty.mean())


def main() -> int:
    connection = duckdb.connect(str(DUCKDB_PATH))
    frame = connection.execute(FEATURE_SQL).df()
    trained = frame[frame["weak_label"].isin(TRAINED_CLASSES)].copy()
    columns = list(FEATURE_COLUMNS)
    print(f"trained rows: {len(trained)}")

    # Shuffle into a separate frame. Reusing the shuffled one for the group fits
    # below would change them: row order moves HistGradientBoosting's early stopping
    # validation split, which is the same class of non determinism as D59. The group
    # arm must stay comparable to the published table, so it uses the original order.
    rng = np.random.default_rng(SEED)
    shuffled = trained.iloc[rng.permutation(len(trained))].reset_index(drop=True)
    n = len(shuffled)
    train_end, calibrate_end = int(0.6 * n), int(0.8 * n)
    random_train = shuffled.iloc[:train_end]
    random_calibrate = shuffled.iloc[train_end:calibrate_end]
    random_test = shuffled.iloc[calibrate_end:]

    model = fit(random_train, columns)
    coverage, empty = conformal_coverage(model, random_calibrate, random_test, columns)
    random_macro = f1_score(
        random_test["weak_label"],
        model.predict(random_test[columns]),
        labels=list(TRAINED_CLASSES),
        average="macro",
        zero_division=0,
    )
    print(
        f"\nrandom split: coverage {coverage:.4f} against nominal {NOMINAL:.2f}, "
        f"empty {empty:.2%}, macro F1 {random_macro:.3f}"
    )

    northeastern_rows = []
    for group, states in HELD_OUT_GROUPS.items():
        test_states = set(states)
        train = trained[~trained["state_name"].isin(test_states)]
        test_all = trained[trained["state_name"].isin(test_states)]
        dropped = NORTHEASTERN[group]
        test_without = test_all[test_all["state_name"] != dropped]
        group_model = fit(train, columns)
        with_all = f1_score(
            test_all["weak_label"],
            group_model.predict(test_all[columns]),
            labels=list(TRAINED_CLASSES),
            average="macro",
            zero_division=0,
        )
        without = f1_score(
            test_without["weak_label"],
            group_model.predict(test_without[columns]),
            labels=list(TRAINED_CLASSES),
            average="macro",
            zero_division=0,
        )
        n_dropped = len(test_all) - len(test_without)
        northeastern_rows.append((group, dropped, n_dropped, float(with_all), float(without)))
        print(
            f"{group}: macro F1 {with_all:.3f} with {dropped}, {without:.3f} without "
            f"({n_dropped} rows dropped)"
        )

    payload = {
        "seed": SEED,
        "omp_num_threads": os.environ.get("OMP_NUM_THREADS"),
        "random_split": {
            "coverage": round(coverage, 4),
            "empty_fraction": round(empty, 4),
            "macro_f1": round(float(random_macro), 4),
            "nominal": NOMINAL,
        },
        "northeastern": [
            {
                "group": g,
                "state": s,
                "rows": r,
                "macro_f1_with": round(a, 4),
                "macro_f1_without": round(b, 4),
            }
            for g, s, r, a, b in northeastern_rows
        ],
    }
    ensure_dir(ARTIFACT_DIR).joinpath("counterfactuals.json").write_text(
        json.dumps(payload, indent=2, allow_nan=False)
    )

    lines = [
        "# Two counterfactuals, measured instead of asserted",
        "",
        f"Regenerate: `uv run python {Path('scripts/counterfactual_splits.py')}`",
        provenance_line(__file__),
        "",
        f"Seed {SEED}, `OMP_NUM_THREADS=4`. D59.",
        "",
        "## Would a random split have hidden the conformal failure?",
        "",
        "Section 6 asserted it would. Fitted here on a 60/20/20 random train, calibrate",
        "and test split of the same rows, with the same estimator and nominal level.",
        "",
        "| Split | Empirical coverage | Nominal | Empty sets |",
        "|---|---|---|---|",
        f"| random | {coverage:.4f} | {NOMINAL:.2f} | {empty:.2%} |",
        "| group_a, spatially blocked | 0.9286 | 0.90 | 3.53 percent |",
        "| group_b, spatially blocked | 0.8097 | 0.90 | 10.88 percent |",
        "| group_c, spatially blocked | 0.8508 | 0.90 | 10.51 percent |",
        "",
        "## Does the northeastern state in each group depress the score?",
        "",
        "Section 7 asserted it does. Each group's model is fitted once and scored twice:",
        "on the full held out group, and on the same group with its northeastern state",
        "removed from the test set. The fit is identical, so only the evaluation",
        "population changes.",
        "",
        "Absolute values here sit within about 0.012 of the published B1 table for the",
        "reasons D59 records. The comparison that matters is within each row, where both",
        "columns come from one model and one run.",
        "",
        "| Group | State removed | Rows removed | Macro F1 with | Macro F1 without |",
        "|---|---|---|---|---|",
    ]
    for group, state, rows, with_all, without in northeastern_rows:
        lines.append(f"| {group} | {state} | {rows} | {with_all:.3f} | {without:.3f} |")
    lines.append("")
    (ROOT / "docs" / "counterfactual_splits.md").write_text("\n".join(lines))
    print("\nwrote docs/counterfactual_splits.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
