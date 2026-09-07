"""Every tool Claude can call must be wired end to end.

Parsed from source rather than imported: core/brain.py pulls in the whole tool
tree, and a tool that is declared but unreachable fails silently at runtime -
Claude either never sees it, or calls it and gets "Unknown tool".
"""
import ast
from pathlib import Path

import pytest

_BRAIN = Path(__file__).resolve().parent.parent / "core" / "brain.py"


def _consts(node) -> set[str]:
    return {n.value for n in ast.walk(node)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)}


@pytest.fixture(scope="module")
def wiring() -> dict:
    tree = ast.parse(_BRAIN.read_text(encoding="utf-8"))
    declared: list[str] = []
    core: set[str] = set()
    groups: dict[str, set[str]] = {}
    triggers: dict[str, set[str]] = {}

    for node in tree.body:
        if not isinstance(node, ast.AnnAssign):
            continue
        target = getattr(node.target, "id", "")
        if target == "TOOLS":
            for elt in node.value.elts:
                if isinstance(elt, ast.Dict):
                    for k, v in zip(elt.keys, elt.values):
                        if isinstance(k, ast.Constant) and k.value == "name":
                            declared.append(v.value)
        elif target == "_CORE_NAMES":
            core = _consts(node.value)
        elif target == "_TOOL_GROUP_NAMES":
            groups = {k.value: _consts(v) for k, v in zip(node.value.keys, node.value.values)}
        elif target == "_GROUP_TRIGGERS":
            triggers = {k.value: _consts(v) for k, v in zip(node.value.keys, node.value.values)}

    dispatched: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_dispatch_tool_once":
            for cmp_ in [n for n in ast.walk(node) if isinstance(n, ast.Compare)]:
                if isinstance(cmp_.left, ast.Name) and cmp_.left.id == "name":
                    for c in cmp_.comparators:
                        if isinstance(c, ast.Constant):
                            dispatched.add(c.value)
                        elif isinstance(c, (ast.Tuple, ast.List, ast.Set)):
                            dispatched |= {e.value for e in c.elts if isinstance(e, ast.Constant)}

    return {"declared": declared, "dispatched": dispatched,
            "core": core, "groups": groups, "triggers": triggers}


def test_tools_parsed(wiring):
    assert len(wiring["declared"]) > 300, "TOOLS list failed to parse"


def test_no_duplicate_tool_names(wiring):
    declared = wiring["declared"]
    dupes = sorted({n for n in declared if declared.count(n) > 1})
    assert not dupes, f"duplicate tool names shadow each other: {dupes}"


def test_every_declared_tool_has_a_dispatch_branch(wiring):
    missing = sorted(set(wiring["declared"]) - wiring["dispatched"])
    assert not missing, f"declared to Claude but not dispatched: {missing}"


def test_no_orphan_dispatch_branches(wiring):
    orphans = sorted(wiring["dispatched"] - set(wiring["declared"]))
    assert not orphans, f"dispatch branch for a tool Claude is never offered: {orphans}"


def test_every_tool_is_reachable_through_the_group_filter(wiring):
    """_select_tools() only offers core tools plus keyword-triggered groups."""
    grouped = set().union(*wiring["groups"].values()) if wiring["groups"] else set()
    unreachable = sorted(set(wiring["declared"]) - wiring["core"] - grouped)
    assert not unreachable, f"never offered to Claude by _select_tools(): {unreachable}"


def test_every_group_has_trigger_keywords(wiring):
    dead = sorted(g for g in wiring["groups"] if not wiring["triggers"].get(g))
    assert not dead, f"groups with no trigger keywords - their tools never load: {dead}"


def test_group_and_core_names_are_real_tools(wiring):
    grouped = set().union(*wiring["groups"].values()) if wiring["groups"] else set()
    phantom = sorted((wiring["core"] | grouped) - set(wiring["declared"]))
    assert not phantom, f"routed but not defined in TOOLS: {phantom}"
