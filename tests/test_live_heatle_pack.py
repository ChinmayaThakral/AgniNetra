"""Practice Heatle carries every verified site, each a valid puzzle like the daily one."""

import json

from apps.live.pipeline.feed import validate_heatle
from ml.paths import ROOT

PACK = ROOT / "apps" / "live" / "web" / "public" / "game" / "heatle.json"
REFERENCE = ROOT / "apps" / "live" / "pipeline" / "reference_pack.json"


def test_every_verified_site_is_a_valid_practice_puzzle() -> None:
    puzzles = json.loads(PACK.read_text())["puzzles"]
    sites = json.loads(REFERENCE.read_text())["heatle"]
    assert len(puzzles) == len(sites)
    assert [p["answer"] for p in puzzles] == [s["answer"] for s in sites]
    for puzzle in puzzles:
        validate_heatle(puzzle)
