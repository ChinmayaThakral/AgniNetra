"""How far do you have to search before every persistent source has a reference asset?

D56 retracted the claim that some persistent sources are absent from every registry,
on the grounds that at a 5 km search radius none of the then 21 candidates lacked an
asset. That sweep was run ad hoc and never committed, so when the D61 rebuild changed
the candidate set from 21 to 53 there was no way to recheck it except by hand. This
is that sweep, as a script.

The point is not the radius. It is that a point proximity test is the wrong
instrument for an areal source: a coal seam fire spans a coalfield while a registry
holds mines as points, so a well documented fire reads as unregistered at 1 km.

Writes docs/registry_radius_sweep.md.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import duckdb

from ml.paths import ARTIFACT_DIR, DUCKDB_PATH, ROOT
from ml.reference.geo import GEO_MACROS

RADII_M = (1000, 2000, 3000, 5000, 10000)
OUTPUT = ROOT / "docs" / "registry_radius_sweep.md"


def main() -> int:
    sources = json.loads((ARTIFACT_DIR / "persistent_sources.json").read_text())["sources"]
    unregistered = [s for s in sources if not s["registered"]]
    print(f"{len(sources)} persistent sources, {len(unregistered)} unregistered at the 1 km rule")

    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial;")
    for macro in GEO_MACROS:
        con.execute(macro)
    con.execute(f"ATTACH '{DUCKDB_PATH}' AS a (READ_ONLY);")

    rows = []
    for radius in RADII_M:
        still_absent, counts = 0, []
        for source in unregistered:
            found = con.execute(
                """
                SELECT count(*) FROM a.ref_osm_industrial
                WHERE geo_distance_m(?, ?, longitude, latitude) <= ?
                """,
                [source["lon"], source["lat"], radius],
            ).fetchone()[0]
            gem = con.execute(
                """
                SELECT count(*) FROM a.ref_gem_assets
                WHERE geo_distance_m(?, ?, longitude, latitude) <= ?
                """,
                [source["lon"], source["lat"], radius],
            ).fetchone()[0]
            total = int(found) + int(gem)
            counts.append(total)
            if total == 0:
                still_absent += 1
        counts.sort()
        median = counts[len(counts) // 2] if counts else 0
        rows.append((radius, still_absent, median))
        print(
            f"  {radius / 1000:>5.0f} km: {still_absent} still absent, "
            f"median assets within {median}"
        )

    lines = [
        "# How far before every persistent source has a reference asset?",
        "",
        f"Regenerate: `uv run python {Path('scripts/registry_radius_sweep.py')}`",
        "",
        f"{len(sources)} persistent sources, of which {len(unregistered)} have no reference",
        "asset within the 1 km rule. Those are the candidates swept below.",
        "",
        "**Distances here are measured from the cluster centroid.** The `registered`",
        "flag in `persistent_sources.py` is measured from each member detection and takes",
        "the minimum, and a cluster spans up to several kilometres, so the two do not",
        "agree exactly. At 1 km this sweep finds one fewer absent source than the flag",
        "does, which is the size of that disagreement rather than an error in either. The",
        "member coordinates are not carried in the artifact, so the sweep cannot",
        "reproduce the flag's construction.",
        "",
        "| Search radius | Still with no reference asset | Median assets within |",
        "|---|---|---|",
    ]
    for radius, absent, median in rows:
        lines.append(f"| {radius // 1000} km | {absent} | {median} |")
    lines += [
        "",
        "A point proximity test is the wrong instrument for an areal source. A coal seam",
        "fire spans kilometres of coalfield while the registries hold mines as points, so",
        "a real and thoroughly documented fire reads as unregistered at 1 km. The OSM tag",
        "set carries no mining tags at all, only `landuse=industrial`, `man_made=works`,",
        "`man_made=flare` and `power=plant`, so a colliery could not have matched however",
        "close it was. D56.",
        "",
    ]
    OUTPUT.write_text("\n".join(lines))
    print(f"wrote {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
