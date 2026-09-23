#!/usr/bin/env python3
"""Figures for the review. Every one captioned with its window and its snapshot.

Usage:
    uv run python scripts/review_figures.py
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
import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import PrecisionRecallDisplay

from ml.features.matrix import FEATURE_COLUMNS, FEATURE_SQL
from ml.labels.splits import split_for
from ml.labels.weak import TRAINED_CLASSES
from ml.paths import ARTIFACT_DIR, DUCKDB_PATH, ROOT, ensure_dir

FIG = ROOT / "docs" / "figures"
SEED = 20260904
SNAPSHOT = (
    "FIRMS windows 2023-10-01 to 2023-11-30, 2024-10-01 to 2024-11-30, "
    "2026-06-06 to 2026-09-03. OSM snapshot 2026-09-02T20:20:51Z sequence 4895. "
    "GEM releases June to August 2026. WorldCover v200 2021."
)
COLOURS = {"flare": "#b00020", "industrial": "#c46210", "agricultural": "#3f7f4f"}


def caption(fig, text: str) -> None:
    fig.text(0.01, 0.005, text + "\n" + SNAPSHOT, fontsize=7.2, color="#444444", va="bottom")


def figure_lift() -> None:
    # Read from the artifact rather than typed. The typed values included with GEM lifts
    # divided by an OpenStreetMap only background, so the figure showed 16.40x where the
    # measurement is 13.35x, and with no artifact registered the freshness check could
    # never see it. D122.
    lifts = json.loads((ARTIFACT_DIR / "lift_with_gem.json").read_text())
    keys = ["monsoon 2026", "burning season 2023", "burning season 2024"]
    windows = ["monsoon 2026", "season 2023", "season 2024"]
    names = {
        "industrial": "industrial",
        "agricultural": "agricultural",
        "wildfire": "wildfire, withdrawn rule",
    }
    before = {k: [lifts[w][v]["lift_before"] for w in keys] for k, v in names.items()}
    after = {k: [lifts[w][v]["lift_after"] for w in keys] for k, v in names.items()}
    fig, axes = plt.subplots(1, 3, figsize=(12, 4.2), sharey=True)
    x = np.arange(len(windows))
    for axis, (name, colour) in zip(
        axes,
        [("industrial", "#c46210"), ("agricultural", "#3f7f4f"), ("wildfire", "#2b6cb0")],
        strict=True,
    ):
        axis.bar(x - 0.19, before[name], 0.36, label="OSM and EOG only", color=colour, alpha=0.45)
        axis.bar(x + 0.19, after[name], 0.36, label="plus GEM assets", color=colour)
        axis.axhline(1.0, color="#333333", linestyle=":", linewidth=1)
        axis.set_xticks(x)
        axis.set_xticklabels(windows, fontsize=8, rotation=12)
        axis.set_title(f"{name} rule", fontsize=10, loc="left")
        axis.set_yscale("log")
        for spine in ("top", "right"):
            axis.spines[spine].set_visible(False)
    axes[0].set_ylabel("lift over background, log scale")
    axes[0].legend(fontsize=7.5, frameon=False)
    fig.suptitle(
        "Weak label lift by window, before and after the GEM trackers",
        fontsize=12,
        x=0.01,
        ha="left",
    )
    caption(
        fig,
        "Lift is the measured class share divided by the share a uniformly placed detection "
        "inside India would pick up. The dotted line at 1 is no information.\n"
        "Agricultural rises above 1 only in burning season; wildfire is below 1 everywhere "
        "and falls as the references improve, which is why it was collapsed into unlabelled.",
    )
    fig.tight_layout(rect=(0, 0.13, 1, 0.95))
    fig.savefig(FIG / "lift_by_window.png", dpi=170)
    plt.close(fig)
    print("  lift_by_window.png")


def figure_diurnal() -> None:
    # Read from scripts/seasonal_comparison.py's artifact rather than typed. D122.
    profiles = json.loads((ARTIFACT_DIR / "seasonal_diurnal.json").read_text())
    y2023 = {int(h): n for h, n in profiles["burning season 2023"].items()}
    y2024 = {int(h): n for h, n in profiles["burning season 2024"].items()}
    t23, t24 = sum(y2023.values()), sum(y2024.values())
    hours = np.arange(24)
    s23 = [100 * y2023.get(h, 0) / t23 for h in hours]
    s24 = [100 * y2024.get(h, 0) / t24 for h in hours]
    fig, axis = plt.subplots(figsize=(11, 4.6))
    axis.bar(hours - 0.2, s23, 0.4, label=f"2023 season (n={t23})", color="#2b6cb0")
    axis.bar(hours + 0.2, s24, 0.4, label=f"2024 season (n={t24})", color="#c46210")
    axis.axvspan(15.5, 19.5, color="#b00020", alpha=0.10)
    note = "17:00 IST\nshifted burning peak\nzero detections,\nboth seasons"
    axis.text(17.5, max(s23) * 0.55, note, ha="center", fontsize=8.5, color="#b00020")
    axis.set_xticks(hours)
    axis.set_xlabel("hour of day, IST")
    axis.set_ylabel("share of detections, percent")
    axis.set_title(
        "The polar orbiting record cannot see the window the burning peak moved into",
        fontsize=12,
        loc="left",
    )
    axis.legend(fontsize=8, frameon=False)
    for spine in ("top", "right"):
        axis.spines[spine].set_visible(False)
    caption(
        fig,
        "India assigned detections on the three sensors present in both years: MODIS Terra "
        "and Aqua, VIIRS S-NPP and NOAA-20. VIIRS NOAA-21 is excluded because it carries no "
        "data before 2024-01-17 and\nwould otherwise report an extra satellite as a year on "
        "year increase. Two seasons cannot establish a multi year trend; the published claim "
        "concerns 2020 to 2024 and 2020 is not ingested.",
    )
    fig.tight_layout(rect=(0, 0.15, 1, 1))
    fig.savefig(FIG / "diurnal_comparison.png", dpi=170)
    plt.close(fig)
    print("  diurnal_comparison.png")


def figure_pr_and_confusion() -> None:
    con = duckdb.connect(str(DUCKDB_PATH))
    frame = con.execute(FEATURE_SQL).df()
    trained = frame[frame["weak_label"].isin(TRAINED_CLASSES)].copy()
    columns = list(FEATURE_COLUMNS)
    _, test_states = split_for("group_a")
    train = trained[~trained["state_name"].isin(test_states)]
    test = trained[trained["state_name"].isin(test_states)]
    model = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.1, random_state=SEED)
    model.fit(train[columns], train["weak_label"])
    probs = model.predict_proba(test[columns])
    classes = list(model.classes_)

    fig, axes = plt.subplots(1, 2, figsize=(12.5, 5.2))
    for name in TRAINED_CLASSES:
        index = classes.index(name)
        truth = (test["weak_label"] == name).astype(int)
        PrecisionRecallDisplay.from_predictions(
            truth,
            probs[:, index],
            ax=axes[0],
            name=name,
            color=COLOURS[name],
        )
    axes[0].set_title("B1 precision recall, group_a held out", fontsize=11, loc="left")
    axes[0].legend(fontsize=8, frameon=False)

    matrix = np.load(ARTIFACT_DIR / "b1_confusion_group_a.npy")
    normalised = matrix / matrix.sum(axis=1, keepdims=True)
    image = axes[1].imshow(normalised, cmap="Oranges", vmin=0, vmax=1)
    axes[1].set_xticks(range(len(TRAINED_CLASSES)), TRAINED_CLASSES, rotation=20, fontsize=9)
    axes[1].set_yticks(range(len(TRAINED_CLASSES)), TRAINED_CLASSES, fontsize=9)
    axes[1].set_xlabel("predicted")
    axes[1].set_ylabel("weak label")
    for i in range(len(TRAINED_CLASSES)):
        for j in range(len(TRAINED_CLASSES)):
            axes[1].text(
                j,
                i,
                f"{normalised[i, j]:.2f}\n{matrix[i, j]}",
                ha="center",
                va="center",
                fontsize=8,
                color="white" if normalised[i, j] > 0.55 else "#222222",
            )
    axes[1].set_title("B1 confusion, row normalised, group_a", fontsize=11, loc="left")
    fig.colorbar(image, ax=axes[1], fraction=0.045)
    caption(
        fig,
        "Option A, no class weighting, fitted on the true prior. Flare is 1.16 percent of "
        "rows, so its curve sits low and that is the reported result rather than a defect.\n"
        "Features exclude the distances and land cover that define the weak label: including "
        "them gives macro F1 0.9998, which is arithmetic rather than attribution.",
    )
    fig.tight_layout(rect=(0, 0.12, 1, 1))
    fig.savefig(FIG / "b1_pr_confusion.png", dpi=170)
    plt.close(fig)
    print("  b1_pr_confusion.png")


def figure_coverage() -> None:
    data = json.loads((ARTIFACT_DIR / "conformal_aoa_b2.json").read_text())
    groups = [g for g in data if g.startswith("group")]
    coverage = [data[g]["coverage"] for g in groups]
    outside = [100 * data[g]["outside_aoa_fraction"] for g in groups]
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.4))
    bar_colours = ["#3f7f4f" if c >= 0.9 else "#b00020" for c in coverage]
    bars = axes[0].bar(groups, coverage, color=bar_colours)
    axes[0].axhline(0.90, color="#333333", linestyle="--", linewidth=1.2)
    axes[0].text(2.4, 0.905, "nominal 90 percent", fontsize=8, ha="right", color="#333333")
    axes[0].set_ylim(0.7, 1.0)
    axes[0].set_ylabel("empirical coverage")
    axes[0].set_title("Split conformal undercovers under spatial shift", fontsize=11, loc="left")
    for bar, value in zip(bars, coverage, strict=True):
        axes[0].text(
            bar.get_x() + bar.get_width() / 2,
            value + 0.005,
            f"{value:.4f}",
            ha="center",
            fontsize=8.5,
        )
    axes[1].bar(groups, outside, color="#2b6cb0")
    axes[1].set_ylabel("percent of test set outside the domain")
    axes[1].set_title("Applicability domain, 95th percentile threshold", fontsize=11, loc="left")
    for axis in axes:
        axis.tick_params(labelsize=8.5)
        for spine in ("top", "right"):
            axis.spines[spine].set_visible(False)
    caption(
        fig,
        "Calibrated on a held out slice of the training states, never on the test group. "
        "A spatially blocked split breaks the exchangeability split conformal assumes, so the "
        "guarantee does not hold:\ntwo of three groups undercover by 8 and 10 points. A random "
        "split would have shown coverage near nominal and concealed it.",
    )
    fig.tight_layout(rect=(0, 0.15, 1, 1))
    fig.savefig(FIG / "conformal_aoa.png", dpi=170)
    plt.close(fig)
    print("  conformal_aoa.png")


def main() -> int:
    ensure_dir(FIG)
    print("writing figures:")
    figure_lift()
    figure_diurnal()
    figure_coverage()
    figure_pr_and_confusion()
    print(f"\nall figures in {FIG}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
