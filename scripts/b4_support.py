"""Measure how much held out evaluation support one Sentinel-2 scene actually gives B4.

B4 has to be comparable to B1 and B2 on the same spatially blocked groups, under
the D32 contract. Whether a single scene can carry that comparison is a question
about detection geography, not about imagery, so it is answerable before any
product is downloaded and before an account exists.

Writes docs/b4_support.md.
"""

import json
import math
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml.documents import provenance_line
from ml.imagery.catalogue import search_l2a
from ml.labels.splits import HELD_OUT_GROUPS
from ml.labels.weak import weak_label_sql
from ml.paths import ARTIFACT_DIR, DUCKDB_PATH, ROOT, ensure_dir
from ml.reference.geo import GEO_MACROS

PROBE_LON = 82.6757
PROBE_LAT = 24.1030
WINDOW_START = datetime(2024, 10, 1, tzinfo=UTC)
WINDOW_END = datetime(2024, 12, 1, tzinfo=UTC)
TRAINED_CLASSES = ("flare", "industrial", "agricultural")
OUTPUT = ROOT / "docs" / "b4_support.md"
_FIELDS = ("rows", "tiles_touched", "tiles_for_80", "tiles_for_95")

# The Sentinel-2 tiling grid is MGRS, which is a UTM construct and not expressible
# in degrees. Approximating it by a degree grid aligned to the measured T44QPM
# footprint keeps the tile count honest to within a partially covered tile at each
# edge, which is enough to answer a question about order of magnitude.
TILE_DLON = 1.0900
TILE_DLAT = 1.0020


def _connect() -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect()
    connection.execute("INSTALL spatial; LOAD spatial;")
    for macro in GEO_MACROS:
        connection.execute(macro)
    connection.execute(f"ATTACH '{DUCKDB_PATH}' AS a (READ_ONLY);")
    return connection


def _group_of(state: str | None, membership: dict[str, str]) -> str:
    if state is None:
        return "no state"
    return membership.get(state, "train, not held out")


def main() -> None:
    products = search_l2a(
        longitude=PROBE_LON, latitude=PROBE_LAT, start=WINDOW_START, end=WINDOW_END
    )
    if not products:
        raise SystemExit("catalogue returned no L2A products over the probe point")
    scene = products[0]
    if scene.footprint_wkt is None:
        raise SystemExit(f"{scene.name} carries no footprint, cannot measure support")

    connection = _connect()
    membership = {s: g for g, states in HELD_OUT_GROUPS.items() for s in states}

    in_scene = connection.execute(
        f"""
        SELECT c.state_name, {weak_label_sql("c", "g")} AS weak_label, count(*)
        FROM a.detections d JOIN a.detection_context c USING (detection_id)
        LEFT JOIN a.detection_gem g USING (detection_id)
        WHERE ST_Within(geo_point(d.longitude, d.latitude), ST_GeomFromText(?))
        GROUP BY 1, 2
        """,
        [scene.footprint_wkt],
    ).fetchall()

    by_group: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    # Seed every held out group so a group the scene never reaches renders as a
    # row of zeros. An absent row reads as an oversight; a zero reads as measured.
    for group in HELD_OUT_GROUPS:
        by_group[group]
    for state, label, count in in_scene:
        by_group[_group_of(state, membership)][label] += count

    everything = connection.execute(
        f"""
        SELECT c.state_name, d.longitude, d.latitude
        FROM a.detections d JOIN a.detection_context c USING (detection_id)
        LEFT JOIN a.detection_gem g USING (detection_id)
        WHERE {weak_label_sql("c", "g")} IN ('flare', 'industrial', 'agricultural')
          AND c.state_name IS NOT NULL
        """
    ).fetchall()

    origin_lon, origin_lat = _footprint_origin(scene.footprint_wkt)
    tiles_needed: dict[str, tuple[int, int, int, int]] = {}
    for group in sorted(HELD_OUT_GROUPS):
        points = [(lon, lat) for state, lon, lat in everything if membership.get(state) == group]
        tiles = Counter(
            (
                math.floor((lon - origin_lon) / TILE_DLON),
                math.floor((lat - origin_lat) / TILE_DLAT),
            )
            for lon, lat in points
        )
        tiles_needed[group] = (len(points), len(tiles), *_tiles_for_coverage(tiles))

    OUTPUT.write_text(_render(scene, by_group, tiles_needed))
    print(f"wrote {OUTPUT.relative_to(ROOT)}")

    tiles_for_80 = sum(entry[2] for entry in tiles_needed.values())
    artifact = ensure_dir(ARTIFACT_DIR) / "b4_support.json"
    artifact.write_text(
        json.dumps(
            {
                "scene": scene.name,
                "cloud_cover_pct": scene.cloud_cover_pct,
                "scene_size_gb": round(scene.size_gb, 3),
                "tiles_for_80_percent": tiles_for_80,
                "tiles_for_95_percent": sum(entry[3] for entry in tiles_needed.values()),
                "gb_for_80_percent": round(tiles_for_80 * scene.size_gb, 1),
                "per_group": {
                    g: dict(zip(_FIELDS, v, strict=True)) for g, v in tiles_needed.items()
                },
            },
            indent=2,
            allow_nan=False,
        )
    )
    print(f"wrote {artifact.relative_to(ROOT)}")
    held_out = sum(
        counts.get(c, 0)
        for group, counts in by_group.items()
        if group in HELD_OUT_GROUPS
        for c in TRAINED_CLASSES
    )
    print(f"scene {scene.name[:44]} at {scene.cloud_cover_pct:.4f} percent cloud")
    print(f"held out trained class detections inside it: {held_out}")
    for group in sorted(HELD_OUT_GROUPS):
        counts = by_group[group]
        print(f"  {group}: {sum(counts.get(c, 0) for c in TRAINED_CLASSES)}")


def _footprint_origin(wkt: str) -> tuple[float, float]:
    coords = wkt[wkt.index("((") + 2 : wkt.index("))")].split(",")
    pairs = [tuple(float(v) for v in c.strip().split()) for c in coords]
    return min(p[0] for p in pairs), min(p[1] for p in pairs)


def _tiles_for_coverage(tiles: Counter) -> tuple[int, int]:
    total = sum(tiles.values())
    accumulated = 0
    at_80 = at_95 = 0
    for rank, (_, count) in enumerate(tiles.most_common(), start=1):
        accumulated += count
        if not at_80 and accumulated >= 0.80 * total:
            at_80 = rank
        if not at_95 and accumulated >= 0.95 * total:
            at_95 = rank
    return at_80, at_95


def _render(scene, by_group: dict, tiles_needed: dict) -> str:
    lines = [
        "# How much of the evaluation set does one Sentinel-2 scene reach?",
        "",
        f"Regenerate: `uv run python {Path('scripts/b4_support.py')}`",
        provenance_line(__file__),
        "",
        f"Scene: `{scene.name}`",
        "",
        f"Cloud cover {scene.cloud_cover_pct:.4f} percent, {scene.size_gb:.2f} GB, "
        f"sensed {scene.sensing_start.date()}. It is the least cloudy of the "
        "L2A products over the Singrauli probe point in the window.",
        "",
        "## Detections inside the scene footprint",
        "",
        "| Group | flare | industrial | agricultural | other | total |",
        "|---|---|---|---|---|---|",
    ]
    for group in sorted(by_group):
        counts = by_group[group]
        other = sum(v for k, v in counts.items() if k not in TRAINED_CLASSES)
        lines.append(
            f"| {group} | {counts.get('flare', 0)} | {counts.get('industrial', 0)} | "
            f"{counts.get('agricultural', 0)} | {other} | {sum(counts.values())} |"
        )
    lines += [
        "",
        "## Tiles required to reach the held out groups",
        "",
        "Counted on a degree grid aligned to the measured footprint, which "
        "approximates the MGRS tiling to within a partial tile per edge.",
        "",
        "| Group | Trained class rows | Tiles touched | Tiles for 80 percent |"
        " Tiles for 95 percent |",
        "|---|---|---|---|---|",
    ]
    total_80 = 0
    for group in sorted(tiles_needed):
        rows, touched, at_80, at_95 = tiles_needed[group]
        total_80 += at_80
        lines.append(f"| {group} | {rows} | {touched} | {at_80} | {at_95} |")
    lines += [
        "",
        f"Reaching 80 percent of all three held out groups needs {total_80} tiles, "
        f"which at {scene.size_gb:.2f} GB per date is {total_80 * scene.size_gb:.0f} GB "
        "for a single pass.",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    main()
