"""The official INSAT-3DS fire product is read by coordinates and file name only.

Its KML carries corrupted address and time fields, so a parser that trusted either
would misplace detections. The file name slot is UTC, which chapter 6.7 checked
against local solar time; a parser reading it as IST would move every hour.
"""

import importlib.util
import sys
from datetime import UTC, datetime

from ml.paths import ROOT

_spec = importlib.util.spec_from_file_location(
    "official_fir_compare", ROOT / "scripts" / "official_fir_compare.py"
)
assert _spec is not None and _spec.loader is not None
fir = importlib.util.module_from_spec(_spec)
sys.modules["official_fir_compare"] = fir
_spec.loader.exec_module(fir)

CORRUPTED = """<kml><Folder>
<Placemark><address>291.636, 291.636298.754</address>
<TimeStamp><when>:03:59 UTC</when></TimeStamp>
<Point><coordinates>
  75.5,30.25,0
</coordinates></Point></Placemark>
<Placemark><address>291.636298.754302.771, 291.636298.754302.771313.658</address>
<TimeStamp><when>01-NOV-2024 UTC</when></TimeStamp>
<Point><coordinates>
  23.98,14.22,0
</coordinates></Point></Placemark>
</Folder></kml>"""


def test_the_slot_in_the_file_name_is_utc() -> None:
    when = fir.slot_of("3SIMG_01NOV2024_1100_L2P_FIR_V01R00.kml")
    assert when == datetime(2024, 11, 1, 11, 0, tzinfo=UTC)
    assert (when + fir.IST).hour == 16


def test_coordinates_are_read_and_corrupted_fields_ignored() -> None:
    longitudes, latitudes = fir.parse_kml(CORRUPTED)
    assert list(longitudes) == [75.5, 23.98]
    assert list(latitudes) == [30.25, 14.22]


def test_the_box_keeps_punjab_and_drops_africa() -> None:
    longitudes, latitudes = fir.parse_kml(CORRUPTED)
    assert list(fir.inside(longitudes=longitudes, latitudes=latitudes, box=fir.BOX)) == [
        True,
        False,
    ]
