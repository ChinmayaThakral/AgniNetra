"""The model card is the phase 4 acceptance artefact and must not overstate.

It is generated from the recorded artifacts, so the risk is not a typo. The risk
is that a metric with almost no support behind it renders as a bare number, which
is how `0.000` outlives `0.000 on n=4`.
"""

import json
import re

from ml.paths import ARTIFACT_DIR, ROOT

CARD = ROOT / "docs" / "model_card.md"
TEXT = CARD.read_text()


def test_model_card_exists() -> None:
    assert CARD.is_file(), "results.md and the roadmap both reference it"


def test_thin_support_is_annotated() -> None:
    # ml/artifacts/ is never committed, so a clean clone has no b1_results.json and
    # the README quickstart would fail here. The test below already guarded the same
    # read; this one did not. D70.
    artifact = ARTIFACT_DIR / "b1_results.json"
    if not artifact.is_file():
        pytest.skip("b1_results.json absent, run scripts/train_b1.py first")
    b1 = json.loads(artifact.read_text())["option_a"]
    for group, entry in b1.items():
        for klass in ("flare", "industrial", "agricultural"):
            support = int(entry[klass]["support"])
            if support >= 30:
                continue
            expected = f"{entry[klass]['f1-score']:.3f} on n={support}"
            assert expected in TEXT, f"{group} {klass} has n={support} and must say so"


def test_b4_is_not_claimed_measured() -> None:
    b4 = ARTIFACT_DIR / "b4_results.json"
    if not b4.is_file():
        return
    status = json.loads(b4.read_text())["b4_status"]
    assert status in TEXT
    assert "not measured" in status, "if B4 ever becomes measured, this test should be revisited"


def test_no_bare_superlative() -> None:
    """The writing rules ban an unmeasured superlative. A model card is where one
    would appear first."""
    banned = ("state of the art", "best in class", "significantly better")
    found = [word for word in banned if word in TEXT.lower()]
    assert not found, found


def test_every_decision_reference_resolves() -> None:
    decisions = (ROOT / "context" / "DECISIONS.md").read_text()
    for reference in sorted(set(re.findall(r"\bD(\d+)\b", TEXT))):
        assert f"## D{reference}." in decisions, f"D{reference} does not exist"
