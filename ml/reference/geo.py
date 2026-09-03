"""Distance and geometry helpers, and the one axis order trap this project has.

Two separate traps live here, and both return a plausible wrong number rather than
an error.

Trap one, units. `ST_Distance` on unprojected longitude and latitude returns
degrees, not metres. The phase 0 acceptance check used planar points where that
was correct. For a nearest asset query it is not.

Trap two, axis order. DuckDB's `ST_Distance_Sphere` and `ST_Distance_Spheroid`
read the first ordinate as latitude and the second as longitude, which is the
reverse of the `ST_Point(x, y)` convention used for storage, by GeoJSON, and by
`ST_Transform`. Measured on 2026-09-03 with duckdb 1.5.5:

    one degree of longitude at latitude 60, true value about 55.66 km
      ST_Point(lat, lon) ordering: 55596.9 m, correct
      ST_Point(lon, lat) ordering: 111194.9 m, wrong and silent

`ST_Area_Spheroid` shares the convention, and it fails louder. Read in storage
order, Madhya Pradesh measures 68940 square kilometres against a published
308252, and every state east of 90 degrees returns NaN because its longitude is
read as a latitude above 90. Flipped, four states match their published areas to
within 0.1 percent.

Geometry is therefore stored in the standard longitude then latitude order, and
nothing calls the spherical functions directly. The macros here are the only
place the flip happens.

Projection was rejected for the general case. Measured against the geodesic for
Delhi to Mumbai: UTM zone 43N is 0.02 percent out, but India spans UTM zones 42 to
47 and a nearest neighbour query that crosses a zone boundary is wrong. The India
NSF Lambert conformal conic, EPSG:7755, holds for the whole country but is 1.8
percent out over that distance. The spheroid function is correct everywhere and
needs no zone bookkeeping. Recorded as D10.
"""

from typing import Final

import duckdb

# Storage order is longitude then latitude. The macro flips for the spheroid call.
GEO_MACROS: Final[tuple[str, ...]] = (
    """
    CREATE OR REPLACE MACRO geo_point(lon, lat) AS
        ST_Point(lon, lat);
    """,
    """
    CREATE OR REPLACE MACRO geo_distance_m(lon_a, lat_a, lon_b, lat_b) AS
        ST_Distance_Spheroid(ST_Point(lat_a, lon_a), ST_Point(lat_b, lon_b));
    """,
    """
    CREATE OR REPLACE MACRO geo_area_km2(geom) AS
        ST_Area_Spheroid(ST_FlipCoordinates(geom)) / 1e6;
    """,
    """
    CREATE OR REPLACE MACRO geo_distance_geom_m(geom_a, geom_b) AS
        ST_Distance_Spheroid(
            ST_Point(ST_Y(geom_a), ST_X(geom_a)),
            ST_Point(ST_Y(geom_b), ST_X(geom_b))
        );
    """,
)


def install_geo(con: duckdb.DuckDBPyConnection) -> None:
    """Load the spatial extension and register the distance macros."""
    con.execute("INSTALL spatial; LOAD spatial;")
    for macro in GEO_MACROS:
        con.execute(macro)
