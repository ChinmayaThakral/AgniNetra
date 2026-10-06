"""What is known about one persistent hot spot, for the people asked to label it.

Everything here is measured from the project's own detection record and reference layers:
where the spot is, when the satellites saw it, how its heat behaves, and the nearest
mapped features around it. Nothing is guessed; a value that cannot be measured is left
out rather than filled in.
"""

import math
import statistics

import duckdb

from .build_chips import _distance_m

# A detection belongs to a spot when it lies within the spot's own spread plus one VIIRS
# pixel of its centre, and it recurs, the same rule the persistent source clustering uses.
PIXEL_M = 375.0
MIN_PRIORS = 20
NEAR_KM = 25.0

DETECTIONS_SQL = """
SELECT d.longitude, d.latitude, d.acq_date_ist, d.daynight, d.frp, d.family
FROM detections d JOIN detection_recurrence r USING (detection_id)
WHERE r.prior_count_90d >= ? AND d.longitude BETWEEN ? AND ? AND d.latitude BETWEEN ? AND ?
"""

# A few level 6 boundaries in OpenStreetMap are company townships, whose name would give a
# labeller the answer, so only names that are not a company's are used.
SUBDISTRICT_SQL = """
SELECT coalesce(name_en, name) AS place FROM ref_osm_admin
WHERE admin_level = '6' AND ST_Contains(geom, ST_Point(?, ?))
  AND NOT regexp_matches(lower(coalesce(name_en, name)),
                         'limited|ltd|steel|plant|power|cement|mine|industr')
LIMIT 1
"""
# A month counts as observed when the record holds detections on at least this many days
# of it; the record covers burning seasons, not whole years.
OBSERVED_DAYS = 20

OSM_WORDS = {
    ("landuse", "industrial"): "industrial area",
    ("man_made", "works"): "works or factory",
    ("power", "plant"): "power plant",
    ("man_made", "flare"): "gas flare",
}


def gem_kind(tracker: str) -> str:
    name = tracker.lower()
    for word, kind in (
        ("steel", "steel or iron plant"),
        ("coal mine", "coal mine"),
        ("power", "power plant"),
        ("cement", "cement plant"),
    ):
        if word in name:
            return kind
    return "industrial asset"


def _box(lon: float, lat: float, metres: float) -> tuple[float, float, float, float]:
    dlat = metres / 111_320.0
    dlon = metres / (111_320.0 * max(math.cos(math.radians(lat)), 0.01))
    return lon - dlon, lon + dlon, lat - dlat, lat + dlat


def _nearest(rows: list[tuple], lon: float, lat: float) -> tuple[float, tuple] | None:
    best = None
    for row in rows:
        d = _distance_m((lon, lat), (row[0], row[1]))
        if best is None or d < best[0]:
            best = (d, row)
    return best


def observed_months(db: duckdb.DuckDBPyConnection) -> list[int]:
    """Months, 1 to 12, that the detection record actually covers."""
    rows = db.execute(
        "SELECT month(acq_date_ist), count(DISTINCT acq_date_ist) FROM detections GROUP BY 1"
    ).fetchall()
    return sorted(m for m, days in rows if days >= OBSERVED_DAYS)


def details_for(db: duckdb.DuckDBPyConnection, site: dict, observed: list[int]) -> dict:
    lon, lat = site["lon"], site["lat"]
    reach = site["spreadM"] + PIXEL_M
    x0, x1, y0, y1 = _box(lon, lat, reach)
    rows = [
        r
        for r in db.execute(DETECTIONS_SQL, [MIN_PRIORS, x0, x1, y0, y1]).fetchall()
        if _distance_m((lon, lat), (r[0], r[1])) <= reach
    ]
    out: dict = {
        "lon": round(lon, 4),
        "lat": round(lat, 4),
        "state": site["state"],
        "detections": site["detections"],
        "night_share": site["nightFraction"],
        "spread_m": site["spreadM"],
    }
    subdistrict = db.execute(SUBDISTRICT_SQL, [lon, lat]).fetchone()
    if subdistrict and subdistrict[0]:
        out["subdistrict"] = subdistrict[0]
    if rows:
        dates = sorted(r[2] for r in rows)
        out["first_seen"] = dates[0].isoformat()
        out["last_seen"] = dates[-1].isoformat()
        out["days_seen"] = len(set(dates))
        months = [0] * 12
        for r in rows:
            months[r[2].month - 1] += 1
        out["by_month"] = months
        out["observed_months"] = observed
        frps = [r[4] for r in rows if r[4] is not None and r[4] > 0]
        if frps:
            out["median_frp_mw"] = round(statistics.median(frps), 1)
        out["satellites"] = sorted({r[5] for r in rows if r[5]})

    near: list[dict] = []
    x0, x1, y0, y1 = _box(lon, lat, NEAR_KM * 1000)
    osm = db.execute(
        "SELECT longitude, latitude, tag_key, tag_value, name FROM ref_osm_industrial "
        "WHERE longitude BETWEEN ? AND ? AND latitude BETWEEN ? AND ?",
        [x0, x1, y0, y1],
    ).fetchall()
    found = _nearest(osm, lon, lat)
    if found:
        d, row = found
        near.append(
            {
                "what": OSM_WORDS.get((row[2], row[3]), "industrial feature"),
                "name": row[4] or None,
                "km": round(d / 1000, 1),
                "source": "OpenStreetMap",
            }
        )
    gem = db.execute(
        "SELECT longitude, latitude, tracker, name, status FROM ref_gem_assets "
        "WHERE longitude BETWEEN ? AND ? AND latitude BETWEEN ? AND ?",
        [x0, x1, y0, y1],
    ).fetchall()
    found = _nearest(gem, lon, lat)
    if found:
        d, row = found
        near.append(
            {
                "what": gem_kind(row[2]),
                "name": row[3] or None,
                "km": round(d / 1000, 1),
                "source": "Global Energy Monitor",
            }
        )
    flares = db.execute(
        "SELECT longitude, latitude FROM ref_flares "
        "WHERE longitude BETWEEN ? AND ? AND latitude BETWEEN ? AND ?",
        [x0, x1, y0, y1],
    ).fetchall()
    found = _nearest(flares, lon, lat)
    if found:
        near.append(
            {
                "what": "gas flare",
                "name": None,
                "km": round(found[0] / 1000, 1),
                "source": "VIIRS flare catalogue",
            }
        )
    out["nearby"] = sorted(near, key=lambda n: n["km"])
    return out
