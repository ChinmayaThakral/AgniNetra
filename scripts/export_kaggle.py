#!/usr/bin/env python3
"""Export BharatThermal-1 as an open dataset, ready to upload to Kaggle.

Usage:
    uv run python scripts/export_kaggle.py

Writes to `data/kaggle/bharatthermal-1/`: the detections as Parquet and as gzipped CSV,
the persistent sources, a column dictionary, a README and Kaggle's
`dataset-metadata.json`. Uploading is the owner's, from their own Kaggle account.

The release is under ODbL 1.0. Some columns are derived from OpenStreetMap geometry, and
whether that makes the table a Derivative Database, which carries share alike, was the
question the dataset card left open; releasing under ODbL 1.0 satisfies either answer.
The other sources, NASA FIRMS, Global Energy Monitor and ESA WorldCover, permit
redistribution with attribution, which the README carries.

Distance to a catalogued gas flare is published as a band, never in metres, for the
reason D69 gives: exact distances from many known points are trilaterable, and the EOG
catalogue is not confirmed redistributable.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import duckdb

from ml.labels.splits import HELD_OUT_GROUPS
from ml.labels.weak import weak_label_sql
from ml.paths import DATA_DIR, ROOT

DB = DATA_DIR / "agninetra.duckdb"
OUT = DATA_DIR / "kaggle" / "bharatthermal-1"
SOURCES = ROOT / "apps" / "console" / "public" / "data" / "sources.json"
KAGGLE_ID = "chinmayathakral/bharatthermal-1"
WINDOWS = (
    ("season_2023", "2023-10-01", "2023-11-30"),
    ("season_2024", "2024-10-01", "2024-11-30"),
    ("monsoon_2026", "2026-06-06", "2026-09-03"),
)
# Distances were searched within a 0.06 degree box, about 6.6 km, so an empty distance
# means nothing catalogued that close, not a missing value.
FLARE_BANDS = ((1000, "under 1 km"), (5000, "1 to 5 km"))
NONE_NEAR = "none within 6.6 km"

COLUMNS = {
    "detection_id": "Stable identifier of the FIRMS detection, a hash of its source fields.",
    "source": "FIRMS product the row came from, for example VIIRS_SNPP_SP.",
    "instrument": "MODIS or VIIRS.",
    "satellite": "Terra, Aqua, Suomi NPP, NOAA-20 or NOAA-21.",
    "latitude": "Pixel centre latitude, degrees, WGS84, as published by FIRMS.",
    "longitude": "Pixel centre longitude, degrees, WGS84, as published by FIRMS.",
    "acq_ts_utc": "Acquisition time, UTC.",
    "acq_ts_ist": "Acquisition time, Indian Standard Time.",
    "acq_hour_ist": "Hour of acquisition, IST, 0 to 23.",
    "daynight": "D or N, as published by FIRMS.",
    "confidence_band": "FIRMS confidence normalised to low, nominal or high.",
    "frp": "Fire radiative power, megawatts.",
    "scan": "Pixel size along scan, kilometres.",
    "track": "Pixel size along track, kilometres.",
    "brightness": "Primary brightness temperature, kelvin (MODIS band 21 or VIIRS I4).",
    "bright_secondary": "Secondary brightness temperature, kelvin (MODIS band 31 or VIIRS I5).",
    "window": "season_2023, season_2024 or monsoon_2026.",
    "state": "Indian state the detection falls in; empty outside India.",
    "split_group": "Spatially blocked evaluation group: group_a, group_b, group_c, or train.",
    "weak_label": "flare, industrial, agricultural or unlabelled, from the rule in the README.",
    "nearest_osm_industrial_m": (
        "Metres to the nearest OpenStreetMap industrial feature; empty if none within 6.6 km."
    ),
    "nearest_gem_asset_m": (
        "Metres to the nearest GEM asset operating that year; empty if none within 6.6 km."
    ),
    "nearest_flare_band": (
        "Distance band to the nearest catalogued gas flare: "
        "under 1 km, 1 to 5 km, 5 km or more, or none within 6.6 km."
    ),
    "landcover_class": "ESA WorldCover 2021 class at the pixel centre.",
    "prior_count_30d": "Detections at the same location in the prior 30 days, or empty.",
    "prior_count_90d": "Detections at the same location in the prior 90 days, or empty.",
    "night_fraction_90d": "Share of those 90 day detections at night, 0 to 1.",
    "frp_variance_90d": "Variance of FRP over those 90 days, megawatts squared.",
    "mean_gap_days": "Mean gap between those detections, days.",
}


def band_sql(column: str) -> str:
    cases = " ".join(f"WHEN {column} < {edge} THEN '{name}'" for edge, name in FLARE_BANDS)
    return f"CASE WHEN {column} IS NULL THEN '{NONE_NEAR}' {cases} ELSE '5 km or more' END"


def window_sql(column: str) -> str:
    cases = " ".join(
        f"WHEN {column} BETWEEN DATE '{start}' AND DATE '{end}' THEN '{name}'"
        for name, start, end in WINDOWS
    )
    return f"CASE {cases} END"


def group_sql(column: str) -> str:
    cases = " ".join(
        f"WHEN {column} IN ({', '.join(repr(s) for s in states)}) THEN '{group}'"
        for group, states in HELD_OUT_GROUPS.items()
    )
    return f"CASE {cases} WHEN {column} IS NULL THEN NULL ELSE 'train' END"


QUERY = f"""
SELECT
    d.detection_id, d.source, d.instrument, d.satellite, d.latitude, d.longitude,
    d.acq_ts_utc, d.acq_ts_ist, d.acq_hour_ist, d.daynight, d.confidence_band, d.frp,
    d.scan, d.track,
    CASE d.instrument WHEN 'VIIRS' THEN d.bright_ti4 ELSE d.brightness END AS brightness,
    CASE d.instrument WHEN 'VIIRS' THEN d.bright_ti5 ELSE d.bright_t31 END AS bright_secondary,
    {window_sql("d.acq_date_ist")} AS window,
    c.state_name AS state,
    {group_sql("c.state_name")} AS split_group,
    CASE WHEN c.state_name IS NULL THEN NULL ELSE {weak_label_sql("c", "g")} END AS weak_label,
    round(c.industrial_m) AS nearest_osm_industrial_m,
    round(g.gem_m_temporal) AS nearest_gem_asset_m,
    {band_sql("c.flare_m")} AS nearest_flare_band,
    c.landcover_class,
    r.prior_count_30d, r.prior_count_90d, r.night_fraction_90d, r.frp_variance_90d,
    r.mean_gap_days
FROM detection_context c
JOIN detections d USING (detection_id)
LEFT JOIN detection_gem g USING (detection_id)
LEFT JOIN detection_recurrence r USING (detection_id)
ORDER BY d.acq_ts_utc, d.detection_id
"""


def readme(counts: dict[str, int], total: int, labelled: int) -> str:
    rows = "\n".join(f"| `{name}` | {text} |" for name, text in COLUMNS.items())
    labels = "\n".join(f"| {name} | {n} |" for name, n in sorted(counts.items()))
    return f"""# BharatThermal-1: thermal anomalies over India, labelled by source type

{total} NASA FIRMS detections over India and its borders across three windows: the
October to November burning seasons of 2023 and 2024, and the 2026 monsoon. {labelled}
fall inside an Indian state and carry a weak label saying what is likely burning: a gas
flare, industrial heat, or agricultural burning.

From AgniNetra, by Chinmaya Thakral: {ROOT_URL}

## The weak label

No row is hand labelled. A rule joins each detection to reference maps, in order:

1. within 500 m of a catalogued gas flare (EOG VIIRS Nightfire): **flare**; the distance
   itself is published only as the band `under 1 km`;
2. else within 1 km of an OpenStreetMap industrial feature, or of a Global Energy Monitor
   asset operating in that year: **industrial**;
3. else on ESA WorldCover cropland: **agricultural**;
4. else **unlabelled**. Rows outside India carry no label.

| Label | Rows |
|---|---|
{labels}

**These are weak labels, not ground truth.** The reference maps are incomplete, and not at
random: industrial features per thousand square kilometres range from 52.2 in Kerala to
0.85 in Mizoram. Nothing was verified in the field.

## Evaluate it the honest way

Detections cluster, so a random split puts the same factory in train and test. Hold out
whole states with `split_group`: train on `train`, test on each of `group_a`, `group_b`
and `group_c`. On these rows a random split overstates macro F1 by 0.115 against the
blocked protocol.

## Columns

| Column | Meaning |
|---|---|
{rows}

## Files

- `detections.parquet`, `detections.csv.gz`: one row per detection.
- `persistent_sources.csv`: 263 locations that burn again and again, from the full record.
- `columns.csv`: the table above.

## Licence and credits

Released under the Open Database License 1.0. Contains information from:

- NASA FIRMS, MODIS and VIIRS active fire data. We acknowledge the use of data from NASA
  LANCE FIRMS, part of NASA's Earth Science Data and Information System.
- OpenStreetMap, copyright OpenStreetMap contributors, ODbL 1.0, snapshot 2026-09-02.
- Global Energy Monitor trackers, CC BY 4.0.
- ESA WorldCover 10 m 2021 v200, CC BY 4.0.
- Distance bands to the EOG VIIRS global gas flaring catalogue, Colorado School of Mines.

Not for enforcement or compliance decisions about any named facility.
"""


ROOT_URL = "https://github.com/ChinmayaThakral/AgniNetra"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB), read_only=True)
    con.execute(f"CREATE TEMP VIEW release AS {QUERY}")
    parquet = OUT / "detections.parquet"
    con.execute(f"COPY release TO '{parquet}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    con.execute(f"COPY release TO '{OUT / 'detections.csv.gz'}' (HEADER, COMPRESSION GZIP)")
    total = con.execute("SELECT count(*) FROM release").fetchone()[0]
    counts = dict(
        con.execute(
            "SELECT weak_label, count(*) FROM release WHERE weak_label IS NOT NULL GROUP BY 1"
        ).fetchall()
    )
    labelled = sum(counts.values())

    sources = json.loads(SOURCES.read_text())
    keys = list(sources[0].keys())
    with (OUT / "persistent_sources.csv").open("w") as f:
        f.write(",".join(keys) + "\n")
        for s in sources:
            cells = ("" if s[k] is None else str(s[k]).replace(",", ";") for k in keys)
            f.write(",".join(cells) + "\n")
    with (OUT / "columns.csv").open("w") as f:
        f.write("column,meaning\n")
        for name, text in COLUMNS.items():
            f.write(f'{name},"{text}"\n')

    text = readme(counts, total, labelled)
    (OUT / "README.md").write_text(text)
    metadata = {
        "title": "BharatThermal-1: India thermal anomalies by source",
        "subtitle": "601k NASA FIRMS hot spots weakly labelled flare, industrial, agricultural",
        "id": KAGGLE_ID,
        "licenses": [{"name": "ODbL-1.0"}],
        "keywords": ["earth and nature", "environment", "india", "geospatial analysis"],
        "description": text,
    }
    (OUT / "dataset-metadata.json").write_text(json.dumps(metadata, indent=1) + "\n")
    print(f"{total} rows, {labelled} labelled {counts}, written to {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
