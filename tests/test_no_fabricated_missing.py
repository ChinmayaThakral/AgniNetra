"""A missing recurrence value must never be coalesced into a real one.

`FEATURE_SQL` carried `coalesce(r.prior_count_90d, 0)`. A detection with no
recurrence row was told its location had zero prior detections in 90 days, which is
a measurement it did not have. Because `detection_recurrence` had not been rebuilt
after the seasonal ingest, that fabricated a zero for 92.1 percent of B1's training
rows, and the rate differed by class, so the feature partly encoded which window a
detection came from. D61.

One line caused it and nothing failed. This is the test that would have.
"""

import re

from ml.features.matrix import FEATURE_SQL
from ml.paths import ROOT

# Anything derived from prior observations at a location. A default here is a claim
# about history that was never measured.
RECURRENCE_COLUMNS = (
    "prior_count_90d",
    "prior_count_30d",
    "night_fraction_90d",
    "frp_variance_90d",
    "mean_gap_days",
)

SQL_SOURCES = (
    ROOT / "ml" / "features" / "matrix.py",
    ROOT / "scripts" / "build_features_3b.py",
)


def test_feature_sql_does_not_default_a_recurrence_column() -> None:
    for column in RECURRENCE_COLUMNS:
        pattern = re.compile(
            rf"(coalesce|ifnull|nvl)\s*\(\s*[\w.]*{re.escape(column)}\b", re.IGNORECASE
        )
        assert not pattern.search(FEATURE_SQL), (
            f"{column} is being defaulted in FEATURE_SQL. A missing recurrence value "
            "means not computed, not zero. Pass NULL through: HistGradientBoosting "
            "handles it natively. D61."
        )


def test_no_sql_file_defaults_a_recurrence_column() -> None:
    """The guard has to cover every file that assembles the feature frame, not only
    the one where the defect happened to live."""
    offenders = []
    for path in SQL_SOURCES:
        if not path.is_file():
            continue
        text = path.read_text()
        for number, line in enumerate(text.splitlines(), start=1):
            if line.lstrip().startswith("#"):
                continue
            for column in RECURRENCE_COLUMNS:
                if re.search(
                    rf"(coalesce|ifnull|nvl)\s*\(\s*[\w.]*{re.escape(column)}\b",
                    line,
                    re.IGNORECASE,
                ):
                    offenders.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()[:80]}")
    assert not offenders, "\n".join(offenders)


def test_the_recurrence_columns_are_still_features() -> None:
    """If someone deletes the columns rather than fixing the default, this fails and
    says so, because dropping them silently would also make the test above pass."""
    from ml.features.matrix import FEATURE_COLUMNS

    for column in RECURRENCE_COLUMNS:
        assert column in FEATURE_COLUMNS, f"{column} left FEATURE_COLUMNS"
