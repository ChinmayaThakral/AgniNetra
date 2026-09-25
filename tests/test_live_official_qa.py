"""The private check against ISRO's product stays private and flags what it says it does.

MOSDAC forbids redistributing its products as downloaded, D126, so nothing the public
feed is built from may import the check, and its output lives under data/, which git
never tracks.
"""

import ast

from ml.paths import ROOT

PIPELINE = ROOT / "apps" / "live" / "pipeline"


def _flag():
    source = (PIPELINE / "official_qa.py").read_text()
    tree = ast.parse(source)
    namespace: dict = {}
    wanted = {"MIN_CELLS", "RATIO_LIMIT", "flag"}
    nodes = [
        n
        for n in tree.body
        if (isinstance(n, ast.FunctionDef) and n.name in wanted)
        or (isinstance(n, ast.Assign) and any(getattr(t, "id", "") in wanted for t in n.targets))
    ]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "official_qa", "exec"), namespace)
    return namespace["flag"]


def test_quiet_hours_are_never_flagged() -> None:
    assert _flag()(3, 0) is False


def test_one_record_seeing_nothing_is_flagged() -> None:
    assert _flag()(40, 0) is True


def test_a_fivefold_gap_is_flagged_and_a_threefold_one_is_not() -> None:
    flag = _flag()
    assert flag(60, 11) is True
    assert flag(30, 11) is False


def test_nothing_that_builds_the_public_feed_imports_the_check() -> None:
    for name in ("feed.py", "sources.py", "build_feed.py"):
        tree = ast.parse((PIPELINE / name).read_text())
        imported = {
            getattr(node, "module", None) or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        } | {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        assert not any("official" in module for module in imported), name


def test_the_check_writes_only_under_data() -> None:
    source = (PIPELINE / "official_qa.py").read_text()
    assert 'OUT = DATA_DIR / "live_qa"' in source
    assert "L2P_FIR" not in (PIPELINE / "build_feed.py").read_text()
