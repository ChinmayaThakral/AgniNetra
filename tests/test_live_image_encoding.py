"""Exercise Pillow's real encoders without imagery downloads or persistent render caches."""

import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import pytest


def _run_encoding_check(tmp_path: Path, source: str, *arguments: str) -> None:
    # A fresh interpreter keeps earlier pyplot imports from selecting persistent caches.
    bootstrap = """\
import socket
import sys
import warnings

warnings.simplefilter("error", DeprecationWarning)
sys.path.insert(0, sys.argv[1])

def _deny_network(*args: object, **kwargs: object) -> None:
    raise AssertionError("Image encoding must not access the network")

socket.socket.connect = _deny_network
socket.socket.connect_ex = _deny_network
socket.getaddrinfo = _deny_network
"""
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            "-c",
            bootstrap + dedent(source),
            str(Path(__file__).resolve().parents[1]),
            *arguments,
        ],
        cwd=tmp_path,
        env={
            "HOME": str(tmp_path),
            "MPLBACKEND": "Agg",
            "MPLCONFIGDIR": str(tmp_path / "matplotlib"),
            "XDG_CACHE_HOME": str(tmp_path / "cache"),
            "XDG_CONFIG_HOME": str(tmp_path / "config"),
        },
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(("width", "height"), [(256, 256), (37, 23)])
def test_chip_webp_preserves_uint8_rgb_dimensions(tmp_path: Path, width: int, height: int) -> None:
    _run_encoding_check(
        tmp_path,
        """
        import io

        import numpy as np
        from PIL import Image

        from apps.live.pipeline.build_chips import stretch, webp

        width, height = map(int, sys.argv[2:])
        y, x = np.indices((height, width))
        pixels = np.stack((x * 7, y * 11, (x + y) * 5), axis=-1).astype(np.uint8)
        original = pixels.copy()
        stretched = stretch(pixels)
        assert stretched.dtype == np.uint8
        assert stretched.shape == (height, width, 3)

        encoded = webp(pixels)
        assert isinstance(encoded, bytes)
        assert encoded
        with Image.open(io.BytesIO(encoded)) as decoded:
            decoded.load()
            assert decoded.format == "WEBP"
            assert decoded.mode == "RGB"
            assert decoded.size == (width, height)
            assert all(low < high for low, high in decoded.getextrema())
        np.testing.assert_array_equal(pixels, original)
        """,
        str(width),
        str(height),
    )


@pytest.mark.parametrize(
    ("feeling", "label"),
    [
        ("watchful", "Netu is watching"),
        ("worried", "Bad air, stay in"),
        ("resting", "Quiet sky"),
    ],
)
def test_social_sticker_renders_transparent_rgba_webp(
    tmp_path: Path, feeling: str, label: str
) -> None:
    _run_encoding_check(
        tmp_path,
        """
        from pathlib import Path

        import matplotlib
        from PIL import Image

        from apps.live.pipeline.social_kit import sticker

        assert matplotlib.get_backend().lower() == "agg"
        assert Path(matplotlib.get_configdir()).is_relative_to(Path.cwd())
        assert Path(matplotlib.get_cachedir()).is_relative_to(Path.cwd())
        path = Path.cwd() / "sticker.webp"
        sticker(sys.argv[2], sys.argv[3], path)

        with Image.open(path) as decoded:
            decoded.load()
            assert decoded.format == "WEBP"
            assert decoded.mode == "RGBA"
            assert decoded.size == (512, 512)
            alpha = decoded.getchannel("A")
            assert alpha.getextrema() == (0, 255)
            assert alpha.getpixel((0, 0)) == 0
            assert alpha.getpixel((256, 212)) == 255
        assert not path.with_suffix(".png").exists()
        assert list(Path.cwd().glob("*.webp")) == [path]
        """,
        feeling,
        label,
    )
