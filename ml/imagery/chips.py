"""Chip extraction at detection locations from a Sentinel-2 L2A product.

A chip describes the site, not the moment. The scene is one date and the
detections span the whole record, so the embedding is a static site context
feature and must not be read as observing the detection itself. D57.
"""

from pathlib import Path
from typing import Final

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import transform as warp_transform
from rasterio.windows import Window

# TerraMind v1 takes the 12 band Sentinel-2 L2A stack in this order. B10 is absent
# from L2A products because it is the cirrus band and is consumed by the
# atmospheric correction rather than delivered.
S2L2A_BANDS: Final[tuple[str, ...]] = (
    "B01",
    "B02",
    "B03",
    "B04",
    "B05",
    "B06",
    "B07",
    "B08",
    "B8A",
    "B09",
    "B11",
    "B12",
)
CHIP_PX: Final[int] = 224


class ChipError(RuntimeError):
    """Raised when a chip cannot be cut whole from the scene."""


def pixel_of(dataset, *, longitude: float, latitude: float) -> tuple[int, int]:
    """Return the (row, col) of a geographic point in the dataset's own grid.

    The point is reprojected into the dataset CRS first. Sentinel-2 is delivered
    in UTM, so passing longitude and latitude to an affine inverse directly would
    silently produce a pixel index near the origin instead of failing.
    """
    xs, ys = warp_transform("EPSG:4326", dataset.crs, [longitude], [latitude])
    row, col = dataset.index(xs[0], ys[0])
    return int(row), int(col)


def chip_window(row: int, col: int, size_px: int, height: int, width: int) -> Window:
    """Return a centred window, raising if it does not fit inside the raster.

    Clipping a chip at the scene edge and padding it would produce an embedding
    of mostly zeros that scores as a real site, so an edge detection is refused
    rather than trimmed.
    """
    half = size_px // 2
    row_off, col_off = row - half, col - half
    if row_off < 0 or col_off < 0 or row_off + size_px > height or col_off + size_px > width:
        raise ChipError(
            f"a {size_px} pixel chip centred at row {row} col {col} does not fit inside "
            f"a {height} by {width} raster. The detection is too close to the scene edge."
        )
    return Window(col_off, row_off, size_px, size_px)


def read_chip(band_paths: dict[str, Path], *, longitude: float, latitude: float) -> np.ndarray:
    """Return one (12, 224, 224) float32 chip, bands in S2L2A_BANDS order.

    Every band is resampled to the 10 m grid by reading a window scaled to that
    band's own resolution, so a 20 m band contributes a 112 pixel window read out
    at 224. Raises ChipError if any band is missing or does not fit.
    """
    missing = [b for b in S2L2A_BANDS if b not in band_paths]
    if missing:
        raise ChipError(f"product is missing bands {missing}")

    stack = np.empty((len(S2L2A_BANDS), CHIP_PX, CHIP_PX), dtype=np.float32)
    for index, band in enumerate(S2L2A_BANDS):
        with rasterio.open(band_paths[band]) as dataset:
            row, col = pixel_of(dataset, longitude=longitude, latitude=latitude)
            metres = dataset.res[0]
            size_px = max(1, round(CHIP_PX * 10.0 / metres))
            window = chip_window(row, col, size_px, dataset.height, dataset.width)
            stack[index] = dataset.read(
                1,
                window=window,
                out_shape=(CHIP_PX, CHIP_PX),
                resampling=Resampling.bilinear,
            ).astype(np.float32)
    return stack


def band_paths_in_safe(safe_root: Path) -> dict[str, Path]:
    """Map band name to file for one unpacked SAFE product.

    Prefers the highest native resolution available for each band, because reading
    a 10 m band from the R20m directory would discard resolution the product has.
    """
    found: dict[str, Path] = {}
    for resolution in ("R10m", "R20m", "R60m"):
        for path in sorted(safe_root.glob(f"GRANULE/*/IMG_DATA/{resolution}/*.jp2")):
            for band in S2L2A_BANDS:
                if f"_{band}_" in path.name and band not in found:
                    found[band] = path
    return found
