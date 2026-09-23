"""A majority vote with a tie must not depend on how Python hashes strings.

D75 found `max(set(labels), key=labels.count)` returning a different winner from one
process to the next whenever the top two counts tied, because a set iterates in an
order that depends on the per process string hash seed. On Gujarat 26 of 621 cells
with four or more detections tied, and each flipped class between runs. The fix sorts
the set first. It was applied in four scripts and never tested, so nothing stopped the
defective form coming back. D121.

The behavioural test runs the vote under several hash seeds in fresh processes. It
also runs the defective form and requires that to vary, which proves the test can see
the defect rather than passing because every seed happened to agree.
"""

import ast
import subprocess
import sys

from ml.paths import ROOT
from ml.tracked import tracked_files

HASH_SEEDS = ("0", "1", "2", "3", "7", "11", "42", "101")
TIED = "['industrial', 'flare', 'flare', 'industrial', 'agricultural']"


def _winner(expression: str, seed: str) -> str:
    code = f"labels = {TIED}\nprint({expression})"
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
        env={"PYTHONHASHSEED": seed},
    )
    return result.stdout.strip()


def test_the_sorted_vote_is_the_same_under_every_hash_seed() -> None:
    winners = {_winner("max(sorted(set(labels)), key=labels.count)", s) for s in HASH_SEEDS}
    assert winners == {"flare"}, winners


def test_the_defective_vote_does_vary_so_this_test_can_see_it() -> None:
    winners = {_winner("max(set(labels), key=labels.count)", s) for s in HASH_SEEDS}
    assert len(winners) > 1, (
        "the unsorted form gave one winner under every seed tried, so the seed list no "
        f"longer exposes the defect and the test above proves nothing: {winners}"
    )


def _unsorted_set_votes(tree: ast.AST) -> list[int]:
    lines = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"max", "min"}
            and node.args
            and isinstance(node.args[0], ast.Call)
            and isinstance(node.args[0].func, ast.Name)
            and node.args[0].func.id in {"set", "frozenset"}
            and any(k.arg == "key" for k in node.keywords)
        ):
            lines.append(node.lineno)
    return lines


def test_no_code_votes_over_an_unsorted_set() -> None:
    offenders = []
    for path in tracked_files((".py",)):
        relative = path.relative_to(ROOT).as_posix()
        if not relative.startswith(("ml/", "scripts/")):
            continue
        tree = ast.parse(path.read_text(), filename=relative)
        offenders += [f"{relative}:{line}" for line in _unsorted_set_votes(tree)]
    assert not offenders, f"max or min over an unsorted set with a key, D75: {offenders}"


def test_the_static_check_recognises_the_defective_shape() -> None:
    assert _unsorted_set_votes(ast.parse("w = max(set(x), key=x.count)")) == [1]
    assert _unsorted_set_votes(ast.parse("w = max(sorted(set(x)), key=x.count)")) == []
