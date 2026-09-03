#!/usr/bin/env python3
"""Phase 3b: the weak label class distribution, and the stop conditions on it.

This is the first real test of the label rules. In 3a the radii were measured
against uniform probe points, giving a background rate: what a detection placed at
random would pick up. Detections are not uniform, so the actual share must be
higher. The size of that gap is the finding. If the industrial share lands near
the background rate, the rule is not finding anything the geography did not
already imply.

Stop conditions checked here, all of which exit non zero:
  any labelled class above 60 percent of detections
  any labelled class with fewer than 300 members, too few to evaluate per class
    inside a spatially blocked split
  any held out group whose test set is empty or nearly so

Usage:
    uv run python scripts/label_distribution_3b.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import duckdb

from ml.labels.splits import HELD_OUT_GROUPS, split_for, validate_groups
from ml.labels.weak import CLASS_UNLABELLED, MAX_CLASS_SHARE
from ml.paths import DUCKDB_PATH, ROOT, ensure_dir

OUT = ROOT / "docs" / "label_distribution.md"

# From scripts/label_radius_sensitivity.py, 4000 uniform probe points, 2026-09-04.
BACKGROUND = {"flare": 0.000000, "industrial": 0.0175}

MIN_CLASS_MEMBERS = 300
MIN_TEST_ROWS = 500


def main() -> int:
    con = duckdb.connect(str(DUCKDB_PATH))
    total = int(con.execute("SELECT count(*) FROM detection_context").fetchone()[0])
    if total == 0:
        print("detection_context is empty. Run build_features_3b.py first.", file=sys.stderr)
        return 2

    rows = con.execute(
        "SELECT weak_label, count(*) FROM detection_context GROUP BY 1 ORDER BY 2 DESC"
    ).fetchall()
    shares = {label: count / total for label, count in rows}
    counts = dict(rows)

    # Second method: recompute the shares from the raw distance columns rather than
    # from the stored label, so a bug in the write path cannot agree with itself.
    independent = con.execute(
        """
        SELECT CASE
                 WHEN flare_m IS NOT NULL AND flare_m <= 500 THEN 'flare'
                 WHEN industrial_m IS NOT NULL AND industrial_m <= 1000 THEN 'industrial'
                 WHEN landcover_class = 'cropland' THEN 'agricultural'
                 WHEN landcover_class IN ('tree_cover','shrubland','grassland') THEN 'wildfire'
                 ELSE 'unlabelled'
               END AS recomputed, count(*)
        FROM detection_context GROUP BY 1
        """
    ).fetchall()
    independent_counts = dict(independent)

    print(f"detections with context: {total}\n")
    print(f"{'class':14s} {'count':>8s} {'share':>9s} {'background':>11s} {'lift':>8s}")
    disagreements = []
    for label, count in rows:
        share = shares[label]
        background = BACKGROUND.get(label)
        if background is None:
            background_text, lift_text = "n/a", "n/a"
        elif background == 0.0:
            background_text, lift_text = f"{background:.4%}", "inf"
        else:
            background_text, lift_text = f"{background:.4%}", f"{share / background:.1f}x"
        print(f"{label:14s} {count:8d} {share:9.2%} {background_text:>11s} {lift_text:>8s}")
        if independent_counts.get(label, 0) != count:
            disagreements.append(
                f"{label}: stored {count}, recomputed {independent_counts.get(label, 0)}"
            )

    print("\nsecond method check, labels recomputed from raw distances:")
    if disagreements:
        print("  DISAGREEMENT")
        for line in disagreements:
            print(f"    {line}")
    else:
        print("  stored labels and recomputed labels agree exactly")

    failures: list[str] = []
    for label, share in shares.items():
        if label == CLASS_UNLABELLED:
            continue
        if share > MAX_CLASS_SHARE:
            failures.append(f"{label} holds {share:.1%}, above the {MAX_CLASS_SHARE:.0%} ceiling")
        if counts[label] < MIN_CLASS_MEMBERS:
            failures.append(
                f"{label} has {counts[label]} members, below {MIN_CLASS_MEMBERS} and too few "
                "to evaluate per class in a spatially blocked split"
            )

    print("\nheld out group test set sizes:")
    validate_groups()
    group_rows: list[tuple[str, int, int]] = []
    for group in HELD_OUT_GROUPS:
        _, test_states = split_for(group)
        placeholders = ", ".join(["?"] * len(test_states))
        test_n = int(
            con.execute(
                f"SELECT count(*) FROM detection_context WHERE state_name IN ({placeholders})",
                list(test_states),
            ).fetchone()[0]
        )
        labelled_n = int(
            con.execute(
                f"SELECT count(*) FROM detection_context WHERE state_name IN ({placeholders}) "
                "AND weak_label <> 'unlabelled'",
                list(test_states),
            ).fetchone()[0]
        )
        group_rows.append((group, test_n, labelled_n))
        print(f"  {group}: {test_n} detections, {labelled_n} labelled")
        if test_n < MIN_TEST_ROWS:
            failures.append(f"{group} test set has {test_n} rows, below {MIN_TEST_ROWS}")

    unassigned = int(
        con.execute("SELECT count(*) FROM detection_context WHERE state_name IS NULL").fetchone()[0]
    )
    print(f"\ndetections assigned to no state: {unassigned} ({unassigned / total:.2%})")

    lines = [
        "# Weak label class distribution",
        "",
        "Generated by `scripts/label_distribution_3b.py`.",
        "",
        f"Window 2026-06-06 to 2026-09-03, {total} detections. This is a monsoon",
        "quarter, so crop residue burning is near its seasonal minimum and the",
        "agricultural share here is not representative of the year.",
        "",
        "| Class | Count | Share | Background rate | Lift |",
        "|---|---|---|---|---|",
    ]
    for label, count in rows:
        share = shares[label]
        background = BACKGROUND.get(label)
        if background is None:
            b, lift = "n/a", "n/a"
        elif background == 0.0:
            b, lift = f"{background:.4%}", "unbounded"
        else:
            b, lift = f"{background:.4%}", f"{share / background:.1f}x"
        lines.append(f"| {label} | {count} | {share:.2%} | {b} | {lift} |")
    lines += [
        "",
        "Background rate is from `scripts/label_radius_sensitivity.py`: the share a",
        "detection placed uniformly at random would pick up. Lift is the ratio. A lift",
        "near 1 would mean the rule is keyed on geography rather than on source type.",
        "",
        "## Held out group sizes",
        "",
        "| Group | Detections | Labelled |",
        "|---|---|---|",
    ]
    for group, test_n, labelled_n in group_rows:
        lines.append(f"| {group} | {test_n} | {labelled_n} |")
    lines += ["", f"Detections assigned to no state: {unassigned} ({unassigned / total:.2%}).", ""]

    ensure_dir(OUT.parent)
    OUT.write_text("\n".join(lines) + "\n")
    print(f"\nwritten to {OUT}")

    if disagreements:
        print("\nSTOP: the second method disagrees with the stored labels", file=sys.stderr)
        return 1
    if failures:
        print("\nSTOP CONDITIONS MET:", file=sys.stderr)
        for failure in failures:
            print(f"  {failure}", file=sys.stderr)
        return 1
    print("\nno stop condition met")
    return 0


if __name__ == "__main__":
    sys.exit(main())
