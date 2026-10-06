# AgniNetra

A research platform for classifying thermal anomaly detections over India into
source types, and for identifying persistent thermal sources that appear in no
registry.

Built by Chinmaya Thakral.

## The problem

NASA FIRMS publishes thermal anomaly detections: a hot pixel with a location, a
time, brightness temperatures and a fire radiative power value. The feed cannot
say what is burning. A refinery flare, a sponge iron kiln, a cement precalciner,
crop residue burning and a forest fire all arrive looking the same. That is the
premise of this project: an alert stream crowded with routine industrial heat is hard
to act on.

## The approach

Each detection is labelled by rule from public maps, a flare catalogue,
industrial features, energy assets and land cover, with no hand labels, and the
classifiers are tested on whole groups of states they never saw. The project set
out to read the source from how a location burns over time. Measured on the polar
orbiting record, that signal is bounded by when the satellites look: they sample
six moments of the day, so time of day separates farm fires from continuous
sources but not flares from industry. A contextual fire detector for India's
geostationary INSAT-3DS satellite looks at the evening hours the polar record
misses.

## Deliverables

1. BharatThermal-1, a multi sensor benchmark for thermal source attribution over
   India with a spatially blocked evaluation protocol, held for publication and
   not yet distributed.
2. Baselines: gradient boosted trees and density clustering, measured; an imagery
   probe, run end to end and refused on support; and KAALCHAKRA, a latent class
   point process, specified but not built, because its central term cannot be
   tested on polar orbiting data.
3. A contextual fire detector for INSAT-3DS.
4. A web console that displays the precomputed results.

## Layout

    ml/         Python package: ingestion, features, labels, models, evaluation
    apps/console/  Next.js console
    scripts/    entry point scripts for backfills and exports
    tests/      pytest suite
    data/       local data store, never committed
    docs/       figures and write up, kept with the team, not in a clone

## Running it

Requires Python 3.11 and `uv`.

    uv sync --extra dev
    uv run pytest

`pyproject.toml` declares every direct dependency, pinned. `requirements.lock.txt`
freezes the full environment the published results were produced in, including the
heavy imagery extra used only by baseline B4. To match that environment exactly,
in a fresh clone:

    uv venv --python 3.11
    uv pip install -r requirements.lock.txt

The console needs Node 22:

    cd apps/console
    npm ci
    npm run build

The FIRMS map key is read from `.env`, which is never committed. Copy
`.env.example` to `.env` and fill it in. Without a key, ingestion is blocked and
reports itself as blocked rather than producing data.

## Status

Project state, decisions and phase specifications are kept with the team rather
than in this repository.

## What a clone does not contain

`docs/`, `context/` and `data/` stay on the team's machines. `data/` holds the
DuckDB store and downloaded products, several of which may not be redistributed;
`docs/` holds the report and the generated result documents. The tests that read
them skip on a clone, and each skip message names the folder it is waiting for.
Everything else runs from a clone.

## Attribution

This project builds on six external data sources. Four of them require attribution
as a licence condition rather than as a courtesy, so the notices below are
reproduced in the console footer and in the dataset card as well.

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

See `LICENSE`. Three things, licensed separately.

- **Code** is MIT. `ml/`, `scripts/`, `tests/`, `apps/console/`.
- **Written results** are CC BY 4.0.
- **The BharatThermal-1 dataset is ODbL 1.0**, in full and as one database.

The dataset takes ODbL because its feature set contains a column copied from an
OpenStreetMap attribute and a column computed against OpenStreetMap geometry, and
OpenStreetMap is ODbL. Releasing under the same licence as the source is correct
whether the dataset counts as a derivative database or a produced work, so no
argument is needed either way. Share alike propagates: if you publicly use an
adapted version of the database, release the adaptation under ODbL and attribute
the sources.

The dataset is held for a research publication in preparation and is not yet
distributed.
