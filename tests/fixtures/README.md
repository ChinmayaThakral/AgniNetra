# Test fixtures

Every file here contains synthetic rows invented for the test suite. None of it is
real satellite data and none of it may reach the detections table.

Three things enforce that:

1. Every file name begins with `SYNTHETIC_`.
2. Every row carries `SYNTHETIC_FIXTURE` in its `version` column.
3. `ml.ingest.load.insert_detections` raises `FixtureRowRefusedError` on any row
   carrying that marker unless the caller passes `allow_fixture_rows=True`, which
   only the test suite does.

Recorded as decision D8.
