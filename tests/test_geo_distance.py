"""Distance must come back in metres. Both traps here return a plausible wrong
number rather than an error, so these tests exist before any spatial join does.
"""

import duckdb
import pytest

from ml.reference.geo import install_geo

# Published great circle distances, used as the external check. Both are quoted
# widely as aerial distances and both are matched to better than one percent.
DELHI = (77.2090, 28.6139)
MUMBAI = (72.8777, 19.0760)
DELHI_MUMBAI_PUBLISHED_M = 1_148_000.0

KOLKATA = (88.3639, 22.5726)
CHENNAI = (80.2707, 13.0827)
KOLKATA_CHENNAI_PUBLISHED_M = 1_366_000.0

TOLERANCE = 0.01


@pytest.fixture
def con() -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect()
    install_geo(connection)
    return connection


def distance(
    con: duckdb.DuckDBPyConnection, a: tuple[float, float], b: tuple[float, float]
) -> float:
    return float(
        con.execute("SELECT geo_distance_m(?, ?, ?, ?)", [a[0], a[1], b[0], b[1]]).fetchone()[0]
    )


class TestPublishedDistances:
    def test_delhi_to_mumbai_within_one_percent(self, con: duckdb.DuckDBPyConnection) -> None:
        measured = distance(con, DELHI, MUMBAI)
        error = abs(measured - DELHI_MUMBAI_PUBLISHED_M) / DELHI_MUMBAI_PUBLISHED_M
        assert error < TOLERANCE, f"{measured:.0f} m against {DELHI_MUMBAI_PUBLISHED_M:.0f} m"

    def test_kolkata_to_chennai_within_one_percent(self, con: duckdb.DuckDBPyConnection) -> None:
        measured = distance(con, KOLKATA, CHENNAI)
        error = abs(measured - KOLKATA_CHENNAI_PUBLISHED_M) / KOLKATA_CHENNAI_PUBLISHED_M
        assert error < TOLERANCE, f"{measured:.0f} m against {KOLKATA_CHENNAI_PUBLISHED_M:.0f} m"

    def test_result_is_metres_not_degrees(self, con: duckdb.DuckDBPyConnection) -> None:
        # The raw ST_Distance answer for this pair is about 10.5, in degrees.
        assert distance(con, DELHI, MUMBAI) > 1_000_000


class TestAxisOrderTrap:
    def test_macro_disagrees_with_the_naive_call(self, con: duckdb.DuckDBPyConnection) -> None:
        """Pins the trap. If a DuckDB release fixes the axis order, this fails and
        the macro must be revisited rather than silently double flipping."""
        naive = float(
            con.execute(
                "SELECT ST_Distance_Spheroid(ST_Point(?, ?), ST_Point(?, ?))",
                [DELHI[0], DELHI[1], MUMBAI[0], MUMBAI[1]],
            ).fetchone()[0]
        )
        assert abs(naive - DELHI_MUMBAI_PUBLISHED_M) / DELHI_MUMBAI_PUBLISHED_M > 0.1
        assert distance(con, DELHI, MUMBAI) > naive

    def test_one_degree_of_longitude_shrinks_with_latitude(
        self, con: duckdb.DuckDBPyConnection
    ) -> None:
        at_equator = distance(con, (0.0, 0.0), (1.0, 0.0))
        at_sixty = distance(con, (0.0, 60.0), (1.0, 60.0))
        assert 110_000 < at_equator < 112_000
        assert 55_000 < at_sixty < 56_500
        # If the axes were swapped both would come back at about 111 km.
        assert at_sixty < at_equator * 0.55

    def test_one_degree_of_latitude_is_stable_with_longitude(
        self, con: duckdb.DuckDBPyConnection
    ) -> None:
        near_west = distance(con, (68.0, 20.0), (68.0, 21.0))
        near_east = distance(con, (97.0, 20.0), (97.0, 21.0))
        assert abs(near_west - near_east) < 100
        assert 110_000 < near_west < 112_000


class TestGeometryMacro:
    def test_geom_macro_agrees_with_the_coordinate_macro(
        self, con: duckdb.DuckDBPyConnection
    ) -> None:
        from_coords = distance(con, DELHI, MUMBAI)
        from_geom = float(
            con.execute(
                "SELECT geo_distance_geom_m(geo_point(?, ?), geo_point(?, ?))",
                [DELHI[0], DELHI[1], MUMBAI[0], MUMBAI[1]],
            ).fetchone()[0]
        )
        assert abs(from_coords - from_geom) < 1.0

    def test_geo_point_stores_longitude_first(self, con: duckdb.DuckDBPyConnection) -> None:
        row = con.execute(
            "SELECT ST_X(geo_point(77.2090, 28.6139)), ST_Y(geo_point(77.2090, 28.6139))"
        ).fetchone()
        assert abs(row[0] - 77.2090) < 1e-9
        assert abs(row[1] - 28.6139) < 1e-9


class TestAreaAxisTrap:
    """ST_Area_Spheroid shares the axis convention. It returns NaN east of 90
    degrees and a value roughly four times too small elsewhere."""

    def test_flipped_area_matches_published_state_areas(
        self, con: duckdb.DuckDBPyConnection
    ) -> None:
        # A square degree box near the equator, used instead of real geometry so
        # the test needs no loaded reference layer.
        measured = float(
            con.execute(
                "SELECT geo_area_km2(ST_GeomFromText('POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))'))"
            ).fetchone()[0]
        )
        # One degree square at the equator is about 12300 square kilometres.
        assert 12_200 < measured < 12_400

    def test_area_macro_survives_east_of_ninety_degrees(
        self, con: duckdb.DuckDBPyConnection
    ) -> None:
        # Mizoram sits near 93 E. Unflipped this returns NaN.
        measured = float(
            con.execute(
                "SELECT geo_area_km2(ST_GeomFromText("
                "'POLYGON((92 23, 93 23, 93 24, 92 24, 92 23))'))"
            ).fetchone()[0]
        )
        assert measured == measured, "area came back NaN, the flip is not applied"
        assert 11_000 < measured < 12_000

    def test_naive_area_call_is_still_broken(self, con: duckdb.DuckDBPyConnection) -> None:
        naive = float(
            con.execute(
                "SELECT ST_Area_Spheroid(ST_GeomFromText("
                "'POLYGON((92 23, 93 23, 93 24, 92 24, 92 23))'))"
            ).fetchone()[0]
        )
        assert naive != naive, "ST_Area_Spheroid no longer returns NaN, revisit the macro"
