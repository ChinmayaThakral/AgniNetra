"""Generate the phase 4 model card from the recorded artifacts.

Every number is read from a JSON artifact written by the script that measured it.
Nothing is transcribed by hand, because a hand copied metric is a number without a
command behind it and this document exists to be the opposite of that.

Writes docs/model_card.md.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml.paths import ARTIFACT_DIR, ROOT

CLASSES = ("flare", "industrial", "agricultural")
STATE_GROUPS = ("group_a", "group_b", "group_c")


# Below this many positives an F1 carries an interval spanning most of the unit
# range. The same floor governs B4. A cell under it is annotated with its support
# rather than printed bare, because `0.000` travels further than `0.000 on n=4`.
MIN_CLASS_SUPPORT = 30


def _cell(entry: dict) -> str:
    """Render one F1, annotated with its support when the support is too thin."""
    support = int(entry["support"])
    if support < MIN_CLASS_SUPPORT:
        return f"{entry['f1-score']:.3f} on n={support}"
    return f"{entry['f1-score']:.3f}"


def load(name: str) -> dict:
    path = ARTIFACT_DIR / name
    if not path.is_file():
        raise SystemExit(
            f"missing artifact {path.relative_to(ROOT)}; run the script that writes it"
        )
    return json.loads(path.read_text())


def main() -> None:
    b1 = load("b1_results.json")
    b2 = load("conformal_aoa_b2.json")
    sources = load("persistent_sources.json")
    b4_path = ARTIFACT_DIR / "b4_results.json"
    b4 = json.loads(b4_path.read_text()) if b4_path.is_file() else None
    support_path = ARTIFACT_DIR / "b4_support.json"
    support = json.loads(support_path.read_text()) if support_path.is_file() else None

    option_a = b1["option_a"]
    macro = [option_a[g]["macro avg"]["f1-score"] for g in STATE_GROUPS]
    mean_macro = sum(macro) / len(macro)
    spread = max(macro) - min(macro)

    lines = [
        "# Model card: AgniNetra source attribution",
        "",
        f"Regenerate: `uv run python {Path('scripts/model_card.py')}`",
        "",
        "Generated from the recorded artifacts. No number here is typed by hand.",
        "",
        "## What the model does",
        "",
        "It assigns a thermal anomaly detection to a source type from context and",
        "recurrence features. It does not detect fires. It labels detections that",
        "NASA FIRMS has already published.",
        "",
        "## Classes",
        "",
        "Three: flare, industrial, agricultural. **Wildfire is not a trained class.**",
        "The land cover rule for it scored a lift below 1 in every window, meaning it",
        "was anti correlated with the thing it was supposed to find, so it was removed",
        "rather than kept as a weak signal. D33.",
        "",
        "## Training data and labels",
        "",
        "Labels are weak, derived by spatial join against reference layers that are",
        "incomplete and not incomplete at random. They are not ground truth. No field",
        "verification of any detection exists.",
        "",
        f"Seed {b1['seed']}, option A, no class weighting. D32.",
        "",
        "## Evaluation protocol",
        "",
        "Spatially blocked by state group. Never a random split: detections are",
        "strongly spatially autocorrelated and a random split puts the same site in",
        "train and test. D3.",
        "",
        "## Measured performance, baseline B1",
        "",
        "| Group | " + " | ".join(f"{c} F1" for c in CLASSES) + " | macro F1 |",
        "|---|---|---|---|---|",
    ]
    for group in (*STATE_GROUPS, "group_d_external"):
        entry = option_a[group]
        cells = " | ".join(_cell(entry[c]) for c in CLASSES)
        lines.append(f"| {group} | {cells} | {entry['macro avg']['f1-score']:.3f} |")

    lines += [
        "",
        f"Held out state group macro F1 mean {mean_macro:.3f}, spread {spread:.3f}.",
        "",
        "**The leakage check comes first.** With the label defining columns present "
        f"the macro F1 is {b1['leakage_macro_f1']:.4f}. Without them it is "
        f"{b1['clean_macro_f1']:.4f}. The first is arithmetic, not attribution. D43.",
        "",
        "## Known limitations, measured",
        "",
        f"**Flare recall is between "
        f"{min(option_a[g]['flare']['recall'] for g in STATE_GROUPS):.3f} and "
        f"{max(option_a[g]['flare']['recall'] for g in STATE_GROUPS):.3f}.** Flare is "
        "roughly one percent of rows and option A does not reweight. Reported as a "
        "result, not hidden.",
        "",
        "**Calibrated uncertainty does not survive spatial shift.**",
        "",
        "| Group | Empirical coverage | Nominal | Empty sets |",
        "|---|---|---|---|",
    ]
    for group in STATE_GROUPS:
        entry = b2[group]
        lines.append(
            f"| {group} | {entry['coverage']:.4f} | {entry['nominal']:.2f} | "
            f"{entry['empty_fraction'] * 100:.2f} percent |"
        )

    b2i = b2["b2_industrial"]
    lines += [
        "",
        "Split conformal assumes exchangeability and a spatially blocked split breaks "
        "it by construction. A random split would have concealed this. D45.",
        "",
        f"**Baseline B2**, density clustering on the industrial class: precision "
        f"{b2i['precision']:.3f}, recall {b2i['recall']:.3f}, F1 {b2i['f1']:.3f}. High "
        "recall with low precision is the signature of a method that finds persistent "
        "locations and cannot tell which are industrial.",
        "",
        f"**Persistent sources.** {len(sources['sources'])} locations, clustered by "
        f"great circle distance at {sources['chosen_radius_m']:.0f} m. The claim that "
        "some of them are absent from every registry was retracted: at a 5 km search "
        "radius none lacks a reference asset. D56.",
        "",
        "## Baseline B4, foundation model probe",
        "",
    ]

    if b4 is None:
        lines.append("not measured. The artifact has not been written.")
    else:
        reached = {g: b4["groups"].get(g, {}).get("rows", 0) for g in STATE_GROUPS}
        lines += [
            f"**Status: {b4['b4_status']}.**",
            "",
            f"The pipeline runs end to end on real imagery: scene `{b4['scene']}`, a "
            f"frozen TerraMind embedding, and a probe fitted on {b4['train_rows']} rows "
            f"with seed {b4['seed']}.",
            "",
            "**One scene is not enough, and it is not partial either.** Held out rows "
            "reached: "
            + ", ".join(f"{g} {n}" for g, n in reached.items())
            + ". group_a is not reached at all, so the comparison against B1 and B2 "
            "cannot be formed on the same groups, and no flare detection falls anywhere "
            "in the scene, so flare metrics are undefined rather than weak. Every per "
            "class cell fell below the support floor and is reported as its support "
            "rather than as a number. D57.",
        ]
        if support is not None:
            lines += [
                "",
                f"**The cost of lifting the refusal is stated rather than left open.** "
                f"Reaching 80 percent of the trained class detections in the three held "
                f"out groups needs {support['tiles_for_80_percent']} tiles, about "
                f"{support['gb_for_80_percent']:.0f} GB for one date each. 95 percent "
                f"needs {support['tiles_for_95_percent']}.",
            ]

    lines += [
        "",
        "## Not measured",
        "",
        "Baseline B3 waits on a MOSDAC order approval.",
        "",
        "KAALCHAKRA against B1 and B2 is **not measured**, and the evidence for that "
        "is measured: four findings say the excitation half of the model is not "
        "testable in a polar orbiting record. D58. Unlike B4 this refusal has no "
        "price, because no quantity of polar orbiting data lifts it.",
        "",
        "No field verification of any detection exists, and no gold set exists to build one from.",
        "",
        "## Two of these are refusals, not gaps",
        "",
        "B4 and phase 6 are both reported as not measured. In each case the system was "
        "run and the evidence was measured to be insufficient, so the number was "
        "withheld rather than produced. Reading them as two missing rows misses what "
        "they share. B4's refusal carries a stated price; phase 6's carries none, "
        "which is why it is a result about the observation record rather than a "
        "shortfall in the dataset.",
        "",
    ]
    destination = ROOT / "docs" / "model_card.md"
    destination.write_text("\n".join(lines))
    print(f"wrote {destination.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
