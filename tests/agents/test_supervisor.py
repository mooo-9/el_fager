"""The supervisor is what makes El Fager the head of the agents: it holds each
one to the task and never marks unfinished work as done."""
from unittest.mock import MagicMock, patch

import pytest

from core.agents.supervisor import assign


@pytest.fixture(autouse=True)
def ledger_in_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr("core.agents.ledger._LEDGER_PATH",
                        tmp_path / "agent_runs.jsonl")
    return tmp_path / "agent_runs.jsonl"


@pytest.fixture(autouse=True)
def under_budget():
    with patch("core.telemetry.over_budget", return_value=(False, 0.0, 5.0)):
        yield


def _agent(*results):
    agent = MagicMock()
    agent.run.side_effect = list(results)
    return agent


class TestHappyPath:
    def test_passing_result_runs_once(self):
        agent = _agent("three brokers with fee tables")
        with patch("core.agents.registry.load", return_value=agent), \
             patch("core.agents.verifier.verify", return_value=("pass", "")):
            report = assign("Sage", "research brokers")
        assert report.ok and report.attempts == 1
        assert agent.run.call_count == 1
        assert report.callsign == "Sage"

    def test_callsign_and_tool_name_both_dispatch(self):
        with patch("core.agents.registry.load", return_value=_agent("a result here")), \
             patch("core.agents.verifier.verify", return_value=("pass", "")):
            assert assign("research_agent", "t").callsign == "Sage"

    def test_verify_false_skips_the_inspector(self):
        with patch("core.agents.registry.load", return_value=_agent("x")), \
             patch("core.agents.verifier.verify") as inspect:
            report = assign("Sage", "t", verify=False)
        inspect.assert_not_called()
        assert report.ok


class TestRetryAndEscalation:
    def test_failed_verdict_retries_once_carrying_the_reason(self):
        agent = _agent("first try", "second try")
        with patch("core.agents.registry.load", return_value=agent), \
             patch("core.agents.verifier.verify",
                   side_effect=[("fail", "only described the plan"), ("pass", "")]):
            report = assign("Sage", "research brokers")
        assert report.ok and report.attempts == 2
        assert agent.run.call_count == 2
        assert "only described the plan" in agent.run.call_args_list[1].args[0]

    def test_two_failures_give_up_and_report_not_ok(self):
        agent = _agent("nope", "nope again")
        with patch("core.agents.registry.load", return_value=agent), \
             patch("core.agents.verifier.verify", return_value=("fail", "not done")):
            report = assign("Sage", "research brokers")
        assert not report.ok
        assert report.attempts == 2
        assert agent.run.call_count == 2
        assert "not done" in report.speech

    def test_unclear_verdict_counts_as_a_pass(self):
        """A broken inspector must not fail an agent that worked."""
        with patch("core.agents.registry.load", return_value=_agent("a result")), \
             patch("core.agents.verifier.verify",
                   return_value=("unclear", "inspection unavailable")):
            assert assign("Sage", "t").ok

    def test_raising_agent_is_a_failure_not_a_crash(self):
        agent = MagicMock()
        agent.run.side_effect = RuntimeError("playwright missing")
        with patch("core.agents.registry.load", return_value=agent):
            report = assign("Sage", "t")
        assert not report.ok
        assert "playwright missing" in report.reason


class TestGuards:
    def test_hanging_agent_trips_the_timeout(self):
        import time
        agent = MagicMock()
        agent.run.side_effect = lambda task: time.sleep(5)
        with patch("core.agents.registry.load", return_value=agent), \
             patch("core.agents.registry.resolve") as resolve:
            resolve.return_value = MagicMock(callsign="Sage", tool_name="research_agent",
                                             timeout_s=1)
            report = assign("Sage", "t")
        assert not report.ok
        assert "timed out" in report.reason

    def test_over_budget_refuses_without_executing(self):
        agent = _agent("should never run")
        with patch("core.telemetry.over_budget", return_value=(True, 9.0, 5.0)), \
             patch("core.agents.registry.load", return_value=agent):
            report = assign("Sage", "t")
        assert report.verdict == "blocked"
        assert not report.ok
        agent.run.assert_not_called()
        assert "9.00" in report.result

    def test_unknown_agent_is_rejected(self):
        report = assign("Gandalf", "t")
        assert not report.ok
        assert report.reason == "unknown agent"


class TestExecutorInjection:
    def test_executor_replaces_the_registry_agent(self):
        calls = []
        with patch("core.agents.verifier.verify", return_value=("pass", "")):
            report = assign("", "do the step", executor=lambda t: calls.append(t) or "done it")
        assert report.ok and calls == ["do the step"]

    def test_executor_result_is_still_inspected(self):
        with patch("core.agents.verifier.verify", return_value=("fail", "nope")):
            report = assign("", "do the step", executor=lambda t: "Tool error (x): boom")
        assert not report.ok


class TestLedger:
    def test_every_attempt_is_written(self, ledger_in_tmp):
        import json
        with patch("core.agents.registry.load", return_value=_agent("a", "b")), \
             patch("core.agents.verifier.verify", return_value=("fail", "not done")):
            assign("Sage", "research brokers", source="mission:abc")
        lines = ledger_in_tmp.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2
        entries = [json.loads(line) for line in lines]
        assert [e["attempt"] for e in entries] == [1, 2]
        assert all(e["callsign"] == "Sage" for e in entries)
        assert all(e["source"] == "mission:abc" for e in entries)
