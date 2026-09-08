"""The contextual detector must not flag cold cloud as fire.

The first version had no absolute floor and returned 150 detections whose brightest
members sat at 248 to 256 K, which is minus 25 to minus 17 Celsius. A cold cloud can
show a large mid wave minus thermal difference through solar reflection, so a purely
relative test cannot separate it from combustion. D79.
"""

from dataclasses import dataclass

import numpy as np
import pytest

from ml.fusion.detect import MIR_FLOOR_K, detect


@dataclass
class SyntheticWindow:
    mir: np.ndarray
    tir1: np.ndarray
    longitude: np.ndarray
    latitude: np.ndarray


def _scene(size: int = 40) -> SyntheticWindow:
    """A uniform warm surface with no fire in it."""
    mir = np.full((size, size), 300.0, dtype=np.float32)
    tir1 = np.full((size, size), 295.0, dtype=np.float32)
    lon, lat = np.meshgrid(
        np.linspace(70.0, 90.0, size), np.linspace(10.0, 30.0, size)
    )
    return SyntheticWindow(mir, tir1, lon.astype(np.float32), lat.astype(np.float32))


def test_a_uniform_scene_has_no_detections() -> None:
    assert len(detect(_scene())) == 0


def test_a_hot_pixel_with_the_signature_is_found() -> None:
    scene = _scene()
    scene.mir[20, 20] = 330.0
    scene.tir1[20, 20] = 300.0
    found = detect(scene)
    assert len(found) == 1
    assert found.row[0] == 20 and found.col[0] == 20


def _cloud_field(size: int = 40) -> SyntheticWindow:
    """A cold cloud deck with one pixel warmer than its neighbours.

    This is the shape of the real failure. The flagged pixels were not warm against
    the whole scene, they were warm against the cloud around them, and they were
    still at minus 20 Celsius. A relative test alone cannot see that.
    """
    scene = _scene(size)
    scene.mir[:] = 245.0
    scene.tir1[:] = 240.0
    scene.mir[10, 10] = 252.0
    scene.tir1[10, 10] = 208.0
    return scene


def test_cold_cloud_is_not_a_fire() -> None:
    """The defect this file exists for. Warm against cloud, cold absolutely."""
    found = detect(_cloud_field())
    assert len(found) == 0, "a 252 K pixel was flagged, the absolute floor is not applied"


def test_warm_without_the_signature_is_not_a_fire() -> None:
    """Sunlit ground raises both channels together, so the difference stays flat."""
    scene = _scene()
    scene.mir[15, 15] = 320.0
    scene.tir1[15, 15] = 315.0
    assert len(detect(scene)) == 0


def test_the_floor_is_load_bearing() -> None:
    """Without the floor the cloud pixel is flagged, with it the pixel is not.

    The contextual tests pass in both cases, which is the point: the floor is doing
    the work and removing it reintroduces the defect.
    """
    scene = _cloud_field()
    assert len(detect(scene, mir_floor=0.0)) == 1
    assert len(detect(scene, mir_floor=MIR_FLOOR_K)) == 0


def test_unobserved_pixels_are_never_flagged() -> None:
    scene = _scene()
    scene.mir[5, 5] = np.nan
    scene.tir1[5, 5] = np.nan
    found = detect(scene)
    assert len(found) == 0
    assert found.valid_pixels == scene.mir.size - 1


def test_raising_the_floor_never_adds_detections() -> None:
    scene = _scene()
    for row, col in ((8, 8), (12, 12), (30, 30)):
        scene.mir[row, col] = 315.0
        scene.tir1[row, col] = 295.0
    counts = [len(detect(scene, mir_floor=f)) for f in (295.0, 300.0, 305.0, 310.0, 320.0)]
    assert counts == sorted(counts, reverse=True), counts


@pytest.mark.parametrize("radius", [3, 5, 7])
def test_the_background_radius_does_not_change_a_clear_case(radius: int) -> None:
    scene = _scene()
    scene.mir[20, 20] = 340.0
    scene.tir1[20, 20] = 300.0
    assert len(detect(scene, radius=radius)) == 1
