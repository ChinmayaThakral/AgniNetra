"""A coordinate can only be passed by name.

The codebase took coordinates in both orders: `tile_name` and `in_india_bbox`
latitude first, everything else longitude first. A test for the axis order trap
already existed, and a new script still passed (latitude, longitude) to the land
cover sampler, because a test only covers the callers it knows about. Three None
results were then recorded as a broken dependency. D116.

So the fix is in the signatures rather than in more tests of callers. Every
coordinate parameter is keyword only, which makes a reversed call an error in every
caller, including callers not yet written. This file enforces that by name across
`ml/` and `scripts/`, and checks the one place a reversed call could still hide: a
tile handed coordinates that all fall outside it now refuses instead of returning
None. D121.
"""

import ast
import re

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from ml.fusion.geolocate import forward, inverse
from ml.paths import ROOT
from ml.reference import landcover
from ml.tracked import tracked_files

# Matched by pattern rather than by a list of spellings. The first version listed eight
# names and missed `_haversine_m(lat1, lon1, lat2, lon2)` in scripts/collocate_insat.py,
# which takes latitude first. A guard that knows only the spellings it was shown is the
# instance scoped guard this project names as its second failure class. D121.
COORDINATE_NAME = re.compile(r"^(lon|lat|longitude|latitude)(s|gitudes|itudes)?_?\d*$")
# Projection coordinates are the same shape of trap: two floats whose order matters.
PROJECTION_FUNCTIONS = {("ml/fusion/geolocate.py", "inverse"): {"x", "y"}}


def _positional_offenders() -> list[str]:
    offenders = []
    for path in tracked_files((".py",)):
        relative = path.relative_to(ROOT).as_posix()
        if not relative.startswith(("ml/", "scripts/")):
            continue
        tree = ast.parse(path.read_text(), filename=relative)
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            projection = PROJECTION_FUNCTIONS.get((relative, node.name), set())
            for arg in [*node.args.posonlyargs, *node.args.args]:
                if COORDINATE_NAME.match(arg.arg) or arg.arg in projection:
                    offenders.append(f"{relative}:{node.lineno} {node.name}({arg.arg})")
    return offenders


def test_no_coordinate_is_positional() -> None:
    offenders = _positional_offenders()
    assert not offenders, (
        "coordinates must be keyword only, so a swapped call is an error rather than a "
        f"silently wrong answer: {offenders}"
    )


def test_a_positional_call_is_refused() -> None:
    with pytest.raises(TypeError):
        forward(77.0, 20.0)  # type: ignore[misc]
    x, y = forward(longitude=77.0, latitude=20.0)
    back_lon, back_lat = inverse(x=x, y=y)
    assert float(back_lon) == pytest.approx(77.0, abs=1e-9)
    assert float(back_lat) == pytest.approx(20.0, abs=1e-9)


def _tile(path) -> None:
    """A three degree tile over northern India, every pixel cropland."""
    data = np.full((30, 30), 40, dtype=np.uint8)
    profile = {
        "driver": "GTiff",
        "height": 30,
        "width": 30,
        "count": 1,
        "dtype": "uint8",
        "crs": "EPSG:4326",
        "transform": from_origin(75.0, 33.0, 0.1, 0.1),
    }
    with rasterio.open(path, "w", **profile) as dataset:
        dataset.write(data, 1)


def test_a_reversed_call_to_a_tile_is_refused(tmp_path) -> None:
    tile = tmp_path / "tile.tif"
    _tile(tile)
    lons, lats = [75.5, 76.5], [30.5, 31.5]
    assert landcover.sample_tile(tile, longitudes=lons, latitudes=lats) == [40, 40]
    with pytest.raises(landcover.AxisOrderError):
        landcover.sample_tile(tile, longitudes=lats, latitudes=lons)


def test_a_point_merely_outside_is_still_none(tmp_path) -> None:
    """The refusal is for all points outside, not any point outside."""
    tile = tmp_path / "tile.tif"
    _tile(tile)
    codes = landcover.sample_tile(tile, longitudes=[75.5, 90.0], latitudes=[30.5, 30.5])
    assert codes == [40, None]
