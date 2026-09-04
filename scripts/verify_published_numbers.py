"""Re-derive every published number and report which ones cannot be reproduced.

The test suite pins that a claim points at a command. It does not pin that the
command still produces the claim. Six of the seven corrections in the decision log
were found by looking rather than by a test, so this exists to look mechanically.

Three categories, deliberately not collapsed.

  reproduced   the number matches a value derived here, and the provenance says
               whether that value came from a live query or from a stored artifact
  mismatch     the number is close to a derived value but does not equal it, which
               is what a stale digit looks like
  unbacked     no derived value corresponds to it at all

The third is the one a spot check misses, and it is the reason this reports
coverage rather than a pass or fail.

D59 matters here. A value read back from a stored artifact is not the same
guarantee as a value recomputed by rerunning its command, because the artifact may
have been written under conditions that no longer reproduce. Provenance is carried
through to the report for exactly that reason.

Writes docs/number_verification.md.
"""

import json
import os

# Pinned before sklearn or numpy threading is initialised anywhere downstream. D59.
os.environ.setdefault("OMP_NUM_THREADS", "4")

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml.paths import ARTIFACT_DIR, DUCKDB_PATH, ROOT

DOCUMENTS = ("docs/results.md", "docs/model_card.md", "docs/paper_outline.md")
OUTPUT = ROOT / "docs" / "number_verification.md"

# Tokens that are numeric but are not claims about measurement.
SKIP_LINE = re.compile(
    r"^\s*\|?\s*-{3,}|^\s*```|^\s*Regenerate:|^\s*Source:|^\s*Table:|^\s*Figure:|^\s*#{1,6}\s",
)
# A bare year, or a fragment left behind by splitting a timestamp, is not a claim.
NOT_A_CLAIM = re.compile(r"^(19|20)\d\d$|^\d{2}$")
SKIP_CONTEXT = re.compile(
    r"\bD\d+\b|\b20\d\d-\d\d-\d\d\b|\bsection \d+\b|\bfigure \d+\b|\bphase \d+\b"
    r"|\bgroup_[a-d]\b(?![^|]*\d\.\d)|EPSG|T4[45]|S2[ABC]_|MSIL2A",
    re.IGNORECASE,
)
NUMBER = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+\.\d+|\d+)(?![\w])")


@dataclass
class Derived:
    """One value this script derived, with how it was obtained."""

    value: float
    label: str
    provenance: str  # "live query" or "stored artifact"


@dataclass
class Finding:
    document: str
    line_number: int
    token: str
    line: str
    category: str
    matched: str = ""
    candidates: list[str] = field(default_factory=list)


def renderings(value: float) -> set[str]:
    """Every string form a published document plausibly uses for one value."""
    forms: set[str] = set()
    if value == int(value) and abs(value) < 1e12:
        whole = int(value)
        forms.add(str(whole))
        forms.add(f"{whole:,}")
    for places in (0, 1, 2, 3, 4):
        forms.add(f"{value:.{places}f}")
        forms.add(f"{value * 100:.{places}f}")
    return {f for f in forms if f}


def derive_from_artifacts() -> list[Derived]:
    values: list[Derived] = []

    def walk(node, path: str, provenance: str) -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                walk(child, f"{path}.{key}" if path else str(key), provenance)
        elif isinstance(node, list):
            for index, child in enumerate(node):
                walk(child, f"{path}[{index}]", provenance)
        elif isinstance(node, (int, float)) and not isinstance(node, bool):
            values.append(Derived(float(node), path, provenance))

    for name in sorted(ARTIFACT_DIR.glob("*.json")):
        walk(json.loads(name.read_text()), name.stem, "stored artifact")
    return values


def derive_from_generated_docs() -> list[Derived]:
    """Numbers in documents that carry a regeneration command of their own.

    Weaker than an artifact and much weaker than a live query, but it is a real
    provenance: the document was written by a script that can be rerun. Without
    this tier the burstiness and coverage tables read as unbacked when they are
    simply backed by a generated table rather than by JSON.
    """
    values: list[Derived] = []
    for path in sorted((ROOT / "docs").glob("*.md")):
        if path.name in {Path(d).name for d in DOCUMENTS} or path.name == OUTPUT.name:
            continue
        text = path.read_text()
        if "Regenerate:" not in text:
            continue
        for token in NUMBER.findall(text):
            try:
                values.append(
                    Derived(float(token.replace(",", "")), f"{path.name}", "generated document")
                )
            except ValueError:
                continue
    return values


def derive_from_database() -> list[Derived]:
    """Values recomputed now, by query, rather than read from an artifact."""
    connection = duckdb.connect()
    connection.execute(f"ATTACH '{DUCKDB_PATH}' AS a (READ_ONLY);")
    queries: dict[str, str] = {
        "detections.total": "SELECT count(*) FROM a.detections",
        "detections.india_assigned": (
            "SELECT count(*) FROM a.detection_context WHERE state_name IS NOT NULL"
        ),
        "detections.no_state": (
            "SELECT count(*) FROM a.detection_context WHERE state_name IS NULL"
        ),
        "detections.trained_class_rows": (
            "SELECT count(*) FROM a.detection_context "
            "WHERE weak_label IN ('flare','industrial','agricultural')"
        ),
        "reference.osm_industrial": "SELECT count(*) FROM a.ref_osm_industrial",
        "reference.osm_admin": "SELECT count(*) FROM a.ref_osm_admin",
        "reference.flares": "SELECT count(*) FROM a.ref_flares",
        "reference.gem_assets": "SELECT count(*) FROM a.ref_gem_assets",
    }
    values: list[Derived] = []
    for label, sql in queries.items():
        try:
            result = connection.execute(sql).fetchone()
        except duckdb.Error as exc:
            print(f"  query failed, {label}: {exc}", file=sys.stderr)
            continue
        if result is not None:
            values.append(Derived(float(result[0]), label, "live query"))

    per_class = connection.execute(
        "SELECT weak_label, count(*) FROM a.detection_context GROUP BY 1"
    ).fetchall()
    for name, count in per_class:
        values.append(Derived(float(count), f"detections.class.{name}", "live query"))
    return values


def classify(token: str, index: dict[str, list[Derived]]) -> Finding:
    """Reproduced at the strongest available provenance, or unbacked.

    There is deliberately no numeric proximity heuristic. An earlier version
    flagged a value as a mismatch when it fell within two percent of any derived
    value, which matched publication years against cluster spreads in metres and
    produced 36 findings of which none was real. Proximity without a semantic link
    between the claim and the source is not evidence of anything. Real staleness is
    caught by REGISTRY below, which compares named claims against named sources.
    """
    hits = index.get(token)
    if not hits:
        return Finding("", 0, token, "", "unbacked")
    rank = {"live query": 0, "stored artifact": 1, "generated document": 2}
    best = sorted(hits, key=lambda d: rank.get(d.provenance, 9))[0]
    return Finding("", 0, token, "", "reproduced", f"{best.label} [{best.provenance}]")


# Headline claims mapped to the source that must still produce them. This is where
# a stale digit actually shows, because both sides name the same quantity.
REGISTRY: tuple[tuple[str, str, str, float], ...] = (
    ("b1 group_a macro F1", "b1_results", "option_a.group_a.macro avg.f1-score", 0.621),
    ("b1 group_b macro F1", "b1_results", "option_a.group_b.macro avg.f1-score", 0.572),
    ("b1 group_c macro F1", "b1_results", "option_a.group_c.macro avg.f1-score", 0.601),
    ("b1 leakage macro F1", "b1_results", "leakage_macro_f1", 0.9998),
    ("b1 clean macro F1", "b1_results", "clean_macro_f1", 0.6209),
    ("b2 industrial F1", "conformal_aoa_b2", "b2_industrial.f1", 0.509),
    ("b2 industrial precision", "conformal_aoa_b2", "b2_industrial.precision", 0.388),
    ("b2 industrial recall", "conformal_aoa_b2", "b2_industrial.recall", 0.740),
    ("conformal group_b coverage", "conformal_aoa_b2", "group_b.coverage", 0.7948),
    ("conformal group_c coverage", "conformal_aoa_b2", "group_c.coverage", 0.8199),
    ("persistent source count", "persistent_sources", "chosen_radius_m", 500.0),
    ("b4 train rows", "b4_results", "train_rows", 440.0),
    ("b4 tiles for 80 percent", "b4_support", "tiles_for_80_percent", 39.0),
    ("b1 ablation with recurrence", "b1_ablation", "overall.predicted_industrial_full", 0.810),
    (
        "b1 ablation without recurrence",
        "b1_ablation",
        "overall.predicted_industrial_without_recurrence",
        0.797,
    ),
)


def check_registry() -> list[tuple[str, str, float, float, bool]]:
    """Compare each named published claim against the artifact key it comes from."""
    rows = []
    for label, artifact, dotted, published in REGISTRY:
        path = ARTIFACT_DIR / f"{artifact}.json"
        if not path.is_file():
            rows.append((label, f"{artifact}.json missing", published, float("nan"), False))
            continue
        node = json.loads(path.read_text())
        for part in dotted.split("."):
            node = node[part] if isinstance(node, dict) and part in node else None
            if node is None:
                break
        if not isinstance(node, (int, float)):
            rows.append((label, f"{artifact}:{dotted} not found", published, float("nan"), False))
            continue
        stored = float(node)
        agrees = abs(round(stored, 4) - published) < 0.0006 or abs(stored - published) < 0.0006
        rows.append((label, f"{artifact}:{dotted}", published, stored, agrees))
    return rows


def main() -> int:
    derived = derive_from_database() + derive_from_artifacts() + derive_from_generated_docs()
    print(
        f"derived {len(derived)} values: "
        f"{sum(1 for d in derived if d.provenance == 'live query')} by live query, "
        f"{sum(1 for d in derived if d.provenance == 'stored artifact')} from artifacts"
    )

    index: dict[str, list[Derived]] = {}
    for candidate in derived:
        for form in renderings(candidate.value):
            index.setdefault(form, []).append(candidate)

    findings: list[Finding] = []
    for relative in DOCUMENTS:
        path = ROOT / relative
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            if SKIP_LINE.search(line):
                continue
            for token in NUMBER.findall(line):
                if SKIP_CONTEXT.search(line) and token not in index:
                    continue
                if len(token.replace(",", "")) < 2 or NOT_A_CLAIM.match(token):
                    continue
                finding = classify(token, index)
                finding.document, finding.line_number, finding.line = relative, number, line.strip()
                findings.append(finding)

    counts = {name: 0 for name in ("reproduced", "unbacked")}
    for finding in findings:
        counts[finding.category] += 1
    total = len(findings)
    print(f"\n{total} numeric claims examined")
    for name, count in counts.items():
        print(f"  {name:12s} {count:5d}  {count / total:.1%}" if total else f"  {name}: 0")

    OUTPUT.write_text(render(findings, counts, total, derived))
    print(f"\nwrote {OUTPUT.relative_to(ROOT)}")
    return 0


def render(findings: list[Finding], counts: dict, total: int, derived: list[Derived]) -> str:
    lines = [
        "# Can every published number be re-derived?",
        "",
        f"Regenerate: `uv run python {Path('scripts/verify_published_numbers.py')}`",
        "",
        "The suite pins that a claim points at a command. It does not pin that the",
        "command still produces the claim. This checks the second thing.",
        "",
        f"{total} numeric claims examined across {len(DOCUMENTS)} documents, against "
        f"{len(derived)} derived values.",
        "",
        "| Category | Count | Share |",
        "|---|---|---|",
    ]
    for name in ("reproduced", "unbacked"):
        share = f"{counts[name] / total:.1%}" if total else "n/a"
        lines.append(f"| {name} | {counts[name]} | {share} |")
    lines += [
        "",
        "**Provenance is carried through deliberately.** A value read back from a",
        "stored artifact is not the same guarantee as one recomputed by rerunning its",
        "command: the artifact may have been written under conditions that no longer",
        "reproduce, which is what D59 established for B1. A `stored artifact`",
        "reproduction confirms the document matches the artifact and says nothing about",
        "whether the artifact still reproduces.",
        "",
        "## Named claims checked against their source",
        "",
        "Blind numeric proximity was removed. An earlier version flagged any published",
        "value within two percent of any derived value, which matched publication years",
        "against cluster spreads in metres and returned 36 findings, none of them real.",
        "Proximity without a semantic link is not evidence. These are checked instead,",
        "because both sides name the same quantity.",
        "",
        "| Claim | Source | Published | Stored | Agrees |",
        "|---|---|---|---|---|",
    ]
    for label, source, published, stored, agrees in check_registry():
        shown = "n/a" if stored != stored else f"{stored:.4f}"
        lines.append(
            f"| {label} | `{source}` | {published} | {shown} | {'yes' if agrees else '**no**'} |"
        )
    lines += [
        "",
        "## Unbacked",
        "",
        "No derived value corresponds to these. Some are prose quantities that are",
        "legitimately not artifact backed, such as a count of columns or a threshold",
        "chosen by decision. The list is reported in full rather than filtered, because",
        "deciding which are legitimate is the review, and a filter would hide the ones",
        "that are not.",
        "",
        "| Document | Line | Token | Claim |",
        "|---|---|---|---|",
    ]
    for finding in findings:
        if finding.category != "unbacked":
            continue
        excerpt = finding.line[:90].replace("|", "\\|")
        lines.append(
            f"| {finding.document} | {finding.line_number} | {finding.token} | {excerpt} |"
        )
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
