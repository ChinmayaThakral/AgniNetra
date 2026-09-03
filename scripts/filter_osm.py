#!/usr/bin/env python3
"""Filter the Geofabrik India extract down to the industrial tag sets.

The extract is roughly 1.7 GB of protobuf. It is streamed once with osmium and
only the matching features are written out, because reading it in Python row by
row or loading it whole are both far slower than the filter.

Tag sets extracted:
    landuse=industrial
    man_made=works
    man_made=flare
    power=plant

Nodes and ways both carry these tags. Ways are reduced to their centroid using
the node locations cached by the location handler, because the label join needs a
representative point and a full polygon store would be a phase 3 concern.

Administrative boundaries at level 4, the Indian states, are collected separately
so that the coverage counts can be produced from the same snapshot.

Usage:
    uv run python scripts/filter_osm.py
"""

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import osmium

from ml.paths import ROOT, ensure_dir

PBF = ROOT / "data" / "raw" / "osm" / "india-latest.osm.pbf"
OUT_DIR = ROOT / "data" / "reference"

INDUSTRIAL_TAGS = (
    ("landuse", "industrial"),
    ("man_made", "works"),
    ("man_made", "flare"),
    ("power", "plant"),
)


def matches(tags: object) -> tuple[str, str] | None:
    for key, value in INDUSTRIAL_TAGS:
        if tags.get(key) == value:
            return key, value
    return None


class IndustrialHandler(osmium.SimpleHandler):
    """Collects industrial features as representative points."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[dict[str, object]] = []
        self.skipped_ways = 0

    def _append(self, osm_id: int, kind: str, tags: object, lon: float, lat: float) -> None:
        hit = matches(tags)
        if hit is None:
            return
        key, value = hit
        self.rows.append(
            {
                "osm_type": kind,
                "osm_id": osm_id,
                "tag_key": key,
                "tag_value": value,
                "name": tags.get("name") or "",
                "operator": tags.get("operator") or "",
                "longitude": round(lon, 7),
                "latitude": round(lat, 7),
            }
        )

    def node(self, n: osmium.osm.Node) -> None:
        if matches(n.tags) is None:
            return
        self._append(n.id, "node", n.tags, n.location.lon, n.location.lat)

    def way(self, w: osmium.osm.Way) -> None:
        if matches(w.tags) is None:
            return
        try:
            lons = [node.lon for node in w.nodes if node.location.valid()]
            lats = [node.lat for node in w.nodes if node.location.valid()]
        except osmium.InvalidLocationError:
            self.skipped_ways += 1
            return
        if not lons:
            self.skipped_ways += 1
            return
        self._append(w.id, "way", w.tags, sum(lons) / len(lons), sum(lats) / len(lats))


def main() -> int:
    if not PBF.is_file():
        print(f"missing extract: {PBF}", file=sys.stderr)
        return 2

    ensure_dir(OUT_DIR)
    handler = IndustrialHandler()
    handler.apply_file(str(PBF), locations=True, idx="flex_mem")

    out = OUT_DIR / "osm_industrial.csv"
    fields = [
        "osm_type",
        "osm_id",
        "tag_key",
        "tag_value",
        "name",
        "operator",
        "longitude",
        "latitude",
    ]
    with out.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(handler.rows)

    print(f"features written: {len(handler.rows)}")
    print(f"ways skipped for missing node locations: {handler.skipped_ways}")
    print(f"output: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
