"""The app's fallback city positions match the pipeline's forecast cities exactly."""

import re

from apps.live.pipeline.feed import AIR_CITIES
from ml.paths import ROOT

PLACE = ROOT / "apps" / "live" / "web" / "src" / "place.ts"


def test_app_city_positions_match_the_pipeline() -> None:
    text = PLACE.read_text()
    start = text.index("export const CITY_POSITIONS")
    block = text[start : text.index("};", start)]
    found = {
        name.strip('"'): (float(lon), float(lat))
        for name, lon, lat in re.findall(
            r'^\s+("?[A-Za-z ]+"?): \[([\d.]+), ([\d.]+)\]', block, re.M
        )
    }
    assert found == {name: (lon, lat) for name, lon, lat in AIR_CITIES}
