"""Every verified Heatle site as a puzzle, for practice rounds after the daily one.

Usage, from the repository root, after the reference pack or its pictures change:
    uv run python -m apps.live.pipeline.build_heatle_pack

The daily puzzle still comes from the evening feed. This file holds the same puzzles
for all the sites at once, so a player can keep learning after today's is done.
"""

import json
import sys

from ml.paths import ROOT

from .build_feed import PIPELINE, heatle_puzzle
from .feed import validate_heatle

OUT = ROOT / "apps" / "live" / "web" / "public" / "game" / "heatle.json"


def main() -> int:
    pack = json.loads((PIPELINE / "reference_pack.json").read_text())
    puzzles = [heatle_puzzle(site) for site in pack["heatle"]]
    for puzzle in puzzles:
        validate_heatle(puzzle)
    credit = pack.get("imagery_credit")
    data = {"schema": "agninetra-heatle/1", "credit": credit, "puzzles": puzzles}
    OUT.write_text(json.dumps(data, separators=(",", ":")) + "\n")
    print(f"{len(puzzles)} puzzles written to {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
