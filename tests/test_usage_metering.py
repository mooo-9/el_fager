"""Tests for brain API metering, usage_report tool, and the budget alert."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import json
from unittest.mock import MagicMock, patch

import pytest

import core.telemetry as tel
import tools.usage_tool as ut


@pytest.fixture(autouse=True)
def isolated_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(tel, "_TELEMETRY_DIR", tmp_path / "telemetry")
    yield tmp_path


def _make_brain():
    from core.brain import Brain
    return Brain(profile={})


def _end_turn_response(text="ok"):
    block = MagicMock()
    block.type = "text"
    block.text = text
    response = MagicMock()
    response.stop_reason = "end_turn"
    response.content = [block]
    response.usage = MagicMock(
        input_tokens=1000, output_tokens=200,
        cache_creation_input_tokens=0, cache_read_input_tokens=0,
    )
    return response


class TestBrainMetering:
    def test_chat_records_telemetry(self):
        brain = _make_brain()
        with patch.object(brain.client.messages, "create",
                          return_value=_end_turn_response()):
            brain.chat("hello")
        s = tel.summarize(days=1)
        assert s["requests"] == 1
        assert s["by_source"]["chat"]["requests"] == 1
        assert s["cost_usd"] > 0

    def test_telemetry_failure_does_not_break_chat(self):
        brain = _make_brain()
        with patch.object(brain.client.messages, "create",
                          return_value=_end_turn_response("still fine")), \
             patch("core.telemetry.record_api_usage",
                   side_effect=RuntimeError("disk full")):
            result = brain.chat("hello")
        assert result == "still fine"

    def test_usage_report_tool_dispatches(self):
        brain = _make_brain()
        out = brain._dispatch_tool("usage_report", {"days": 1})
        assert "No API usage" in out or "API calls" in out


class TestUsageReport:
    def test_empty(self):
        assert "No API usage recorded" in ut.usage_report(days=1)

    def test_report_contains_cost_and_breakdown(self):
        tel.record_api_usage("chat", "claude-opus-4-8", MagicMock(
            input_tokens=100_000, output_tokens=20_000,
            cache_creation_input_tokens=0, cache_read_input_tokens=0,
        ), 1500.0)
        out = ut.usage_report(days=1)
        assert "$" in out
        assert "chat" in out
        assert "1 API calls" in out

    def test_week_wording(self):
        assert "last 7 days" in ut.usage_report(days=7).lower()


class TestBudgetAlert:
    def _engine(self, tmp_path, monkeypatch):
        import core.proactive as pa
        from core.proactive import ProactiveEngine
        monkeypatch.setattr(pa, "_STATE_FILE", tmp_path / "state.json")
        monkeypatch.chdir(tmp_path)
        e = ProactiveEngine(speak_fn=None)
        e._deliver = MagicMock()
        return e

    def test_over_budget_warns(self, tmp_path, monkeypatch):
        engine = self._engine(tmp_path, monkeypatch)
        with patch("core.telemetry.cost_today", return_value=9.99):
            engine._check_api_budget()
        engine._deliver.assert_called_once()
        assert "$9.99" in engine._deliver.call_args.args[0]

    def test_under_budget_silent(self, tmp_path, monkeypatch):
        engine = self._engine(tmp_path, monkeypatch)
        with patch("core.telemetry.cost_today", return_value=0.42):
            engine._check_api_budget()
        engine._deliver.assert_not_called()

    def test_custom_budget_from_settings(self, tmp_path, monkeypatch):
        engine = self._engine(tmp_path, monkeypatch)
        (tmp_path / "data").mkdir()
        (tmp_path / "data" / "settings.json").write_text(
            json.dumps({"api_daily_budget_usd": 1.0}), encoding="utf-8")
        with patch("core.telemetry.cost_today", return_value=2.0):
            engine._check_api_budget()
        engine._deliver.assert_called_once()

    def test_zero_budget_disables(self, tmp_path, monkeypatch):
        engine = self._engine(tmp_path, monkeypatch)
        (tmp_path / "data").mkdir()
        (tmp_path / "data" / "settings.json").write_text(
            json.dumps({"api_daily_budget_usd": 0}), encoding="utf-8")
        with patch("core.telemetry.cost_today", return_value=99.0):
            engine._check_api_budget()
        engine._deliver.assert_not_called()
