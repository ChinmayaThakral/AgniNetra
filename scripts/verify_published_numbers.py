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
from typing import Final

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml.documents import (
    DIGEST_LABEL,
    declared_generator,
    generated_documents,
    generator_digest,
    is_generated,
    provenance_line,
    recorded_digest,
)
from ml.labels.weak import weak_label_sql
from ml.paths import ARTIFACT_DIR, DUCKDB_PATH, ROOT

# Scope is a glob with an explicit exclude list, not an inclusion list. An inclusion
# list omits silently: this constant named three documents, so "15.2 percent unbacked"
# was 15.2 percent of three files while every other document in docs/ went unchecked.
# An exclude list fails loudly instead, because a new document enters scope by default
# and has to be argued out. The report is therefore in scope before it is
# written, which is the point: the one document that matters must not be the one the
# tracer never sees.
SCOPE_EXCLUDED: dict[str, str] = {
    "docs/number_verification.md": "this tracer's own output",
    "docs/audit/SUMMARY.md": "audit findings about this repository, not claims by it",
    "docs/audit/audit-code.md": "audit finding",
    "docs/audit/audit-deploy.md": "audit finding",
    "docs/audit/audit-licensing.md": "audit finding",
    "docs/audit/audit-logic.md": "audit finding",
    "docs/audit/audit-repo.md": "audit finding",
    "docs/audit/audit-secrets.md": "audit finding",
    "docs/audit/2026-09-16-numbers.md": "audit finding",
    "docs/audit/2026-09-16-fusion-code.md": "audit finding",
    "docs/audit/2026-09-16-methodology.md": "audit finding",
    "docs/audit/2026-09-16-guards.md": "audit finding",
    "docs/audit/2026-09-16-secrets-history.md": "audit finding",
}


# The type test that keeps the two tiers apart lives in ml/documents.py, because
# three separate checks need it and each local copy is a place it can drift. D112.


def all_documents() -> list[Path]:
    return [
        path
        for path in sorted((ROOT / "docs").rglob("*.md"))
        if path.relative_to(ROOT).as_posix() not in SCOPE_EXCLUDED
    ]


def evidence_documents() -> list[Path]:
    """Generated documents. A script produced these numbers, so they are provenance."""
    return [p for p in all_documents() if is_generated(p)]


def documents() -> list[str]:
    """Prose documents. These make claims, and every claim must trace to evidence.

    Disjoint from evidence_documents by construction: a document is one or the other,
    decided by whether a script wrote it. Nothing can be both its own claim and its own
    proof. tests/test_number_tracer_tiers.py asserts the two sets never intersect.
    """
    return [p.relative_to(ROOT).as_posix() for p in all_documents() if not is_generated(p)]


OUTPUT = ROOT / "docs" / "number_verification.md"

# Tokens that are numeric but are not claims about measurement.
SKIP_LINE = re.compile(
    r"^\s*\|?\s*-{3,}|^\s*```|^\s*Regenerate:|^\s*Source:|^\s*Table:|^\s*Figure:|^\s*#{1,6}\s",
)
# A bare year, or a fragment left behind by splitting a timestamp, is not a claim.
NOT_A_CLAIM = re.compile(r"^(19|20)\d\d$|^\d{2}$")
# A DOI, a PMC identifier, a volume or a page range is an address, not a measurement.
# The report's literature chapter is dense with them and every one read as an unbacked
# claim, which is noise that hides real findings in the same table.
SKIP_CONTEXT = re.compile(
    r"\bD\d+\b|\b20\d\d-\d\d-\d\d\b|\bsection \d+\b|\bfigure \d+\b|\bphase \d+\b"
    r"|\bgroup_[a-d]\b(?![^|]*\d\.\d)|EPSG|T4[45]|S2[ABC]_|MSIL2A"
    r"|\bdoi:|\bdoi\.org|\bPMC\d+|\barXiv:",
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


# A rendering may round a value but it may not round the value away. An earlier
# version emitted every form at zero through four decimal places and again at a
# hundred times scale, so a single stored 0.0066 claimed to back the tokens 0, 0.0,
# 0.007, 0.01, 0.66, 0.660, 0.6600, 0.7 and 1. Across 4219 derived values that
# indexed 16758 tokens, of which 1 was backed by 653 different values and 0 by 476.
# Proximity was refused in classify and readmitted through rounding. D101.
RENDER_TOLERANCE: Final[float] = 0.005


def _forms(value: float, scale: float) -> set[str]:
    """String forms of value times scale that keep the value's significant figures."""
    scaled = value * scale
    forms: set[str] = set()
    if scaled == int(scaled) and abs(scaled) < 1e12:
        whole = int(scaled)
        forms.add(str(whole))
        forms.add(f"{whole:,}")
    # The range extends past four places for small magnitudes. A fixed 0 to 4 cannot
    # represent 0.000669 at its own precision at all, so a standard deviation that size
    # read as unbacked no matter how it was written. The tolerance gate below still
    # decides which of these survive, so widening the range cannot loosen matching.
    limit = 4
    if scaled != 0:
        import math

        limit = max(4, min(10, int(-math.floor(math.log10(abs(scaled)))) + 4))
    for places in range(limit + 1):
        text = f"{scaled:.{places}f}"
        shown = float(text)
        if scaled == 0:
            if shown == 0:
                forms.add(text)
            continue
        if abs(shown - scaled) / abs(scaled) <= RENDER_TOLERANCE:
            forms.add(text)
    return {f for f in forms if f}


def renderings(value: float) -> set[str]:
    """Forms a document uses when it states the value as it is."""
    return _forms(value, 1.0)


def percent_renderings(value: float) -> set[str]:
    """Forms a document uses when it states the value as a percentage.

    Applied only where the claim is actually marked as a percentage. Applying the
    hundred times rescale everywhere is what let a share of 0.0066 back a claim of
    0.66 about something unrelated.
    """
    return _forms(value, 100.0)


def in_percent_context(line: str, token: str, following: str = "") -> bool:
    """Whether this token is written as a percentage.

    The next line is appended before searching because prose wraps. A paragraph
    reading "rose from 6.52 to 9.69" then "percent." on the next line left 9.69
    outside percent context and therefore unbacked, while the identical claim
    unwrapped was backed. Only a token at the very end of a line can reach into the
    following one, because the window is measured from the token.
    """
    probe = line if not following else f"{line} {following.lstrip()}"
    for match in re.finditer(re.escape(token), probe):
        tail = probe[match.end() : match.end() + 10].lstrip()
        if tail.startswith("%") or tail.lower().startswith("percent"):
            return True
    return False


# An external category exists so that "unbacked" can mean one thing: this project
# asserted a number it cannot reproduce, which is a defect. A figure quoted from
# somebody else's paper is not that, and mixing the two means the headline can never
# reach zero, at which point a ratchet with permanent residents stops being watched.
#
# External status is earned, not fallen into. A paragraph qualifies only if it carries
# BOTH a resolvable citation and a recorded read depth. Without both requirements the
# category is an escape hatch and every awkward number migrates into it.
EXTERNAL_CITATION = re.compile(r"\bdoi:|\bdoi\.org/|\bPMC\d{4,}|\barXiv:", re.IGNORECASE)
READ_DEPTH = re.compile(
    r"read at full text|read depth:|\bunverified\b|abstract only|metadata only"
    r"|read in full",
    re.IGNORECASE,
)


def external_lines(text: str) -> set[int]:
    """Line numbers sitting in a paragraph that cites a source and states a read depth.

    Paragraph scoped rather than line scoped because a citation and the figures it
    supports are routinely on different lines of the same wrapped paragraph.
    """
    qualifying: set[int] = set()
    start = 1
    buffer: list[str] = []

    def flush(first: int, lines: list[str]) -> None:
        if not lines:
            return
        joined = "\n".join(lines)
        if EXTERNAL_CITATION.search(joined) and READ_DEPTH.search(joined):
            qualifying.update(range(first, first + len(lines)))

    for number, line in enumerate(text.splitlines(), start=1):
        if line.strip():
            if not buffer:
                start = number
            buffer.append(line)
        else:
            flush(start, buffer)
            buffer = []
    flush(start, buffer)
    return qualifying


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
    for path in evidence_documents():
        # The digest line is an identifier. Its hex could contain a run of digits, and
        # an identifier must never be able to back a claim. D121.
        text = "\n".join(line for line in path.read_text().splitlines() if DIGEST_LABEL not in line)
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
        # The label of record, not the stored column, which predates the withdrawal of
        # the wildfire class and carries no GEM term. This is the strongest provenance
        # tier the tracer has, so reading the stale column here would have certified
        # stale class counts at the highest confidence it gives. D121.
        "detections.trained_class_rows": (
            "SELECT count(*) FROM a.detection_context c "
            "LEFT JOIN a.detection_gem g USING (detection_id) "
            f"WHERE {weak_label_sql('c', 'g')} IN ('flare','industrial','agricultural')"
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
        f"SELECT {weak_label_sql('c', 'g')} AS label, count(*) "
        "FROM a.detection_context c LEFT JOIN a.detection_gem g USING (detection_id) "
        "GROUP BY 1"
    ).fetchall()
    for name, count in per_class:
        values.append(Derived(float(count), f"detections.class.{name}", "live query"))
    return values


def classify(
    token: str,
    index: dict[str, list[Derived]],
    percent_index: dict[str, list[Derived]] | None = None,
) -> Finding:
    """Reproduced at the strongest available provenance, or unbacked.

    There is deliberately no numeric proximity heuristic. An earlier version
    flagged a value as a mismatch when it fell within two percent of any derived
    value, which matched publication years against cluster spreads in metres and
    produced 36 findings of which none was real. Proximity without a semantic link
    between the claim and the source is not evidence of anything. Real staleness is
    caught by REGISTRY below, which compares named claims against named sources.
    """
    hits = list(index.get(token) or [])
    if percent_index is not None:
        hits += percent_index.get(token) or []
    if not hits:
        return Finding("", 0, token, "", "unbacked")
    rank = {"live query": 0, "stored artifact": 1, "generated document": 2}
    best = sorted(hits, key=lambda d: rank.get(d.provenance, 9))[0]
    return Finding("", 0, token, "", "reproduced", f"{best.label} [{best.provenance}]")


# Headline claims mapped to the source that must still produce them. This is where
# a stale digit actually shows, because both sides name the same quantity.
REGISTRY: tuple[tuple[str, str, str, float], ...] = (
    ("b1 group_a macro F1", "b1_results", "option_a.group_a.macro avg.f1-score", 0.661),
    ("b1 group_b macro F1", "b1_results", "option_a.group_b.macro avg.f1-score", 0.612),
    ("b1 group_c macro F1", "b1_results", "option_a.group_c.macro avg.f1-score", 0.651),
    ("b1 leakage macro F1", "b1_results", "leakage_macro_f1", 0.9996),
    ("b1 clean macro F1", "b1_results", "clean_macro_f1", 0.6609),
    ("b2 industrial F1", "conformal_aoa_b2", "b2_industrial.f1", 0.518),
    ("b2 industrial precision", "conformal_aoa_b2", "b2_industrial.precision", 0.396),
    ("b2 industrial recall", "conformal_aoa_b2", "b2_industrial.recall", 0.746),
    ("conformal group_b coverage", "conformal_aoa_b2", "group_b.coverage", 0.8103),
    ("conformal group_c coverage", "conformal_aoa_b2", "group_c.coverage", 0.8472),
    ("persistent source count", "persistent_sources", "chosen_radius_m", 500.0),
    ("b4 train rows", "b4_results", "train_rows", 440.0),
    ("b4 tiles for 80 percent", "b4_support", "tiles_for_80_percent", 39.0),
    ("b1 ablation with recurrence", "b1_ablation", "overall.predicted_industrial_full", 0.874),
    (
        "b1 ablation without recurrence",
        "b1_ablation",
        "overall.predicted_industrial_without_recurrence",
        0.794,
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


# A figure is a claim like any other, and it is the one kind that cannot be checked
# by re-deriving a value: the number in the document and the number in the artifact
# can agree while the picture shows neither. That is the shape D61 had. A checker
# cannot read the picture, but it can insist the picture is not older than what it
# depicts.
FIGURE_SOURCES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("architecture.png", ("architecture.json",)),
    ("b1_pr_confusion.png", ("b1_results.json", "b1_confusion_group_a.npy")),
    ("conformal_aoa.png", ("conformal_aoa_b2.json",)),
    ("console_country.png", ("persistent_sources.json", "b1_results.json")),
    ("console_jharkhand.png", ("persistent_sources.json", "b1_results.json")),
    ("diurnal_comparison.png", ("seasonal_diurnal.json",)),
    ("lift_by_window.png", ("lift_with_gem.json",)),
    ("m1_intensity_signatures.png", ()),
    ("osm_coverage_density.png", ()),
)


def check_document_freshness() -> list[tuple[str, str]]:
    """Generated documents that no longer describe what regenerating them would say.

    Two ways, reported separately. The code that produced a document can have changed,
    which is caught exactly: each generator records a digest of its own code and every
    repository module it imports, and a mismatch means rerunning it would run different
    code. That is how m1_prototype.md went stale unnoticed, D117. Or the data can have
    changed since, caught conservatively by the last ingest date: fifteen documents were
    found predating an ingest, though six of nine regenerated byte identical once the
    analysis population was pinned, so an ingest flag is a reason to look rather than
    proof of a change. D113, D114, D121.

    Reported rather than failed, because a stale document is a queue item, not a broken
    build.
    """
    stale: list[tuple[str, str]] = []
    cutoff = None
    try:
        con = duckdb.connect(str(DUCKDB_PATH), read_only=True)
        last = con.execute("SELECT max(started_at) FROM ingest_runs").fetchone()[0]
        if last is not None and hasattr(last, "timestamp"):
            cutoff = (last.timestamp(), str(last)[:19])
    except (duckdb.Error, TypeError, AttributeError):
        cutoff = None
    for path in generated_documents("docs"):
        if path == OUTPUT:
            # This run rewrites its own report after checking, so the previous copy is
            # always about to be replaced and flagging it would be noise.
            continue
        name = path.relative_to(ROOT).as_posix()
        generator = declared_generator(path)
        recorded = recorded_digest(path)
        if generator is None or not generator.is_file():
            stale.append((name, "names no generator script that exists"))
        elif recorded is None:
            stale.append((name, "records no generator digest"))
        elif recorded != (current := generator_digest(generator)):
            stale.append((name, f"code changed, recorded {recorded} against {current}"))
        if cutoff and path.stat().st_mtime < cutoff[0]:
            stale.append((name, f"predates the last ingest at {cutoff[1]}"))
    return stale


def check_figure_freshness() -> list[tuple[str, str, str]]:
    """Report figures older than an artifact they depict.

    A figure with no listed artifact is derived from the database rather than from a
    fitted model, and is reported as unchecked rather than as passing, because a
    silent pass would be the same defect one level up.
    """
    findings = []
    for name, artifacts in FIGURE_SOURCES:
        figure = ROOT / "docs" / "figures" / name
        if not figure.is_file():
            findings.append((name, "missing", "the document references a figure that is absent"))
            continue
        if not artifacts:
            findings.append(
                (name, "unchecked", "no artifact registered, derived from the database")
            )
            continue
        drawn = figure.stat().st_mtime
        for artifact in artifacts:
            path = ARTIFACT_DIR / artifact
            if not path.is_file():
                findings.append((name, "unchecked", f"{artifact} absent"))
                continue
            if path.stat().st_mtime > drawn:
                findings.append(
                    (name, "STALE", f"older than {artifact}, which was rewritten after it")
                )
    return findings


def main() -> int:
    derived = derive_from_database() + derive_from_artifacts() + derive_from_generated_docs()
    print(
        f"derived {len(derived)} values: "
        f"{sum(1 for d in derived if d.provenance == 'live query')} by live query, "
        f"{sum(1 for d in derived if d.provenance == 'stored artifact')} from artifacts"
    )

    index: dict[str, list[Derived]] = {}
    percent_index: dict[str, list[Derived]] = {}
    for candidate in derived:
        for form in renderings(candidate.value):
            index.setdefault(form, []).append(candidate)
        for form in percent_renderings(candidate.value):
            percent_index.setdefault(form, []).append(candidate)

    findings: list[Finding] = []
    for relative in documents():
        path = ROOT / relative
        text = path.read_text()
        cited = external_lines(text)
        all_lines = text.splitlines()
        for number, line in enumerate(all_lines, start=1):
            if SKIP_LINE.search(line):
                continue
            for token in NUMBER.findall(line):
                if SKIP_CONTEXT.search(line) and token not in index:
                    continue
                if len(token.replace(",", "")) < 2 or NOT_A_CLAIM.match(token):
                    continue
                finding = classify(
                    token,
                    index,
                    percent_index
                    if in_percent_context(
                        line, token, all_lines[number] if number < len(all_lines) else ""
                    )
                    else None,
                )
                if finding.category == "unbacked" and number in cited:
                    finding.category = "external"
                finding.document, finding.line_number, finding.line = relative, number, line.strip()
                findings.append(finding)

    counts = {name: 0 for name in ("reproduced", "external", "unbacked")}
    for finding in findings:
        counts[finding.category] += 1
    total = len(findings)
    print(f"\n{total} numeric claims examined")
    for name, count in counts.items():
        print(f"  {name:12s} {count:5d}  {count / total:.1%}" if total else f"  {name}: 0")

    documents_stale = check_document_freshness()
    if documents_stale:
        print(f"\ngenerated documents that are stale: {len(documents_stale)}")
        for name, reason in documents_stale:
            print(f"  STALE: {name}, {reason}")
    else:
        print("\ngenerated documents: all match their generator code and postdate the ingest")

    figures = check_figure_freshness()
    stale = [f for f in figures if f[1] == "STALE"]
    print(f"\nfigures: {len(FIGURE_SOURCES)} referenced, {len(stale)} stale")
    for name, status, detail in figures:
        if status != "unchecked":
            print(f"  {status}: {name}, {detail}")

    OUTPUT.write_text(render(findings, counts, total, derived, figures))
    print(f"\nwrote {OUTPUT.relative_to(ROOT)}")
    return 0


def render(
    findings: list[Finding],
    counts: dict,
    total: int,
    derived: list[Derived],
    figures: list[tuple[str, str, str]],
) -> str:
    lines = [
        "# Can every published number be re-derived?",
        "",
        f"Regenerate: `uv run python {Path('scripts/verify_published_numbers.py')}`",
        provenance_line(__file__),
        "",
        "The suite pins that a claim points at a command. It does not pin that the",
        "command still produces the claim. This checks the second thing.",
        "",
        f"{total} numeric claims examined across {len(documents())} documents, against "
        f"{len(derived)} derived values.",
        "",
        "| Category | Count | Share |",
        "|---|---|---|",
    ]
    for name in ("reproduced", "external", "unbacked"):
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
        "## Figure freshness",
        "",
        "A figure is the one kind of claim that cannot be checked by re-deriving a",
        "value: the document and the artifact can agree while the picture shows",
        "neither. This does not read the picture. It insists the picture is not older",
        "than the artifact it depicts, which is the only part of that failure a checker",
        "can catch.",
        "",
        "| Figure | Status | Detail |",
        "|---|---|---|",
    ]
    for name, status, detail in figures:
        lines.append(f"| `{name}` | {status} | {detail} |")
    lines += [
        "",
        "`unchecked` is reported rather than silently passed. A figure with no",
        "registered artifact is drawn from the database, and a checker that called that",
        "a pass would be the same defect one level up.",
        "",
        "## External, quoted from cited sources",
        "",
        "Figures from other people's papers. These are not defects and they are not",
        "this project's to reproduce. Their correct backing is a citation with a stated",
        "read depth, which is what puts them here: a claim reaches this category only if",
        "its paragraph carries both a resolvable citation and a recorded read depth.",
        "Requiring both is what stops the category becoming an escape hatch for awkward",
        "numbers.",
        "",
        "They were counted as unbacked until 2026-09-20. At the changeover the headline",
        "moved from 76 unbacked of 527 to 71 unbacked and 5 external, with the reproduced",
        "count unchanged at 451. Both figures are recorded because relocating a number",
        "without saying so is the failure this report exists to catch.",
        "",
        "| Document | Line | Token | Claim |",
        "|---|---|---|---|",
    ]
    for finding in findings:
        if finding.category != "external":
            continue
        excerpt = finding.line[:90].replace("|", "\\|")
        lines.append(
            f"| {finding.document} | {finding.line_number} | {finding.token} | {excerpt} |"
        )
    lines += [
        "",
        "## Unbacked",
        "",
        "This project asserted these numbers and cannot re-derive them. Some are prose",
        "quantities that are",
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
    lines += [
        "",
        "## Reproduced, and by what",
        "",
        "A verdict that does not say what it matched cannot be audited. The spurious",
        "backing found in D101 was invisible for exactly that reason: the report said",
        "reproduced and stopped, when printing the source would have shown a burstiness",
        "separation being backed by an hourly detection share. Every reproduction is",
        "listed with the value that backs it, so a wrong match is visible on reading.",
        "",
        "| Document | Line | Token | Backed by |",
        "|---|---|---|---|",
    ]
    for finding in findings:
        if finding.category != "reproduced":
            continue
        lines.append(
            f"| {finding.document} | {finding.line_number} | {finding.token} | {finding.matched} |"
        )
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
