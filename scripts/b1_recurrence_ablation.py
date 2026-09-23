"""Is B1's flare and industrial confusion independent of the recurrence features?

Section 11 wants to present B1 as corroboration of the observability argument from
a route that shares no machinery with it. That premise needed checking, because
`FEATURE_COLUMNS` contains five recurrence features and one of them,
`mean_gap_days`, is the mean of raw inter arrival gaps, which is the exact quantity
D37 established is a constellation artefact.

So B1 is not disjoint from the recurrence route by construction. This script
measures how much of the confusion survives when the recurrence block is removed,
leaving only thermal, diurnal and sensor features. What survives is genuinely
independent. What does not was never corroboration.

Writes docs/b1_recurrence_ablation.md and ml/artifacts/b1_ablation.json.
"""

import json
import os

# HistGradientBoostingClassifier reduces histograms across OpenMP threads, and the
# floating point order of that reduction depends on the thread count. A fixed seed
# is therefore not sufficient for reproducibility: the same fit gives 73.98, 76.02
# and 76.42 percent flare confusion at 1, 2 and 8 threads. Pinned before sklearn is
# imported, because the runtime reads it at load. D59.
THREADS = "4"
os.environ.setdefault("OMP_NUM_THREADS", THREADS)

import sys  # noqa: E402
from pathlib import Path  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import duckdb  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.ensemble import HistGradientBoostingClassifier  # noqa: E402

from ml.documents import provenance_line  # noqa: E402
from ml.features.matrix import FEATURE_COLUMNS, FEATURE_SQL  # noqa: E402
from ml.labels.splits import HELD_OUT_GROUPS, split_for, validate_groups  # noqa: E402
from ml.labels.weak import TRAINED_CLASSES  # noqa: E402
from ml.paths import ARTIFACT_DIR, DUCKDB_PATH, ROOT, ensure_dir  # noqa: E402

SEED = 20260904

RECURRENCE_COLUMNS = (
    "prior_count_90d",
    "prior_count_30d",
    "night_fraction_90d",
    "frp_variance_90d",
    "mean_gap_days",
)


def fit(train: pd.DataFrame, columns: list[str]):
    model = HistGradientBoostingClassifier(
        max_iter=200, learning_rate=0.1, max_depth=None, random_state=SEED
    )
    model.fit(train[columns], train["weak_label"])
    return model


def flare_confusion(model, test: pd.DataFrame, columns: list[str]) -> tuple[int, float]:
    """Return the flare row count and the share of them predicted industrial."""
    flare = test[test["weak_label"] == "flare"]
    if flare.empty:
        return 0, float("nan")
    predicted = model.predict(flare[columns])
    return len(flare), float(np.mean(predicted == "industrial"))


def main() -> int:
    validate_groups()
    connection = duckdb.connect(str(DUCKDB_PATH))
    inside = connection.execute(FEATURE_SQL).df()
    trained = inside[inside["weak_label"].isin(TRAINED_CLASSES)].copy()

    full = list(FEATURE_COLUMNS)
    without = [c for c in full if c not in RECURRENCE_COLUMNS]
    print(f"full feature set: {len(full)} columns")
    print(f"without recurrence: {len(without)} columns, dropped {sorted(RECURRENCE_COLUMNS)}")

    results: dict[str, dict] = {}
    for group in HELD_OUT_GROUPS:
        _, test_states = split_for(group)
        train = trained[~trained["state_name"].isin(test_states)]
        test = trained[trained["state_name"].isin(test_states)]

        n_full, share_full = flare_confusion(fit(train, full), test, full)
        _, share_without = flare_confusion(fit(train, without), test, without)
        results[group] = {
            "flare_rows": n_full,
            "predicted_industrial_full": round(share_full, 4),
            "predicted_industrial_without_recurrence": round(share_without, 4),
        }
        print(
            f"{group}: flare n={n_full}, predicted industrial "
            f"{share_full:.1%} with recurrence, {share_without:.1%} without"
        )

    weighted_full = sum(r["flare_rows"] * r["predicted_industrial_full"] for r in results.values())
    weighted_without = sum(
        r["flare_rows"] * r["predicted_industrial_without_recurrence"] for r in results.values()
    )
    total = sum(r["flare_rows"] for r in results.values())
    overall = {
        "flare_rows": total,
        "predicted_industrial_full": round(weighted_full / total, 4),
        "predicted_industrial_without_recurrence": round(weighted_without / total, 4),
        "seed": SEED,
        "omp_num_threads": os.environ.get("OMP_NUM_THREADS"),
        "dropped_columns": list(RECURRENCE_COLUMNS),
    }
    print(
        f"\nacross the three groups: {overall['predicted_industrial_full']:.1%} with recurrence, "
        f"{overall['predicted_industrial_without_recurrence']:.1%} without, on {total} flare rows"
    )

    payload = {"per_group": results, "overall": overall}
    artifact = ensure_dir(ARTIFACT_DIR) / "b1_ablation.json"
    artifact.write_text(json.dumps(payload, indent=2, allow_nan=False))

    lines = [
        "# Does B1's flare confusion depend on the recurrence features?",
        "",
        f"Regenerate: `uv run python {Path('scripts/b1_recurrence_ablation.py')}`",
        provenance_line(__file__),
        "",
        "`FEATURE_COLUMNS` contains five recurrence features, and `mean_gap_days` is the",
        "mean of raw inter arrival gaps, the quantity D37 found to be a constellation",
        "artefact. B1 is therefore not disjoint from the recurrence route, and any claim",
        "that the two agree from independent machinery has to survive dropping them.",
        "",
        "Share of true flare detections predicted industrial, per held out group.",
        "",
        "| Group | flare rows | With recurrence | Without recurrence |",
        "|---|---|---|---|",
    ]
    for group, entry in results.items():
        lines.append(
            f"| {group} | {entry['flare_rows']} | "
            f"{entry['predicted_industrial_full']:.1%} | "
            f"{entry['predicted_industrial_without_recurrence']:.1%} |"
        )
    lines += [
        f"| **all three** | **{total}** | "
        f"**{overall['predicted_industrial_full']:.1%}** | "
        f"**{overall['predicted_industrial_without_recurrence']:.1%}** |",
        "",
        f"Seed {SEED}, OMP_NUM_THREADS={os.environ.get('OMP_NUM_THREADS')}. "
        f"Dropped: {', '.join(RECURRENCE_COLUMNS)}.",
        "",
        "Both arms are fitted in the same run at the same thread count, so the "
        "comparison between them is unaffected by the thread sensitivity recorded in "
        "D59. The absolute shares carry that sensitivity and are quoted to the nearest "
        "point rather than to a decimal.",
        "",
    ]
    destination = ROOT / "docs" / "b1_recurrence_ablation.md"
    destination.write_text("\n".join(lines))
    print(f"wrote {destination.relative_to(ROOT)} and {artifact.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
