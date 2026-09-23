"""Unbacked claims are a pinned set, and the report carries none it has not explained.

A count of unbacked claims can hold steady while one is fixed and another appears, so
the tracer pins them as a set keyed on document, nearest heading and value. This fails
on any unbacked claim not in the set and on any pin that no longer matches a claim, so
the set stays exact in both directions. The report may not hold an untriaged pin: every
number it prints without a source has a category and a reason. D122.

The documents and the database live on the owner's machine, so this skips elsewhere.
"""

import importlib.util
import json
import sys

import pytest

from ml.paths import DUCKDB_PATH, ROOT

if not (ROOT / "docs").is_dir() or not DUCKDB_PATH.is_file():
    pytest.skip("docs/ and the database are local only", allow_module_level=True)

_spec = importlib.util.spec_from_file_location(
    "verify_published_numbers", ROOT / "scripts" / "verify_published_numbers.py"
)
assert _spec is not None and _spec.loader is not None
tracer = importlib.util.module_from_spec(_spec)
sys.modules["verify_published_numbers"] = tracer
_spec.loader.exec_module(tracer)


@pytest.fixture(scope="module")
def traced():
    findings, _, texts = tracer.collect_findings()
    return findings, texts


def test_every_unbacked_claim_is_pinned_and_every_pin_is_live(traced) -> None:
    findings, texts = traced
    new, gone = tracer.unpinned(findings, texts)
    assert not new, "unbacked claims not in the baseline: " + ", ".join(
        f"{f.document}:{f.line_number} {f.token}" for f in new
    )
    assert not gone, f"pins that no longer match any claim, remove them: {gone}"


def test_the_report_has_no_untriaged_pin() -> None:
    baseline = json.loads(tracer.BASELINE.read_text())
    untriaged = [
        key
        for key, pin in baseline.items()
        if key.startswith("docs/report.md") and pin["category"] == "untriaged"
    ]
    assert not untriaged, f"numbers in the report with no source and no reason: {untriaged}"
    for key, pin in baseline.items():
        if pin["category"] != "untriaged":
            assert len(pin["reason"]) > 10, f"{key}: a categorised pin needs its reason"
