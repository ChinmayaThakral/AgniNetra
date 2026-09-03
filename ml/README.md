# ml

The Python side. Ingestion, reference layers, features, weak labels, models,
evaluation.

## Layout

    paths.py        the single path resolver, imported everywhere
    ingest/         FIRMS client, parsing, deterministic ids, the DuckDB schema
    reference/      flare, asset, land use and land cover layers
    features/       thermal, spatial, recurrence and temporal feature builders
    labels/         weak label rules and the spatially blocked split protocol
    models/         baselines B1, B2 and B4
    stpp/           KAALCHAKRA, the latent class point process
    eval/           metrics, calibration, conformal sets, applicability domain
    fusion/         INSAT-3DS collocation, from phase 5
    artifacts/      trained models and exports, never committed

Directories appear as their phase creates them. A directory listed here that does
not exist yet has not been built yet, and that is expected.

## Rules that matter here

No absolute path in any source file. Everything resolves through `paths.py`.

Every random seed is fixed and recorded with the run. A result that cannot be
reproduced from its recorded seed and config is not a result.

Features computed at time t use only detections strictly before t. There is a
leakage test that asserts this on a constructed sequence, and it is not optional.

Every number reported comes from a command that was run. An unmeasured value is
the string `not measured`.
