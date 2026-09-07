"""Tests for tools/mission_tool.py, the proactive mission executor, and
brain wiring for mission tools."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import MagicMock, patch

import pytest

import core.missions as mi
import tools.mission_tool as mt


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(mi, "_MISSIONS_PATH", tmp_path / "missions.json")
    yield tmp_path


class TestMissionTools:
    def test_start_mission_parses_numbered_lines(self):
        out = mt.start_mission("research brokers",
                               "1. find brokers\n2. compare fees\n3. summarize")
        assert "3 steps" in out
        mgr = mi.MissionManager()
        steps = mgr.get_active()["steps"]
        assert steps[0]["description"] == "find brokers"

    def test_start_mission_semicolon_separated(self):
        mt.start_mission("g", "step one; step two")
        assert len(mi.MissionManager().get_active()["steps"]) == 2

    def test_second_mission_refused_while_active(self):
        mt.start_mission("g", "a")
        out = mt.start_mission("g2", "b")
        assert "already in progress" in out

    def test_status_and_cancel(self):
        mt.start_mission("my goal", "a; b")
        assert "my goal" in mt.mission_status()
        assert "cancelled" in mt.cancel_mission()
        assert "No mission is running" in mt.cancel_mission()


class TestProactiveMissionExecutor:
    def _engine(self, tmp_path, monkeypatch, brain_fn):
        import core.proactive as pa
        from core.proactive import ProactiveEngine
        monkeypatch.setattr(pa, "_STATE_FILE", tmp_path / "state.json")
        e = ProactiveEngine(speak_fn=None, brain_fn=brain_fn)
        e._deliver = MagicMock()
        return e

    def test_executes_one_step_per_cycle(self, isolated, monkeypatch):
        brain = MagicMock(return_value="step result")
        engine = self._engine(isolated, monkeypatch, brain)
        mt.start_mission("g", "one; two")
        engine._check_missions()
        assert brain.call_count == 1
        active = mi.MissionManager().get_active()
        assert active["steps"][0]["status"] == "done"
        assert active["steps"][1]["status"] == "pending"

    def test_step_prompt_includes_goal_and_prior_results(self, isolated, monkeypatch):
        brain = MagicMock(return_value="found 5 brokers")
        engine = self._engine(isolated, monkeypatch, brain)
        mt.start_mission("research brokers", "find; compare")
        engine._check_missions()
        engine._check_missions()
        second_prompt = brain.call_args_list[1].args[0]
        assert "research brokers" in second_prompt
        assert "found 5 brokers" in second_prompt

    def test_completion_announced(self, isolated, monkeypatch):
        brain = MagicMock(return_value="all done")
        engine = self._engine(isolated, monkeypatch, brain)
        mt.start_mission("g", "only step")
        engine._check_missions()
        engine._deliver.assert_called_once()
        assert "Mission complete" in engine._deliver.call_args.args[0]

    def test_failure_retries_then_blocks_and_announces(self, isolated, monkeypatch):
        brain = MagicMock(side_effect=RuntimeError("API down"))
        engine = self._engine(isolated, monkeypatch, brain)
        mt.start_mission("g", "fragile step")
        engine._check_missions()  # attempt 1 -> retry
        assert mi.MissionManager().get_active() is not None
        engine._deliver.assert_not_called()
        engine._check_missions()  # attempt 2 -> blocked
        assert mi.MissionManager().get_active() is None
        engine._deliver.assert_called_once()
        assert "stuck" in engine._deliver.call_args.args[0]

    def test_no_mission_no_brain_calls(self, isolated, monkeypatch):
        brain = MagicMock()
        engine = self._engine(isolated, monkeypatch, brain)
        engine._check_missions()
        brain.assert_not_called()

    def test_no_brain_fn_is_silent(self, isolated, monkeypatch):
        engine = self._engine(isolated, monkeypatch, None)
        mt.start_mission("g", "a")
        engine._check_missions()  # must not raise


class TestParallelParsing:
    def test_ampersand_joins_previous_group(self):
        mt.start_mission("g", "1. research A\n& research B\ncompare\nsummarize")
        steps = mi.MissionManager().get_active()["steps"]
        assert [s["group"] for s in steps] == [1, 1, 2, 3]
        assert steps[1]["description"] == "research B"

    def test_leading_ampersand_on_first_step_starts_group_one(self):
        mt.start_mission("g", "& weird first\nsecond")
        steps = mi.MissionManager().get_active()["steps"]
        assert [s["group"] for s in steps] == [1, 2]


class TestParallelExecution:
    def _engine(self, tmp_path, monkeypatch, brain_fn):
        import core.proactive as pa
        from core.proactive import ProactiveEngine
        monkeypatch.setattr(pa, "_STATE_FILE", tmp_path / "state.json")
        e = ProactiveEngine(speak_fn=None, brain_fn=brain_fn)
        e._deliver = MagicMock()
        return e

    def test_grouped_steps_run_in_one_cycle(self, isolated, monkeypatch):
        brain = MagicMock(return_value="r")
        engine = self._engine(isolated, monkeypatch, brain)
        mt.start_mission("g", "1. find A\n& find B\ncompare")
        engine._check_missions()
        assert brain.call_count == 2  # group 1 both steps, group 2 waits
        active = mi.MissionManager().get_active()
        assert [s["status"] for s in active["steps"]] == ["done", "done", "pending"]

    def test_cap_three_steps_per_cycle(self, isolated, monkeypatch):
        brain = MagicMock(return_value="r")
        engine = self._engine(isolated, monkeypatch, brain)
        mt.start_mission("g", "a\n& b\n& c\n& d")
        engine._check_missions()
        assert brain.call_count == 3
        engine._check_missions()
        assert brain.call_count == 4

    def test_failure_in_group_stops_cycle_but_retries(self, isolated, monkeypatch):
        brain = MagicMock(side_effect=["ok", RuntimeError("boom"), "ok", "ok"])
        engine = self._engine(isolated, monkeypatch, brain)
        mt.start_mission("g", "a\n& b\nlast")
        engine._check_missions()  # a ok, b fails -> retry queued
        active = mi.MissionManager().get_active()
        statuses = {s["description"]: s["status"] for s in active["steps"]}
        assert statuses == {"a": "done", "b": "pending", "last": "pending"}
        engine._check_missions()  # b retried ok
        engine._check_missions()  # last runs
        assert mi.MissionManager().get_active() is None


class TestBrainWiring:
    def test_mission_tools_have_schemas(self):
        from core.brain import TOOLS
        names = {t["name"] for t in TOOLS}
        assert {"start_mission", "mission_status", "cancel_mission"} <= names

    def test_mission_keywords_expose_group(self):
        from core.brain import _select_tools
        names = {t["name"] for t in _select_tools("plan and execute this overnight")}
        assert "start_mission" in names

    def test_dispatch_routes_mission_status(self):
        from core.brain import Brain
        brain = Brain(profile={})
        with patch("tools.mission_tool.mission_status",
                   return_value="No mission running.") as ms:
            out = brain._dispatch_tool("mission_status", {})
        ms.assert_called_once()
        assert out == "No mission running."
