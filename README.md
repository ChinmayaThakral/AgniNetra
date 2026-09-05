# AgniNetra

A research platform for classifying thermal anomaly detections over India into
source types, and for identifying persistent thermal sources that appear in no
registry.

Built by Chinmaya Thakral.

## The problem

NASA FIRMS publishes thermal anomaly detections: a hot pixel with a location, a
time, brightness temperatures and a fire radiative power value. The feed cannot
say what is burning. A refinery flare, a sponge iron kiln, a cement precalciner,
crop residue burning and a forest fire all arrive looking the same. A fire
response consumer therefore receives an alert stream dominated by routine
industrial heat, and stops reading it.

## The approach

The discriminating signal is not in the pixel. It is in the recurrence process at
a location. A flare burns nightly for months with low radiative power variance.
Crop residue burning has a sharp seasonal envelope and a strong diurnal
concentration. A wildfire is bursty, self exciting, spatially expanding, and does
not return to the same pixel next year. Industrial batch processes are periodic
with campaign structure. Those are four different point process signatures, and
modelling them directly is the research contribution.

## Deliverables

1. BharatThermal-1, an open multi sensor benchmark for thermal source attribution
   over India with a spatially blocked evaluation protocol.
2. KAALCHAKRA, a latent class marked spatio temporal point process, benchmarked
   against four baselines.
3. A web console that demonstrates the result.

## Layout

    ml/         Python package: ingestion, features, labels, models, evaluation
    apps/console/  Next.js console
    scripts/    entry point scripts for backfills and exports
    tests/      pytest suite
    data/       local data store, never committed
    docs/       figures and write up

## Running it

Requires Python 3.11 and `uv`.

    uv venv --python 3.11
    uv pip install -r requirements.txt
    uv run pytest

The FIRMS map key is read from `.env`, which is never committed. Copy
`.env.example` to `.env` and fill it in. Without a key, ingestion is blocked and
reports itself as blocked rather than producing data.

## Status

Project state, decisions and phase specifications are kept with the team rather
than in this repository.

## Attribution

This project builds on six external data sources. Four of them require attribution
as a licence condition rather than as a courtesy, so the notices below are
reproduced in `docs/dataset_card.md` and in the console footer as well.

- **NASA FIRMS.** MODIS and VIIRS active fire data from NASA FIRMS, part of NASA's
  Earth Science Data and Information System. <https://firms.modaps.eosdis.nasa.gov/>
- **OpenStreetMap.** Industrial features and administrative boundaries, copyright
  OpenStreetMap contributors, licensed ODbL 1.0.
  <https://www.openstreetmap.org/copyright>
- **Global Energy Monitor.** Power, coal mine, iron and steel and cement trackers,
  licensed CC BY 4.0. <https://globalenergymonitor.org/>
- **ESA WorldCover.** ESA WorldCover 10 m 2021 v200, licensed CC BY 4.0.
  <https://esa-worldcover.org/>
- **Copernicus Sentinel-2.** Contains modified Copernicus Sentinel data 2024,
  processed by the AgniNetra team. <https://dataspace.copernicus.eu/>
- **EOG, Colorado School of Mines.** VIIRS global gas flaring catalogue. Attribution
  required, redistribution not confirmed, so values derived from it are published
  only as coarse bands. See D69. <https://eogdata.mines.edu/>

## Licence

See `LICENSE`. In short: the code is MIT, the written results are CC BY 4.0, and
**the BharatThermal-1 dataset is not released yet.**

The dataset is withheld because the feature set contains columns derived from
OpenStreetMap geometry, and whether that makes it a Derivative Database under ODbL
section 4.4, which carries share alike, or a Produced Work under section 4.5, which
does not, has not been decided. The licensing audit sets out both readings with the licence text quoted and is
held with the team. That decision is outstanding and it is the
only thing standing between this repository and a dataset release.
