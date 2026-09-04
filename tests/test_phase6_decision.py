"""The phase 6 decision must say the same thing in all three places it appears.

D58 is recorded in the phase file, in results.md and in the model card. The risk
is drift: one of them decaying into "blocked on MOSDAC", or the flare kernel
quietly becoming confirmed. D42 exists because that is how the last one went.
"""

from ml.paths import ROOT

PHASE_6 = (ROOT / "context" / "phases" / "PHASE_6.md").read_text()
RESULTS = (ROOT / "docs" / "results.md").read_text()
CARD = (ROOT / "docs" / "model_card.md").read_text()
DECISIONS = (ROOT / "context" / "DECISIONS.md").read_text()


def test_d58_is_recorded_in_all_three_places() -> None:
    for name, text in (("PHASE_6.md", PHASE_6), ("results.md", RESULTS), ("model_card.md", CARD)):
        assert "D58" in text, f"{name} does not cite the phase 6 decision"


def test_the_decision_precedes_the_acceptance_it_supersedes() -> None:
    decision = PHASE_6.index("## Decision, 2026-09-05")
    acceptance = PHASE_6.index("## Acceptance")
    assert decision < acceptance, "the decision must be read before the criteria it supersedes"
    assert "Superseded by the decision above" in PHASE_6


def test_phase_6_is_not_described_as_blocked_on_mosdac() -> None:
    """The whole point of D58 is that this is a result, not a dependency."""
    for name, text in (("results.md", RESULTS), ("model_card.md", CARD)):
        for line in text.splitlines():
            lowered = line.lower()
            if "kaalchakra" in lowered and "mosdac" in lowered:
                raise AssertionError(f"{name} still ties KAALCHAKRA to MOSDAC: {line.strip()[:90]}")


def test_flare_kernel_is_unresolved_everywhere() -> None:
    assert "flare kernel stays unresolved" in RESULTS
    assert "unresolved, not confirmed" in RESULTS
    assert "## D42." in DECISIONS


def test_the_d39_correction_holds_in_the_decision_log() -> None:
    """PHASE_6.md said 'reduces' while the decision log still said 'removes'."""
    marker = DECISIONS.index("## D39.")
    body = DECISIONS[marker : marker + 700]
    assert "Superseded on one point by D58" in body
    assert "It reduces the thinning" in body


def test_both_refusals_state_their_cost() -> None:
    """A refusal without a price is indistinguishable from a shortfall."""
    assert "39 tiles" in CARD and "46 GB" in CARD
    assert "no price" in CARD or "carries none" in CARD


def test_the_evidence_is_not_described_as_four_independent_findings() -> None:
    """Three of the four were consequences of one measurement. Counting them
    separately inflates one result into three, which is the thing this project
    keeps catching itself doing."""
    import re

    pattern = re.compile(r"four\s+(independent\s+)?(findings|measurements|tests)", re.IGNORECASE)
    for name, text in (
        ("PHASE_6.md", PHASE_6),
        ("results.md", RESULTS),
        ("model_card.md", CARD),
        ("DECISIONS.md", DECISIONS),
    ):
        for line in text.splitlines():
            if pattern.search(line) and "not four independent findings" not in line:
                raise AssertionError(f"{name} counts the evidence as four: {line.strip()[:90]}")


def test_b1_independence_is_measured_not_asserted() -> None:
    assert "b1_recurrence_ablation" in RESULTS
    assert "## D60." in DECISIONS
    assert "mean_gap_days" in RESULTS, "the overlap must be named, not glossed"


def test_the_thread_determinism_finding_is_recorded() -> None:
    assert "## D59." in DECISIONS
    assert "OMP_NUM_THREADS" in DECISIONS


def test_flare_kernel_status_reaches_the_model_card() -> None:
    assert "unresolved, not confirmed" in CARD
    assert "D42" in CARD
