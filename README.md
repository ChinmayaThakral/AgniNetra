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

    context/    project brief, roadmap, per phase specs, live state, decisions
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

See `context/STATE.md`. It is the single source of truth for where the work
stands.

## Licence

Not yet chosen. The intended release for BharatThermal-1 is CC BY 4.0.
