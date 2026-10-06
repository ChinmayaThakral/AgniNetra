# ml

The Python side. Ingestion, reference layers, features, weak labels, models,
evaluation.

## Layout

    paths.py        the single path resolver, imported everywhere
    population.py   the analysis population, defined once
    tracked.py      the tracked file enumeration every guard uses
    documents.py    which documents a check may read
    ingest/         FIRMS client, parsing, deterministic ids, the DuckDB schema
    reference/      flare, asset, land use and land cover layers
    features/       thermal, spatial, recurrence and temporal feature builders
    labels/         weak label rules and the spatially blocked split protocol
    fusion/         INSAT-3DS reading, detection, geolocation and collocation
    imagery/        Sentinel-2 acquisition, chips and embeddings for baseline B4
    eval/           reserved, empty
    artifacts/      trained models and exports, never committed

The baselines are fitted by scripts rather than a package: `scripts/train_b1.py`,
`scripts/conformal_aoa_b2.py` and `scripts/train_b4.py`. KAALCHAKRA, the latent
class point process, was not built: its excitation term is not testable in a polar
orbiting record, so phase 6 closed as a specification.

## Rules that matter here

No absolute path in any source file. Everything resolves through `paths.py`.

Every random seed is fixed and recorded with the run. A result that cannot be
reproduced from its recorded seed and config is not a result.

Features computed at time t use only detections strictly before t. There is a
leakage test that asserts this on a constructed sequence, and it is not optional.

Every number reported comes from a command that was run. An unmeasured value is
the string `not measured`.
