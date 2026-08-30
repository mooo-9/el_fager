"""Mission steps only advance when the work actually passed inspection.

Before the supervisor existed, core/proactive.py marked a step done whenever
brain.chat() returned without raising -- so a step whose result was
"I couldn't do that" counted as complete and the mission moved on.
"""
from unittest.mock import MagicMock, patch

import pytest

from core.missions import MissionManager
from core.proactive import ProactiveEngine
from tools.mission_tool import start_mission


@pytest.fixture
def mgr(tmp_path):
    return MissionManager(path=tmp_path / "missions.json")


@pytest.fixture
def engine(monkeypatch, tmp_path):
    monkeypatch.setattr("core.proactive._STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr("core.agents.ledger._LEDGER_PATH", tmp_path / "runs.jsonl")
    engine = ProactiveEngine(speak_fn=MagicMock())
    engine._deliver = MagicMock()
    return engine


class TestStepParsing:
    def test_agent_and_acceptance_are_stored_on_the_step(self, mgr, monkeypatch):
        monkeypatch.setattr("tools.mission_tool._mgr", lambda: mgr)
        start_mission("compare brokers", "\n".join([
            "@sage research European brokers -> at least 3 brokers with fees",
            "& @sage research Egyptian rules",
            "write a summary",
        ]))
        steps = mgr.get_active()["steps"]
        assert [s["agent"] for s in steps] == ["Sage", "Sage", None]
        assert steps[0]["acceptance"] == "at least 3 brokers with fees"
        assert steps[1]["acceptance"] is None
        # '&' still groups steps into one cycle
        assert steps[0]["group"] == steps[1]["group"] != steps[2]["group"]

    def test_plain_missions_are_unchanged(self, mgr, monkeypatch):
        monkeypatch.setattr("tools.mission_tool._mgr", lambda: mgr)
        start_mission("do things", "step one\nstep two")
        steps = mgr.get_active()["steps"]
        assert [s["agent"] for s in steps] == [None, None]
        assert [s["group"] for s in steps] == [1, 2]

    def test_assigned_crew_is_named_back_to_mo(self, mgr, monkeypatch):
        monkeypatch.setattr("tools.mission_tool._mgr", lambda: mgr)
        assert "Assigned to Sage" in start_mission("g", "@sage research x")


class TestSupervisedExecution:
    def _run(self, engine, mgr, monkeypatch, brain_result, verdict):
        monkeypatch.setattr("core.missions.MissionManager", lambda: mgr)
        engine._brain_fn = MagicMock(return_value=brain_result)
        with patch("core.agents.verifier.verify", return_value=verdict):
            engine._check_missions()

    def test_passing_step_advances_the_mission(self, engine, mgr, monkeypatch):
        mgr.create("g", ["step one", "step two"])
        self._run(engine, mgr, monkeypatch, "step one is finished", ("pass", ""))
        steps = mgr.get_active()["steps"]
        assert steps[0]["status"] == "done"
        assert steps[1]["status"] == "pending"

    def test_rejected_step_is_requeued_not_marked_done(self, engine, mgr, monkeypatch):
        mgr.create("g", ["step one", "step two"])
        self._run(engine, mgr, monkeypatch, "I could not do that.",
                  ("fail", "the assistant declined the step"))
        step = mgr.get_active()["steps"][0]
        assert step["status"] == "pending"      # requeued, NOT done
        assert step["attempts"] == 1

    def test_second_rejection_blocks_the_mission_and_escalates(self, engine, mgr, monkeypatch):
        mgr.create("g", ["step one"])
        for _ in range(2):
            self._run(engine, mgr, monkeypatch, "I could not do that.",
                      ("fail", "the assistant declined the step"))
        assert mgr.get_active() is None
        assert mgr.last_finished()["status"] == "blocked"
        spoken = engine._deliver.call_args.args[0]
        assert "stuck at step 1" in spoken
        assert "declined the step" in spoken   # Mo is told WHY

    def test_acceptance_criteria_reach_the_inspector(self, engine, mgr, monkeypatch):
        mgr.create("g", ["research brokers"], agents=[None],
                   acceptance=["at least 3 brokers with fees"])
        monkeypatch.setattr("core.missions.MissionManager", lambda: mgr)
        engine._brain_fn = MagicMock(return_value="a long enough result string")
        with patch("core.agents.verifier.verify", return_value=("pass", "")) as inspect:
            engine._check_missions()
        assert inspect.call_args.args[1] == "at least 3 brokers with fees"

    def test_assigned_step_goes_to_that_agent_not_the_brain(self, engine, mgr, monkeypatch):
        mgr.create("g", ["research brokers"], agents=["Sage"], acceptance=[None])
        monkeypatch.setattr("core.missions.MissionManager", lambda: mgr)
        engine._brain_fn = MagicMock()
        agent = MagicMock()
        agent.run.return_value = "three brokers with fee tables"
        with patch("core.agents.registry.load", return_value=agent), \
             patch("core.agents.verifier.verify", return_value=("pass", "")):
            engine._check_missions()
        agent.run.assert_called_once()
        engine._brain_fn.assert_not_called()
        assert mgr.last_finished()["status"] == "done"

    def test_completed_mission_is_announced(self, engine, mgr, monkeypatch):
        mgr.create("g", ["only step"])
        self._run(engine, mgr, monkeypatch, "the step is finished", ("pass", ""))
        assert "Mission complete" in engine._deliver.call_args.args[0]
