"""Publish the before and after for every number the D61 rebuild touched.

The old numbers are not deleted. They were produced by a pipeline in which
`detection_recurrence` covered 88454 of 601941 detections and `FEATURE_SQL`
coalesced the missing prior counts to zero, so 92.1 percent of B1's training rows
carried a fabricated zero at a rate that differed by class. Withdrawing them
silently would be the same failure as publishing them was.

If the conclusions hold across the rebuild, that is itself a result: it shows the
finding was robust to a defect capable of producing it. If any conclusion moves,
that is what had to be known before submission rather than after.

Reads the withdrawn copies in context/withdrawn/ and the current artifacts.
Writes docs/refit_comparison.md.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml.documents import provenance_line
from ml.paths import ARTIFACT_DIR, ROOT

BEFORE_DIR = ROOT / "context" / "withdrawn"
OUTPUT = ROOT / "docs" / "refit_comparison.md"
CLASSES = ("flare", "industrial", "agricultural")
GROUPS = ("group_a", "group_b", "group_c", "group_d_external")
STATE_GROUPS = GROUPS[:3]


def load(name: str) -> tuple[dict | None, dict | None]:
    before = BEFORE_DIR / name
    after = ARTIFACT_DIR / name
    return (
        json.loads(before.read_text()) if before.is_file() else None,
        json.loads(after.read_text()) if after.is_file() else None,
    )


def dig(node, dotted: str):
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def delta(before, after) -> str:
    if before is None or after is None:
        return "n/a"
    change = after - before
    return f"{change:+.3f}"


def main() -> int:
    b1_before, b1_after = load("b1_results.json")
    b2_before, b2_after = load("conformal_aoa_b2.json")
    abl_before, abl_after = load("b1_ablation.json")
    src_before, src_after = load("persistent_sources.json")
    if b1_after is None:
        raise SystemExit("no current b1_results.json; run scripts/train_b1.py first")

    lines = [
        "# Before and after the D61 rebuild",
        "",
        f"Regenerate: `uv run python {Path('scripts/refit_comparison.py')}`",
        provenance_line(__file__),
        "",
        "`detection_recurrence` covered 88454 of 601941 detections and `FEATURE_SQL`",
        "coalesced the missing prior counts to zero, so **92.1 percent of B1's training",
        "rows carried a fabricated zero**, at 94.8 percent for agricultural against 83.7",
        "for industrial. The table was rebuilt to full coverage, the coalesce was",
        "removed so a missing value reaches the estimator as missing, and everything",
        "downstream was refitted with the thread count pinned. D61, D65.",
        "",
        "Withdrawn artifacts are kept in `context/withdrawn/` so this is regenerable.",
        "",
        "## Baseline B1, macro F1 by held out group",
        "",
        "| Group | Withdrawn | Rebuilt | Change |",
        "|---|---|---|---|",
    ]
    for group in GROUPS:
        before = dig(b1_before or {}, f"option_a.{group}.macro avg.f1-score")
        after = dig(b1_after, f"option_a.{group}.macro avg.f1-score")
        shown_b = f"{before:.3f}" if before is not None else "n/a"
        shown_a = f"{after:.3f}" if after is not None else "n/a"
        lines.append(f"| {group} | {shown_b} | {shown_a} | {delta(before, after)} |")

    def spread(payload) -> tuple[float | None, float | None]:
        if payload is None:
            return None, None
        values = [dig(payload, f"option_a.{g}.macro avg.f1-score") for g in STATE_GROUPS]
        values = [v for v in values if v is not None]
        if not values:
            return None, None
        return sum(values) / len(values), max(values) - min(values)

    mean_b, spread_b = spread(b1_before)
    mean_a, spread_a = spread(b1_after)
    lines += [
        "",
        f"State group mean {mean_b:.3f} to {mean_a:.3f} ({delta(mean_b, mean_a)}), "
        f"spread {spread_b:.3f} to {spread_a:.3f} ({delta(spread_b, spread_a)}).",
        "",
        "## Per class F1, the three state groups",
        "",
        "| Group | Class | Withdrawn | Rebuilt | Change |",
        "|---|---|---|---|---|",
    ]
    for group in STATE_GROUPS:
        for klass in CLASSES:
            before = dig(b1_before or {}, f"option_a.{group}.{klass}.f1-score")
            after = dig(b1_after, f"option_a.{group}.{klass}.f1-score")
            shown_b = f"{before:.3f}" if before is not None else "n/a"
            shown_a = f"{after:.3f}" if after is not None else "n/a"
            lines.append(f"| {group} | {klass} | {shown_b} | {shown_a} | {delta(before, after)} |")

    lines += ["", "## Leakage check", "", "| Quantity | Withdrawn | Rebuilt |", "|---|---|---|"]
    for label, key in (
        ("with label defining columns", "leakage_macro_f1"),
        ("without them", "clean_macro_f1"),
    ):
        before = dig(b1_before or {}, key)
        after = dig(b1_after, key)
        lines.append(
            f"| {label} | {before:.4f} | {after:.4f} |"
            if before is not None and after is not None
            else f"| {label} | n/a | n/a |"
        )

    if b2_before and b2_after:
        lines += [
            "",
            "## Conformal coverage and B2",
            "",
            "| Quantity | Withdrawn | Rebuilt | Change |",
            "|---|---|---|---|",
        ]
        for group in STATE_GROUPS:
            before = dig(b2_before, f"{group}.coverage")
            after = dig(b2_after, f"{group}.coverage")
            lines.append(
                f"| {group} empirical coverage | {before:.4f} | {after:.4f} | "
                f"{delta(before, after)} |"
            )
        for label, key in (
            ("B2 industrial precision", "b2_industrial.precision"),
            ("B2 industrial recall", "b2_industrial.recall"),
            ("B2 industrial F1", "b2_industrial.f1"),
        ):
            before, after = dig(b2_before, key), dig(b2_after, key)
            lines.append(f"| {label} | {before:.3f} | {after:.3f} | {delta(before, after)} |")

    if abl_before and abl_after:
        lines += [
            "",
            "## The recurrence ablation now means something",
            "",
            "Before the rebuild this compared a model against one with five columns",
            "removed that were 96 percent NULL or 92 percent fabricated, so it measured",
            "what B1 was not using. After the rebuild the columns carry real values and",
            "the comparison tests what recurrence contributes. D62.",
            "",
            "| Quantity | Withdrawn | Rebuilt |",
            "|---|---|---|",
        ]
        for label, key in (
            ("flare predicted industrial, with recurrence", "overall.predicted_industrial_full"),
            (
                "flare predicted industrial, without recurrence",
                "overall.predicted_industrial_without_recurrence",
            ),
        ):
            before, after = dig(abl_before, key), dig(abl_after, key)
            lines.append(f"| {label} | {before:.3f} | {after:.3f} |")

    if src_before and src_after:
        lines += [
            "",
            "## Persistent sources",
            "",
            "| Quantity | Withdrawn | Rebuilt |",
            "|---|---|---|",
            f"| sources at the chosen radius | {len(src_before['sources'])} | "
            f"{len(src_after['sources'])} |",
        ]
    lines.append("")
    OUTPUT.write_text("\n".join(lines))
    print(f"wrote {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
