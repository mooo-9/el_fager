"""El Fager's commander tools, and calling an agent by name."""
from unittest.mock import MagicMock, patch

import pytest

from core.agents.router import parse_callsign
from core.agents.supervisor import AgentReport
from tools.agent_tool import agent_report, agent_roster, delegate


@pytest.fixture(autouse=True)
def ledger_in_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr("core.agents.ledger._LEDGER_PATH",
                        tmp_path / "agent_runs.jsonl")


class TestDelegate:
    def test_passing_work_is_reported_as_finished(self):
        report = AgentReport("Sage", "pass", "three brokers, fees listed")
        with patch("core.agents.supervisor.assign", return_value=report) as assign:
            out = delegate("Sage", "research brokers", "at least 3 brokers")
        assert "Sage finished it" in out
        assert "three brokers" in out
        assert assign.call_args.kwargs["acceptance"] == "at least 3 brokers"
        assert assign.call_args.kwargs["verify"] is True

    def test_failed_work_is_reported_as_failed_not_papered_over(self):
        report = AgentReport("Sage", "fail", "", reason="only described the plan",
                             attempts=2)
        with patch("core.agents.supervisor.assign", return_value=report):
            out = delegate("Sage", "research brokers")
        assert "could not finish" in out
        assert "only described the plan" in out

    def test_budget_block_passes_the_explanation_through(self):
        report = AgentReport("Sage", "blocked", "I did not start Sage: budget reached.")
        with patch("core.agents.supervisor.assign", return_value=report):
            assert delegate("Sage", "t") == "I did not start Sage: budget reached."

    def test_unknown_agent_lists_the_real_ones(self):
        out = delegate("Gandalf", "t")
        assert "no agent called 'Gandalf'" in out
        assert "Sage" in out

    def test_callsign_resolves_to_the_tool_name(self):
        with patch("core.agents.supervisor.assign",
                   return_value=AgentReport("Sage", "pass", "x")) as assign:
            delegate("sage", "t")
        assert assign.call_args.args[0] == "research_agent"


class TestRoster:
    def test_roster_names_every_agent_and_the_inspector(self):
        out = agent_roster()
        for callsign in ("Argus", "Nomad", "Midas", "Sage", "Scribe", "Vitals", "Warden"):
            assert callsign in out
        assert "No agent is working right now" in out

    def test_roster_shows_work_in_flight(self):
        from core.agents import ledger
        token = ledger.start_run("Sage", "research brokers", "voice")
        try:
            assert "Working right now" in agent_roster()
        finally:
            ledger.finish_run(token)


class TestReport:
    def test_report_summarises_the_ledger(self):
        from core.agents import ledger
        ledger.record("Sage", "a", "pass")
        ledger.record("Sage", "b", "fail")
        out = agent_report("Sage")
        assert "Sage" in out and "50%" in out

    def test_report_rejects_an_unknown_agent(self):
        assert "no agent called" in agent_report("Gandalf")


class TestParseCallsign:
    @pytest.mark.parametrize("message,expected_task", [
        ("Sage, research Egyptian brokers", "research Egyptian brokers"),
        ("sage research Egyptian brokers", "research Egyptian brokers"),
        ("Scribe: summarize this contract", "summarize this contract"),
        ("VITALS log my lunch", "log my lunch"),
    ])
    def test_addressing_an_agent_by_name(self, message, expected_task):
        result = parse_callsign(message)
        assert result is not None
        assert result[1] == expected_task

    def test_maps_to_the_right_tool(self):
        assert parse_callsign("Sage, research x")[0] == "research_agent"
        assert parse_callsign("Argus, click submit")[0] == "screen_agent"

    @pytest.mark.parametrize("message", [
        "what is the weather in Cairo",
        "Sage",          # a name with no task
        "Sage ok",       # too short to be a task
        "tell Sage to research x",  # not addressed at the start
        "",
    ])
    def test_non_invocations_are_ignored(self, message):
        assert parse_callsign(message) is None


class TestBrainDispatch:
    def test_agent_tool_goes_through_the_supervisor_unverified(self):
        from core.brain import Brain
        brain = Brain(profile={})
        report = AgentReport("Sage", "pass", "a research answer")
        with patch("core.agents.supervisor.assign", return_value=report) as assign:
            out = brain._dispatch_tool("research_agent", {"task": "research x"})
        assert out == "a research answer"
        assert assign.call_args.kwargs["verify"] is False

    def test_a_failing_agent_reports_failure_rather_than_an_empty_string(self):
        from core.brain import Brain
        brain = Brain(profile={})
        report = AgentReport("Nomad", "fail", "", reason="timed out after 240s")
        with patch("core.agents.supervisor.assign", return_value=report):
            out = brain._dispatch_tool("browser_agent", {"task": "book a table"})
        assert "Nomad could not finish" in out
        assert "timed out" in out

    def test_callsign_is_intercepted_before_the_tool_loop(self):
        from core.brain import Brain
        brain = Brain(profile={})
        report = AgentReport("Sage", "pass", "a research answer")
        with patch("core.agents.supervisor.assign", return_value=report) as assign:
            out = brain._try_agent_dispatch("Sage, research Egyptian brokers")
        assert out == "a research answer"
        assert assign.call_args.args == ("research_agent", "research Egyptian brokers")

    def test_a_callsign_cannot_bypass_the_live_trading_confirmation(self):
        """Financial-safety intents are checked before callsign routing."""
        from core.brain import Brain
        brain = Brain(profile={})
        with patch("core.agents.supervisor.assign") as assign:
            out = brain._try_agent_dispatch("Midas, confirm live trading")
        assign.assert_not_called()
        assert "CAUTION" in out

    def test_ordinary_messages_still_fall_through_to_the_tool_loop(self):
        from core.brain import Brain
        assert Brain(profile={})._try_agent_dispatch("what is the weather") is None
