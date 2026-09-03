# console

The Next.js console. It demonstrates the result. It does not produce it.

Scaffolded in phase 7. This directory holds only this README until then.

## What it does

Reads precomputed results exported by the Python side: class posteriors, conformal
prediction sets, applicability domain status, recurrence history per location.

Renders a map, a timeline scrubber, a per detection evidence panel, a persistent
source panel, and export to CSV and GeoJSON.

## What it does not do

It does not run a model, does not fit anything, does not call a Python process, and
does not reach any external data provider at request time.

The one piece of model code here is the hand written tree evaluator in
`lib/tree-eval.ts`, which reads the JSON export from phase 4. A test asserts it
agrees with the Python implementation to 1e-5 on a fixed sample. That test is the
contract between the two sides.

## Constraints

TypeScript strict. A zod schema at every boundary, including the model JSON. Server
components by default. No browser storage APIs; state that must survive a reload
goes in the URL.

No number is displayed without its units and, where the pipeline produces one, its
uncertainty. A probability shown without its conformal set misrepresents what the
system knows.
