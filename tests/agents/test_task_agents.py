"""Herald, Chronos, Abacus and Forge -- the four tool-loop agents.

The point of each is a small tool set: its own tools, not the brain's ~380.
These tests pin the wiring and, above all, the safety gate -- an agent working
unattended must not be able to send, delete, or push.
"""
from unittest.mock import MagicMock, patch

import pytest

from core.agents.base_agent import BaseAgent
from core.agents.comms_agent import SEND_TOOLS, CommsAgent
from core.agents.dev_agent import DevAgent
from core.agents.finance_agent import FinanceAgent
from core.agents.registry import ROSTER, load, resolve
from core.agents.scheduler_agent import SchedulerAgent

_AGENTS = [CommsAgent, SchedulerAgent, FinanceAgent, DevAgent]


class TestWiring:
    @pytest.mark.parametrize("cls", _AGENTS)
    def test_is_a_base_agent(self, cls):
        assert isinstance(cls(), BaseAgent)

    @pytest.mark.parametrize("cls", _AGENTS)
    def test_every_schema_has_a_dispatch_entry_and_vice_versa(self, cls):
        schemas, dispatch = cls()._toolset()
        assert {s["name"] for s in schemas} == set(dispatch)

    @pytest.mark.parametrize("cls", _AGENTS)
    def test_every_dispatch_target_is_callable(self, cls):
        _, dispatch = cls()._toolset()
        assert all(callable(fn) for fn in dispatch.values())

    @pytest.mark.parametrize("cls", _AGENTS)
    def test_tool_set_stays_small(self, cls):
        """The whole point is a focused agent -- if this grows past ~20 the
        agent is turning back into the brain."""
        schemas, _ = cls()._toolset()
        assert 5 <= len(schemas) <= 20

    @pytest.mark.parametrize("callsign", ["Herald", "Chronos", "Abacus", "Forge"])
    def test_registered_in_the_roster(self, callsign):
        spec = resolve(callsign)
        assert spec is not None
        assert spec.tool_name in ROSTER
        assert spec.confirm_before, "each new agent declares a safety gate"


class TestSafetyGate:
    """confirm_before is enforced by REMOVING tools, not by prompt wording."""

    @pytest.mark.parametrize("cls,gated", [
        (CommsAgent, SEND_TOOLS),
        (SchedulerAgent, ("confirm_delete_event", "remove_schedule", "enable_focus_mode")),
        (FinanceAgent, ("send_invoice", "delete_invoice", "delete_budget")),
        (DevAgent, ("run_python", "git_add", "git_commit", "git_push")),
    ])
    def test_unattended_agent_loses_its_side_effecting_tools(self, cls, gated):
        open_schemas, open_dispatch = cls()._toolset()
        shut_schemas, shut_dispatch = cls(allow_side_effects=False)._toolset()
        for name in gated:
            assert name in open_dispatch, f"{name} should exist when attended"
            assert name not in shut_dispatch, f"{name} must be gone when unattended"
            assert name not in {s["name"] for s in shut_schemas}
        # Everything else survives -- the gate is narrow, not a lockout.
        assert set(shut_dispatch) == set(open_dispatch) - set(gated)

    def test_read_tools_survive_the_gate(self):
        _, dispatch = CommsAgent(allow_side_effects=False)._toolset()
        assert "list_messages" in dispatch
        assert "read_message" in dispatch

    def test_staging_survives_so_the_agent_can_still_draft(self):
        _, dispatch = CommsAgent(allow_side_effects=False)._toolset()
        assert "send_message" in dispatch      # stages only
        assert "confirm_send_message" not in dispatch   # actually sends

    @pytest.mark.parametrize("callsign", ["Herald", "Chronos", "Abacus", "Forge"])
    def test_registry_gate_matches_the_agent_module(self, callsign):
        """The spec's confirm_before and the agent's own constant must agree,
        or the gate would silently name tools that do not exist."""
        spec = resolve(callsign)
        _, dispatch = load(spec.tool_name, allow_side_effects=True)._toolset()
        for name in spec.confirm_before:
            assert name in dispatch, f"{callsign} gates '{name}' which it does not have"

    def test_load_passes_the_flag_through(self):
        agent = load("Herald", allow_side_effects=False)
        assert "send_telegram" not in agent._toolset()[1]

    def test_agents_without_a_gate_take_no_flag(self):
        """Sage has no confirm_before, so load() must not pass the argument."""
        with patch("core.agents.research_agent.ResearchAgent") as cls:
            load("Sage", allow_side_effects=False)
        cls.assert_called_once_with()


class TestSupervisorDerivesTheFlag:
    @pytest.fixture(autouse=True)
    def ledger_in_tmp(self, tmp_path, monkeypatch):
        monkeypatch.setattr("core.agents.ledger._LEDGER_PATH",
                            tmp_path / "runs.jsonl")

    @pytest.mark.parametrize("source,expected", [
        ("voice", True),
        ("callsign", True),
        ("delegate", True),
        ("mission:a1b2", False),
        ("task:c3d4", False),
    ])
    def test_only_mo_present_means_side_effects_allowed(self, source, expected):
        from core.agents.supervisor import assign
        with patch("core.telemetry.over_budget", return_value=(False, 0.0, 5.0)), \
             patch("core.agents.registry.load") as load_agent, \
             patch("core.agents.verifier.verify", return_value=("pass", "")):
            load_agent.return_value.run.return_value = "a real result"
            assign("Herald", "check the inbox", source=source)
        assert load_agent.call_args.kwargs["allow_side_effects"] is expected


class TestToolLoop:
    def test_a_tool_missing_from_dispatch_is_refused_not_guessed(self):
        from core.agents.tool_loop import _call
        out = _call({}, "confirm_send_message", {})
        assert "not available" in out
        assert "Do not retry" in out

    def test_a_raising_tool_becomes_a_readable_failure(self):
        from core.agents.tool_loop import _call
        out = _call({"boom": lambda: (_ for _ in ()).throw(ValueError("no auth"))},
                    "boom", {})
        assert out.startswith("Tool error (boom):")
        assert "no auth" in out

    def test_arguments_are_passed_through(self):
        from core.agents.tool_loop import _call
        assert _call({"echo": lambda x: f"got {x}"}, "echo", {"x": 7}) == "got 7"

    def test_a_failed_client_returns_an_error_the_inspector_will_reject(self):
        from core.agents.tool_loop import run_tool_loop
        with patch("anthropic.Anthropic", side_effect=RuntimeError("no key")):
            out = run_tool_loop("comms_agent", "sys", [], {}, "do it")
        assert out.startswith("Error:")

    def test_loop_stops_at_the_step_cap(self):
        from core.agents.tool_loop import run_tool_loop
        client = MagicMock()
        block = MagicMock()
        block.type = "tool_use"
        block.name = "echo"
        block.input = {}
        block.id = "t1"
        client.messages.create.return_value = MagicMock(
            content=[block], stop_reason="tool_use")
        with patch("anthropic.Anthropic", return_value=client):
            out = run_tool_loop("dev_agent", "sys", [], {"echo": lambda: "x"},
                                "loop forever", max_steps=3)
        assert client.messages.create.call_count == 3
        assert "stopped after 3 steps" in out
