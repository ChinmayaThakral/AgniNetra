"""ESA WorldCover 10 m sampling.

DuckDB does not read GeoTIFF, so sampling happens with rasterio outside the
database and the sampled class values are written in as a column.

Tiles are 3 by 3 degrees, named by their south west corner. Over the India
bounding box, 102 of the 121 candidate tiles exist, totalling 7.50 GB, measured
on 2026-09-03. The rest are ocean.

The tile list is resolved from coordinates rather than downloaded wholesale, so a
sampling run pulls only the tiles its points actually fall in.
"""

import os
from pathlib import Path
from typing import Final

import rasterio

TILE_DEGREES: Final[int] = 3
S3_BASE: Final[str] = "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map"
PRODUCT_VERSION: Final[str] = "v200"
VINTAGE: Final[str] = "2021"

# ESA WorldCover class codes. Kept here rather than in a lookup table because the
# label rules in phase 3 read them by name.
CLASSES: Final[dict[int, str]] = {
    10: "tree_cover",
    20: "shrubland",
    30: "grassland",
    40: "cropland",
    50: "built_up",
    60: "bare_sparse_vegetation",
    70: "snow_and_ice",
    80: "permanent_water_bodies",
    90: "herbaceous_wetland",
    95: "mangroves",
    100: "moss_and_lichen",
}


def tile_name(latitude: float, longitude: float) -> str:
    """Return the WorldCover tile filename containing a coordinate."""
    lat_corner = (int(latitude) // TILE_DEGREES) * TILE_DEGREES
    lon_corner = (int(longitude) // TILE_DEGREES) * TILE_DEGREES
    hemisphere = "N" if lat_corner >= 0 else "S"
    meridian = "E" if lon_corner >= 0 else "W"
    return (
        f"ESA_WorldCover_10m_{VINTAGE}_{PRODUCT_VERSION}_"
        f"{hemisphere}{abs(lat_corner):02d}{meridian}{abs(lon_corner):03d}_Map.tif"
    )


def tile_url(latitude: float, longitude: float) -> str:
    """Return the download URL for the tile containing a coordinate."""
    return f"{S3_BASE}/{tile_name(latitude, longitude)}"


def sample_tile(tile_path: Path, points: list[tuple[float, float]]) -> list[int | None]:
    """Sample one tile at (longitude, latitude) points. Returns class codes.

    A point outside the tile, or landing on the raster nodata value, comes back as
    None rather than as a filled default, so an unsampled point stays
    distinguishable from a measured class.
    """
    with rasterio.open(tile_path) as raster:
        left, bottom, right, top = raster.bounds
        results: list[int | None] = []
        inside = [
            (index, point)
            for index, point in enumerate(points)
            if left <= point[0] <= right and bottom <= point[1] <= top
        ]
        results = [None] * len(points)
        if not inside:
            return results
        sampled = raster.sample([point for _, point in inside])
        for (index, _), value in zip(inside, sampled, strict=True):
            code = int(value[0])
            results[index] = code if code in CLASSES else None
        return results


BLOCK_PIXELS: Final[int] = 1024


def _configure_gdal_for_remote() -> None:
    """Settings that make range reads over the network viable rather than painful."""
    os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
    os.environ.setdefault("GDAL_CACHEMAX", "1024")
    os.environ.setdefault("VSI_CACHE", "TRUE")
    os.environ.setdefault("VSI_CACHE_SIZE", "200000000")


class TileNotAvailableError(RuntimeError):
    """Raised when a tile name resolves to no published tile.

    19 of the 121 candidate tiles over the India bounding box do not exist because
    they are entirely ocean. A point near a coast or on a small island can resolve
    to one of them. The caller records the affected points as unsampled rather than
    guessing a class for them.
    """


def sample_tile_remote(name: str, points: list[tuple[float, float]]) -> list[int | None]:
    """Sample one tile over the network, without downloading it.

    WorldCover tiles are cloud optimised GeoTIFFs with 1024 pixel blocks, so a
    windowed read fetches only the blocks it needs. Points are sorted into block
    order before sampling, which turns random access into near sequential access:
    measured on tile N30E072 with 12066 real detections, 279.5 seconds unordered
    against 44.8 seconds ordered, a factor of 6.2. Results are returned in the
    caller's original order. D20.
    """
    _configure_gdal_for_remote()
    url = f"/vsicurl/{S3_BASE}/{name}"
    results: list[int | None] = [None] * len(points)
    try:
        opened = rasterio.open(url)
    except rasterio.errors.RasterioIOError as exc:
        if "404" in str(exc):
            raise TileNotAvailableError(f"{name} is not published") from exc
        raise
    with opened as raster:
        left, bottom, right, top = raster.bounds
        inside = [
            (index, point)
            for index, point in enumerate(points)
            if left <= point[0] <= right and bottom <= point[1] <= top
        ]
        if not inside:
            return results
        located = [(raster.index(point[0], point[1]), index) for index, point in inside]
        located.sort(
            key=lambda item: (
                item[0][0] // BLOCK_PIXELS,
                item[0][1] // BLOCK_PIXELS,
                item[0],
            )
        )
        ordered_points = [points[index] for _, index in located]
        for (_, index), value in zip(located, raster.sample(ordered_points), strict=True):
            code = int(value[0])
            results[index] = code if code in CLASSES else None
    return results


def group_by_tile(
    points: list[tuple[float, float]],
) -> dict[str, list[int]]:
    """Group point indexes by the WorldCover tile that contains them."""
    grouped: dict[str, list[int]] = {}
    for index, (longitude, latitude) in enumerate(points):
        grouped.setdefault(tile_name(latitude, longitude), []).append(index)
    return grouped


def class_name(code: int | None) -> str | None:
    """Map a WorldCover class code to its name."""
    return None if code is None else CLASSES.get(code)
