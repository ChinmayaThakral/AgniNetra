#!/usr/bin/env python3
"""Extract Indian administrative boundaries from the same OSM snapshot.

Coverage counts must come from the snapshot that produced the features, not from
a separate boundary file of a different vintage, otherwise the per state counts
and the features they count are describing two different worlds.

admin_level 4 is states and union territories. admin_level 6 is districts.

Usage:
    uv run python scripts/extract_osm_admin.py
"""

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import osmium

from ml.paths import ROOT, ensure_dir

PBF = ROOT / "data" / "raw" / "osm" / "india-latest.osm.pbf"
OUT_DIR = ROOT / "data" / "reference"
WANTED_LEVELS = {"4", "6"}


WKT = osmium.geom.WKTFactory()


def wanted(tags: object) -> bool:
    """Administrative boundary at one of the levels this project counts by."""
    return tags.get("boundary") == "administrative" and tags.get("admin_level") in WANTED_LEVELS


def main() -> int:
    if not PBF.is_file():
        print(f"missing extract: {PBF}", file=sys.stderr)
        return 2

    ensure_dir(OUT_DIR)
    rows: list[dict[str, object]] = []
    failed = 0

    # with_areas assembles multipolygon relations, which is how a state boundary
    # is represented. It implies a two pass read of the extract.
    processor = osmium.FileProcessor(str(PBF)).with_areas().with_locations()
    for obj in processor:
        if not isinstance(obj, osmium.osm.Area):
            continue
        if not wanted(obj.tags):
            continue
        try:
            geometry = WKT.create_multipolygon(obj)
        except (RuntimeError, osmium.InvalidLocationError):
            failed += 1
            continue
        if not geometry:
            failed += 1
            continue
        rows.append(
            {
                "osm_id": obj.orig_id(),
                "admin_level": obj.tags.get("admin_level"),
                "name": obj.tags.get("name") or "",
                "name_en": obj.tags.get("name:en") or "",
                "wkt": geometry,
            }
        )

    out = OUT_DIR / "osm_admin.csv"
    with out.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["osm_id", "admin_level", "name", "name_en", "wkt"]
        )
        writer.writeheader()
        writer.writerows(rows)

    levels: dict[str, int] = {}
    for row in rows:
        key = str(row["admin_level"])
        levels[key] = levels.get(key, 0) + 1
    print(f"areas written: {len(rows)}")
    print(f"areas whose geometry could not be assembled: {failed}")
    for level in sorted(levels):
        print(f"  admin_level {level}: {levels[level]}")
    print(f"output: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
