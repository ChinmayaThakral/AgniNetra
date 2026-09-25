"""The transaction counters ingest_runs was designed to carry, now recorded.

Twenty runs wrote NULL into transactions_before and transactions_after because the
backfill printed the map key status and never parsed it. These pin the parse and
the per run read, both with no network access.
"""

import importlib.util
import sys

import pytest

from ml.ingest.firms import (
    FirmsClient,
    Response,
    TransactionStatusError,
    parse_transactions,
)
from ml.paths import ROOT

_spec = importlib.util.spec_from_file_location(
    "backfill_firms", ROOT / "scripts" / "backfill_firms.py"
)
assert _spec is not None and _spec.loader is not None
backfill = importlib.util.module_from_spec(_spec)
sys.modules["backfill_firms"] = backfill
_spec.loader.exec_module(backfill)

LIVE_SHAPE = (
    '{ "transaction_limit" : 5000, "current_transactions": 37, '
    '"transaction_interval" : "10 minutes" }'
)


class QueuedTransport:
    def __init__(self, bodies: list[str]) -> None:
        self._bodies = list(bodies)

    def get(self, url: str) -> Response:
        return Response(200, self._bodies.pop(0))


def test_the_live_response_shape_parses() -> None:
    assert parse_transactions(LIVE_SHAPE) == 37


@pytest.mark.parametrize(
    "body",
    [
        "not json",
        '{"transaction_limit": 5000}',
        '{"current_transactions": "37"}',
        '{"current_transactions": 3.5}',
        '{"current_transactions": true}',
        "[1, 2]",
    ],
)
def test_an_unreadable_count_is_refused_rather_than_guessed(body: str) -> None:
    with pytest.raises(TransactionStatusError):
        parse_transactions(body)


def test_a_run_reads_the_count_through_the_client() -> None:
    client = FirmsClient("k", QueuedTransport([LIVE_SHAPE]), sleep=lambda _: None)
    assert backfill.read_transactions(client) == 37


def test_an_unreadable_count_is_stored_as_null(capsys: pytest.CaptureFixture[str]) -> None:
    client = FirmsClient("k", QueuedTransport(["<html>down</html>"]), sleep=lambda _: None)
    assert backfill.read_transactions(client) is None
    assert "transactions not recorded" in capsys.readouterr().err


def test_the_insert_names_both_counter_columns() -> None:
    source = (ROOT / "scripts" / "backfill_firms.py").read_text()
    assert "transactions_before, " in source
    assert '"transactions_after, started_at' in source
