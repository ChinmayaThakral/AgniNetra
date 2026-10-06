"""The released dataset never carries a flare distance in metres, and every row lands in
exactly one of its windows and split groups."""

import importlib.util
import sys
from datetime import date

import duckdb

from ml.paths import ROOT

_spec = importlib.util.spec_from_file_location(
    "export_kaggle", ROOT / "scripts" / "export_kaggle.py"
)
assert _spec is not None and _spec.loader is not None
kaggle = importlib.util.module_from_spec(_spec)
sys.modules["export_kaggle"] = kaggle
_spec.loader.exec_module(kaggle)


def evaluate(expression: str, column: str, value: object) -> object:
    con = duckdb.connect()
    return con.execute(f"SELECT {expression} FROM (SELECT ? AS {column})", [value]).fetchone()[0]


def test_flare_distance_is_only_ever_a_band() -> None:
    band = kaggle.band_sql("m")
    assert evaluate(band, "m", 400.0) == "under 1 km"
    assert evaluate(band, "m", 3000.0) == "1 to 5 km"
    assert evaluate(band, "m", 6000.0) == "5 km or more"
    assert evaluate(band, "m", None) == kaggle.NONE_NEAR


def test_dates_fall_in_their_window_and_states_in_their_group() -> None:
    window = kaggle.window_sql("d")
    assert evaluate(window, "d", date(2024, 11, 1)) == "season_2024"
    assert evaluate(window, "d", date(2026, 7, 1)) == "monsoon_2026"
    group = kaggle.group_sql("s")
    assert evaluate(group, "s", "Punjab") == "group_a"
    assert evaluate(group, "s", "Bihar") == "train"
    assert evaluate(group, "s", None) is None
