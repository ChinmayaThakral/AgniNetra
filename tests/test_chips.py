"""Tests for chip extraction geometry.

Sentinel-2 is delivered in UTM. The failure this file exists to catch is a
longitude and latitude passed to an affine inverse without reprojection, which
returns a pixel index near the raster origin rather than raising.
"""

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from rasterio.windows import Window

from ml.imagery.chips import ChipError, chip_window, pixel_of

SYNTHETIC_LON = 82.6757
SYNTHETIC_LAT = 24.1030


def _synthetic_utm_raster(path):
    """A 1000 by 1000 raster at 10 m in UTM 44N, centred on the probe point."""
    from rasterio.warp import transform as warp_transform

    xs, ys = warp_transform("EPSG:4326", "EPSG:32644", [SYNTHETIC_LON], [SYNTHETIC_LAT])
    west, north = xs[0] - 5000, ys[0] + 5000
    profile = {
        "driver": "GTiff",
        "height": 1000,
        "width": 1000,
        "count": 1,
        "dtype": "uint16",
        "crs": "EPSG:32644",
        "transform": from_origin(west, north, 10.0, 10.0),
    }
    with rasterio.open(path, "w", **profile) as dataset:
        dataset.write(np.zeros((1000, 1000), dtype="uint16"), 1)
    return path


def test_probe_point_lands_at_the_raster_centre(tmp_path):
    path = _synthetic_utm_raster(tmp_path / "synthetic.tif")
    with rasterio.open(path) as dataset:
        row, col = pixel_of(dataset, SYNTHETIC_LON, SYNTHETIC_LAT)
    assert row == pytest.approx(500, abs=1)
    assert col == pytest.approx(500, abs=1)


def test_unreprojected_lookup_would_have_missed(tmp_path):
    """Guards the trap rather than trusting that nobody reintroduces it."""
    path = _synthetic_utm_raster(tmp_path / "synthetic.tif")
    with rasterio.open(path) as dataset:
        naive_row, naive_col = dataset.index(SYNTHETIC_LON, SYNTHETIC_LAT)
        correct_row, correct_col = pixel_of(dataset, SYNTHETIC_LON, SYNTHETIC_LAT)
    assert (naive_row, naive_col) != (correct_row, correct_col)


def test_window_is_centred():
    window = chip_window(500, 500, 224, 1000, 1000)
    assert window == Window(388, 388, 224, 224)


def test_edge_detection_is_refused_not_padded():
    with pytest.raises(ChipError, match="too close to the scene edge"):
        chip_window(10, 500, 224, 1000, 1000)


def test_window_fitting_exactly_is_allowed():
    assert chip_window(112, 112, 224, 224, 224) == Window(0, 0, 224, 224)
