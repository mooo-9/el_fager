import json
import time
import pytest
from unittest.mock import MagicMock


@pytest.fixture
def brain(monkeypatch):
    monkeypatch.setattr("anthropic.Anthropic", MagicMock)
    from core.brain import Brain
    return Brain({})


class TestLiveActivationDispatch:
    def test_first_confirm_returns_caution_message(self, brain, monkeypatch, tmp_path):
        monkeypatch.setattr("core.brain._LIVE_CONFIG_PATH", str(tmp_path / "cfg.json"))
        result = brain._try_agent_dispatch("confirm live trading")
        assert "CAUTION" in result
        assert "again" in result.lower() or "confirm" in result.lower()

    def test_first_confirm_sets_pending_true(self, brain, monkeypatch, tmp_path):
        monkeypatch.setattr("core.brain._LIVE_CONFIG_PATH", str(tmp_path / "cfg.json"))
        brain._try_agent_dispatch("confirm live trading")
        assert brain._live_pending is True

    def test_cancel_clears_pending_state(self, brain, monkeypatch, tmp_path):
        monkeypatch.setattr("core.brain._LIVE_CONFIG_PATH", str(tmp_path / "cfg.json"))
        brain._try_agent_dispatch("confirm live trading")
        result = brain._try_agent_dispatch("cancel live trading")
        assert brain._live_pending is False
        assert "cancel" in result.lower()

    def test_cancel_when_not_pending_returns_safely(self, brain, monkeypatch, tmp_path):
        monkeypatch.setattr("core.brain._LIVE_CONFIG_PATH", str(tmp_path / "cfg.json"))
        result = brain._try_agent_dispatch("cancel live trading")
        assert isinstance(result, str)
        assert brain._live_pending is False

    def test_second_confirm_timeout_returns_timeout_message(self, brain, monkeypatch, tmp_path):
        monkeypatch.setattr("core.brain._LIVE_CONFIG_PATH", str(tmp_path / "cfg.json"))
        brain._try_agent_dispatch("confirm live trading")
        brain._live_pending_ts = time.monotonic() - 65.0  # backdate 65 s -> timed out
        result = brain._try_agent_dispatch("confirm live trading")
        assert brain._live_pending is False
        assert "timed out" in result.lower() or "start over" in result.lower()

    def test_second_confirm_gate_not_passed_returns_gate_summary(self, brain, monkeypatch, tmp_path):
        monkeypatch.setattr("core.brain._LIVE_CONFIG_PATH", str(tmp_path / "cfg.json"))
        monkeypatch.setattr(
            "core.paper_metrics.PaperMetrics.compute",
            lambda self: {
                "total_completed": 5, "win_rate": 40.0, "sharpe": 0.2,
                "max_drawdown": 25.0, "profit_factor": 0.7, "gate_pass": False,
            },
        )
        monkeypatch.setattr("core.paper_metrics._TRADES_PATH", tmp_path / "none.json")
        brain._try_agent_dispatch("confirm live trading")
        result = brain._try_agent_dispatch("confirm live trading")
        assert "NOT YET" in result or "Paper trading gate check" in result
        assert brain._live_pending is False

    def test_second_confirm_gate_passes_writes_live_mode_to_config(self, brain, monkeypatch, tmp_path):
        cfg_path = tmp_path / "trading_config.json"
        monkeypatch.setattr("core.brain._LIVE_CONFIG_PATH", str(cfg_path))
        monkeypatch.setattr(
            "core.paper_metrics.PaperMetrics.compute",
            lambda self: {
                "total_completed": 35, "win_rate": 60.0, "sharpe": 1.5,
                "max_drawdown": 10.0, "profit_factor": 1.8, "gate_pass": True,
            },
        )
        brain._try_agent_dispatch("confirm live trading")
        brain._try_agent_dispatch("confirm live trading")
        written = json.loads(cfg_path.read_text())
        assert written["mode"] == "live"

    def test_second_confirm_gate_passes_returns_activation_message(self, brain, monkeypatch, tmp_path):
        cfg_path = tmp_path / "trading_config.json"
        monkeypatch.setattr("core.brain._LIVE_CONFIG_PATH", str(cfg_path))
        monkeypatch.setattr(
            "core.paper_metrics.PaperMetrics.compute",
            lambda self: {
                "total_completed": 35, "win_rate": 60.0, "sharpe": 1.5,
                "max_drawdown": 10.0, "profit_factor": 1.8, "gate_pass": True,
            },
        )
        brain._try_agent_dispatch("confirm live trading")
        result = brain._try_agent_dispatch("confirm live trading")
        assert "LIVE TRADING ACTIVATED" in result
        assert brain._live_pending is False

    def test_activation_message_is_cp1252_safe(self, brain, monkeypatch, tmp_path):
        cfg_path = tmp_path / "trading_config.json"
        monkeypatch.setattr("core.brain._LIVE_CONFIG_PATH", str(cfg_path))
        monkeypatch.setattr(
            "core.paper_metrics.PaperMetrics.compute",
            lambda self: {
                "total_completed": 35, "win_rate": 60.0, "sharpe": 1.5,
                "max_drawdown": 10.0, "profit_factor": 1.8, "gate_pass": True,
            },
        )
        brain._try_agent_dispatch("confirm live trading")
        result = brain._try_agent_dispatch("confirm live trading")
        for ch in result:
            assert ord(ch) < 0x2000 or 0x2013 <= ord(ch) <= 0x2014, \
                f"Non-cp1252 char U+{ord(ch):04X} in activation message"
