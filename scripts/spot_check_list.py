#!/usr/bin/env python3
"""The persistent sources that survive a registry search, as a checkable list.

`scripts/registry_radius_sweep.py` reports how many candidates survive each search
radius and never names them, so the imagery spot check the results section asks for had
nothing to work from. This writes the survivors out with the context a person needs to
judge each one in a browser, and a map link per row.

Night fraction is carried as context and not as evidence. The reasoning that it should
discriminate is sound, a coal seam fire burns through the night and crop residue burning
does not, but it was measured and it does not: these candidates have a median night
fraction of 1.00 against a median of 1.00 across all 263 persistent sources, and 6 of 8
sit at or above 0.97 against 60 percent of the full set. Persistence already selects for
night burning, so the column separates nothing here.

This decides nothing. Whether a candidate is genuinely absent from every registry cannot
be established from point proximity against a tag set that carries no mining category,
which is why the claim stays retracted. This only makes the looking cheap.

Usage:
    uv run python scripts/spot_check_list.py [--radius-m 5000]
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml.paths import ARTIFACT_DIR, ROOT


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--radius-m", type=float, default=5000.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    path = ARTIFACT_DIR / "persistent_sources.json"
    if not path.is_file():
        print(f"BLOCKED: {path} missing, run scripts/persistent_sources.py", file=sys.stderr)
        return 2
    payload = json.loads(path.read_text())

    # nearestAssetM is None when no catalogued asset was found at any distance, which
    # persistent_sources.py writes in place of a 1e12 sentinel. That is the strongest
    # candidate in the set, not a missing value, so it survives every radius. Coalescing
    # it to a number here would either drop it or invent a distance for it.
    def survives(source: dict) -> bool:
        distance = source["nearestAssetM"]
        return distance is None or float(distance) > args.radius_m

    rows = [s for s in payload["sources"] if survives(s)]
    rows.sort(key=lambda s: -int(s["detections"]))

    km = args.radius_m / 1000.0
    print(f"{len(rows)} of {len(payload['sources'])} persistent sources have no")
    print(f"catalogued asset within {km:.0f} km, measured from each member detection\n")

    header = (
        "| # | State | Latitude | Longitude | Detections | Spread m | Night frac | "
        "Nearest asset | Map | What the imagery shows |"
    )
    lines = [
        f"# Persistent sources surviving a {km:.0f} km registry search",
        "",
        "Regenerate: `uv run python scripts/spot_check_list.py`",
        "",
        "These are the candidates the results section asks somebody to check against",
        "imagery. Proximity cannot settle whether a source is genuinely absent from every",
        "registry: the reference tag set carries no mining category, and a point test is",
        "the wrong instrument for an areal source. The last column is filled in by a",
        "person looking, and is the only column that can close the question.",
        "",
        "Night fraction is context, not evidence. It was checked against the base rate",
        "and does not separate these candidates: median 1.00 here against median 1.00",
        "across all 263 persistent sources. Persistence already selects for night",
        "burning.",
        "",
        header,
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for n, s in enumerate(rows, start=1):
        lat, lon = float(s["lat"]), float(s["lon"])
        link = f"https://www.google.com/maps/@{lat:.4f},{lon:.4f},15z/data=!3m1!1e3"
        raw = s["nearestAssetM"]
        nearest = "none found" if raw is None else f"{float(raw) / 1000:.1f} km"
        print(
            f"  {n}. {s['state']!s:16s} {lat:8.4f} {lon:8.4f}  {int(s['detections']):5d} det  "
            f"night {float(s['nightFraction']):.2f}  nearest {nearest}"
        )
        lines.append(
            f"| {n} | {s['state']} | {lat:.4f} | {lon:.4f} | {int(s['detections'])} | "
            f"{float(s['spreadM']):.0f} | {float(s['nightFraction']):.2f} | "
            f"{nearest} | [satellite]({link}) | not checked |"
        )
    lines.append("")
    out = ROOT / "docs" / "spot_check_candidates.md"
    out.write_text("\n".join(lines))
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
