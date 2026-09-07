"""The heuristic half of the Warden golden set, run offline in every suite.

The other 17 cases need a real key and are the ones that measure Warden's
judgement rather than his cheap checks -- run scripts/eval_warden.py for those.
"""
import json
from pathlib import Path

import pytest

from core.agents.verifier import _heuristic, verify

_CASES = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "warden_cases.json")
    .read_text(encoding="utf-8")
)
_HEURISTIC_CASES = [c for c in _CASES if c["heuristic"]]
_JUDGED_CASES = [c for c in _CASES if not c["heuristic"]]


@pytest.mark.parametrize("case", _HEURISTIC_CASES, ids=lambda c: c["id"])
def test_heuristic_settles_its_cases_without_an_api_call(case):
    verdict, _ = verify(case["task"], case["acceptance"], case["result"])
    assert verdict == case["expect"]


@pytest.mark.parametrize("case", _JUDGED_CASES, ids=lambda c: c["id"])
def test_judged_cases_are_left_for_warden(case):
    """These must NOT be settled by the heuristic -- if one starts short-
    circuiting, the cheap check has grown teeth it was not meant to have and
    good work will be rejected without ever being read."""
    assert _heuristic(case["result"]) is None


def test_the_set_covers_both_error_modes():
    assert any(c["expect"] == "pass" for c in _JUDGED_CASES)
    assert any(c["expect"] == "fail" for c in _JUDGED_CASES)
