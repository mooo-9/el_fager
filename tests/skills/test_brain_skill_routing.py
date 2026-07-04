"""Brain wiring tests for SkillForge tools."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from unittest.mock import MagicMock, patch


def _make_brain():
    from core.brain import Brain
    return Brain(profile={})


def _tool_use_response(tool_name: str, tool_input: dict, tool_id: str = "t1"):
    block = MagicMock()
    block.type = "tool_use"
    block.name = tool_name
    block.input = tool_input
    block.id = tool_id
    response = MagicMock()
    response.stop_reason = "tool_use"
    response.content = [block]
    return response


def _end_turn_response(text: str):
    block = MagicMock()
    block.type = "text"
    block.text = text
    response = MagicMock()
    response.stop_reason = "end_turn"
    response.content = [block]
    return response


def test_all_skill_tools_have_schemas():
    from core.brain import TOOLS
    names = {t["name"] for t in TOOLS}
    expected = {"learn_skill", "list_skills", "run_skill", "delete_skill",
                "schedule_skill", "unschedule_skill", "skill_proposals",
                "dismiss_skill_proposal"}
    assert expected <= names


def test_run_skill_always_available():
    from core.brain import _select_tools
    names = {t["name"] for t in _select_tools("random unrelated message")}
    assert "run_skill" in names
    assert "learn_skill" in names


def test_skill_keywords_expose_full_group():
    from core.brain import _select_tools
    names = {t["name"] for t in _select_tools("can you automate my routine")}
    assert "schedule_skill" in names
    assert "skill_proposals" in names


def test_chat_runs_skill_then_executes_steps():
    brain = _make_brain()
    responses = [
        _tool_use_response("run_skill", {"name": "focus mode"}, "t1"),
        _tool_use_response("web_search", {"query": "lofi focus playlist"}, "t2"),
        _end_turn_response("Focus mode is on, Mo."),
    ]
    with patch.object(brain.client.messages, "create", side_effect=responses), \
         patch("tools.skill_tool.run_skill",
               return_value="SKILL 'focus mode' -- execute: play focus music"), \
         patch("tools.web_tool.web_search", return_value="playlist found"):
        result = brain.chat("focus time")
    assert result == "Focus mode is on, Mo."


def test_dispatch_routes_all_skill_tools():
    brain = _make_brain()
    with patch("tools.skill_tool.list_skills", return_value="Skills: none") as ls:
        out = brain._dispatch_tool("list_skills", {})
    ls.assert_called_once()
    assert out == "Skills: none"
