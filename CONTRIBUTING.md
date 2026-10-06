# Contributing to AgniNetra

AgniNetra attributes satellite thermal detections over India to a likely source: crop
residue burning, industry or gas flares. Contributions of code, data checks, labels and
documentation are all welcome.

## Ways to help

- **Label hot spots.** Qualify in Heatle on [AgniNetra Live](https://agninetra.chinmayathakral.com),
  then label the persistent hot spots no map explains in Swipe.
- **Check a site.** Many issues ask whether a recurring hot spot is a plant, a mine or a
  kiln. Imagery and local knowledge both help.
- **Fix or build.** Issues labelled `good first issue` are a good start.
- **Improve the docs and the wiki.**

## Getting set up

Python work uses [uv](https://docs.astral.sh/uv/) and Python 3.11; the web apps use Node 22.

```
uv sync --extra dev
uv run pytest
cd apps/console && npm ci && npm run dev
cd apps/live/web && npm ci && npm run dev
```

Branches: `console` carries the research pipeline and the console and is the default.
`agninetra` adds AgniNetra Live. Changes to shared code go to `console` first and are
merged into `agninetra`.

## House rules

These keep the project honest and are checked in CI.

1. No placeholder or invented numbers. A value that was not measured is written as
   `not measured`. Every number in a document comes from a command in the repository.
2. Farm fires are only ever shown per 11 km cell or per district, never as a point that
   could identify a field.
3. Credit every data source, with the wording its licence asks for.
4. Python is formatted and linted with ruff, line length 100. TypeScript is strict and
   parses every boundary with zod.
5. No em dashes or en dashes, and no emoji, in code, docs or commit messages.

## Commits and pull requests

Commit subjects follow `type(scope): imperative subject`, for example
`fix(console): keep the legend visible on narrow screens`. Types are `feat`, `fix`,
`refactor`, `test`, `docs`, `chore`, `data` and `exp`.

Open a pull request against `console` unless the change is to Live only. Describe what
changed and how you checked it. CI runs the Python tests, ruff, the convention checks and
both web builds.

## Conduct

Everyone taking part is expected to follow the [code of conduct](CODE_OF_CONDUCT.md).
