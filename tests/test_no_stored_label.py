"""No copy of the weak label is stored or read from the database.

A stored label went stale twice and was read after it had, the second time by the
held out group counts in docs/label_distribution.md, which overstated group_b's
labelled rows by 5896. The rule of record is weak_label_sql, computed at read time.
D124.
"""

import re
import subprocess

from ml.paths import ROOT

STORED_READ = re.compile(r"\b(?:c|context|detection_context)\.weak_label\b|\bAND weak_label <>")


def test_the_context_table_has_no_label_column() -> None:
    source = (ROOT / "scripts" / "build_features_3b.py").read_text()
    ddl = source[source.index("CREATE OR REPLACE TABLE detection_context") :]
    ddl = ddl[: ddl.index(");")]
    for column in ("weak_label", "label_source", "label_rule", "label_confidence"):
        assert column not in ddl, f"detection_context stores {column} again"


def test_no_source_reads_a_stored_label() -> None:
    listed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "*.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    offenders = [
        path
        for path in listed
        if not path.startswith("tests/") and STORED_READ.search((ROOT / path).read_text())
    ]
    assert not offenders, f"reads a stored label rather than weak_label_sql: {offenders}"
