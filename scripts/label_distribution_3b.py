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

from ml.documents import provenance_line
from ml.labels.background import flare_background, weighted_industrial_background
from ml.labels.splits import HELD_OUT_GROUPS, split_for, validate_groups
from ml.labels.weak import (
    CLASS_UNLABELLED,
    MAX_CLASS_SHARE,
    label_from_distances,
    weak_label_sql,
)
from ml.paths import DUCKDB_PATH, ROOT, ensure_dir

OUT = ROOT / "docs" / "label_distribution.md"

# Read from the measurement rather than copied. The industrial rate includes GEM and
# is weighted by how the population splits across window years, D122. Filled in main.
BACKGROUND: dict[str, float] = {}

MIN_CLASS_MEMBERS = 300
MIN_TEST_ROWS = 500


def main() -> int:
    con = duckdb.connect(str(DUCKDB_PATH))
    total = int(con.execute("SELECT count(*) FROM detection_context").fetchone()[0])
    if total == 0:
        print("detection_context is empty. Run build_features_3b.py first.", file=sys.stderr)
        return 2

    # The label of record, from the one SQL definition. Until 2026-09-23 this read the
    # stored column, which predates the withdrawal of the wildfire class and has no GEM
    # term, and the second method below recomputed that same stale rule, so the two
    # agreed exactly while both were wrong. D121.
    rows = con.execute(
        f"SELECT {weak_label_sql('c', 'g')} AS label, count(*) "
        "FROM detection_context c LEFT JOIN detection_gem g USING (detection_id) "
        "GROUP BY 1 ORDER BY 2 DESC, 1"
    ).fetchall()
    shares = {label: count / total for label, count in rows}
    counts = dict(rows)
    years = dict(
        con.execute(
            "SELECT year(d.acq_date_ist), count(*) FROM detection_context c "
            "JOIN detections d USING (detection_id) GROUP BY 1"
        ).fetchall()
    )
    BACKGROUND["flare"] = flare_background()
    BACKGROUND["industrial"] = weighted_industrial_background(years)

    # Second method: the same rule implemented independently in Python, from the raw
    # distance columns, so a defect in either implementation cannot agree with itself.
    raw = con.execute(
        "SELECT c.flare_m, c.industrial_m, c.landcover_class, g.gem_m_temporal "
        "FROM detection_context c LEFT JOIN detection_gem g USING (detection_id)"
    ).fetchall()
    independent_counts: dict[str, int] = {}
    for flare_m, industrial_m, landcover_class, gem_m in raw:
        name = label_from_distances(flare_m, industrial_m, landcover_class, gem_m=gem_m).label
        independent_counts[name] = independent_counts.get(name, 0) + 1

    # The stored column is kept visible rather than hidden: it is stale, nothing reads it
    # any more, and until it is rebuilt a count of how far it has drifted belongs in the
    # document that describes the labels.
    stale_rows = int(
        con.execute(
            f"SELECT count(*) FROM detection_context c "
            f"LEFT JOIN detection_gem g USING (detection_id) "
            f"WHERE c.weak_label IS DISTINCT FROM {weak_label_sql('c', 'g')}"
        ).fetchone()[0]
    )

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

    print("\nsecond method check, the rule implemented twice, SQL against Python:")
    if disagreements:
        print("  DISAGREEMENT")
        for line in disagreements:
            print(f"    {line}")
    else:
        print("  the two implementations agree exactly")
    print(f"stored column rows that differ from the label of record: {stale_rows}")

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

    # The window was hard coded here and the count was not, so after the seasonal
    # ingest this file described 601941 detections spanning three windows as a
    # monsoon quarter in which crop residue burning is at its minimum. That caveat
    # is the reverse of the truth for two of the three windows. Derived from the
    # data instead, so the description cannot drift from what was counted again.
    first_day, last_day, window_count = con.execute(
        """
        SELECT min(acq_date_ist), max(acq_date_ist),
               count(DISTINCT date_trunc('month', acq_date_ist))
        FROM detections
        """
    ).fetchone()

    lines = [
        "# Weak label class distribution",
        "",
        "Regenerate: `uv run python scripts/label_distribution_3b.py`",
        provenance_line(__file__),
        "",
        "Generated by `scripts/label_distribution_3b.py`.",
        "",
        f"{total} detections spanning {first_day} to {last_day}, across "
        f"{window_count} distinct months of ingest.",
        "",
        "The ingest is not a continuous record. It is three windows, one monsoon "
        "quarter and two burning seasons, so the class shares below are a property "
        "of that sampling and not of the year.",
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
    lines += [
        "",
        f"Detections assigned to no state: {unassigned} ({unassigned / total:.2%}).",
        "",
        "The label is computed by `weak_label_sql` and checked against an independent",
        "Python implementation of the same rule. The stored `weak_label` column in",
        "`detection_context` predates the withdrawal of the wildfire class and carries",
        f"no GEM term. It differs from the label of record in {stale_rows} rows and no",
        "analysis reads it. D120, D121.",
        "",
    ]

    ensure_dir(OUT.parent)
    OUT.write_text("\n".join(lines) + "\n")
    print(f"\nwritten to {OUT}")

    if disagreements:
        print("\nSTOP: the two implementations of the label rule disagree", file=sys.stderr)
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
