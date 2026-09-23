"""The analysis population, defined once so no query has to remember it.

The `detections` table holds every row ever ingested. That is not the population
any published result describes.

On 2026-09-16 a FIRMS backfill pulled 2025-05-04 to 2025-05-08, 41029 rows, to check
whether the rabi INSAT window had independent corroboration. Those rows are
validation data: a different season, gathered for a different question. They took
the table from 601941 to 642970.

Every result in this project was computed on the 601941. Scripts that join
`detection_context` stayed correct by accident, because that table was built before
the backfill and has exactly the 601941 rows. Scripts that queried `detections`
directly silently started describing a different population, which is how
`gem_temporal_validity.md` came to publish a share of 3.54 percent for data that no
longer existed. D114.

Constraining the population is also the answer to decision B, which asked which rows
the feature build should cover. The answer is the analysis population, named here,
rather than whatever happens to be in the table on the day.
"""

from typing import Final

# Windows pulled to answer a question other than the one the results report on.
VALIDATION_WINDOWS: Final[tuple[tuple[str, str, str], ...]] = (
    (
        "2025-05-01",
        "2025-05-31",
        "May 2025 rabi corroboration backfill, ingested 2026-09-16",
    ),
)

EXPECTED_ROWS: Final[int] = 601941


def analysis_predicate(alias: str = "d") -> str:
    """SQL predicate selecting the analysis population from `detections`.

    Written as a predicate rather than a view so a caller can see it in the query it
    is reading, and so a query that forgets it is visibly different from one that
    does not.
    """
    clauses = [
        f"NOT ({alias}.acq_date_ist BETWEEN DATE '{start}' AND DATE '{end}')"
        for start, end, _ in VALIDATION_WINDOWS
    ]
    return " AND ".join(clauses) if clauses else "TRUE"


def analysis_where(alias: str = "d") -> str:
    """The predicate as a complete WHERE clause, empty when nothing is excluded."""
    predicate = analysis_predicate(alias)
    return "" if predicate == "TRUE" else f"WHERE {predicate}"
