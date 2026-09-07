import json
import pytest
from unittest.mock import patch
from pathlib import Path
import tools.backtest_tool as tool
from core.backtester import SymbolResult

_SAMPLE = SymbolResult(
    symbol="SPY",
    total_return_pct=34.2,
    benchmark_return_pct=28.1,
    win_rate_pct=61.0,
    avg_gain_pct=12.3,
    avg_loss_pct=6.1,
    max_drawdown_pct=14.2,
    sharpe_ratio=1.4,
    total_trades=23,
    winning_trades=14,
    losing_trades=9,
)


def test_run_backtest_no_keys(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "your_alpaca_key_here")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "your_secret_here")
    assert "not configured" in tool.run_backtest("SPY")


def test_run_backtest_success(monkeypatch, tmp_path):
    monkeypatch.setenv("ALPACA_API_KEY", "PKTEST123")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "SKTEST456")
    monkeypatch.setattr(tool, "_RESULTS_PATH", tmp_path / "results.json")
    with patch("core.backtester.run_backtest", return_value=_SAMPLE):
        result = tool.run_backtest("SPY")
    assert "34.2" in result
    assert "28.1" in result
    assert "outperforms" in result
    assert "61" in result


def test_get_backtest_results_no_file(monkeypatch, tmp_path):
    monkeypatch.setattr(tool, "_RESULTS_PATH", tmp_path / "nonexistent.json")
    assert "No backtest results" in tool.get_backtest_results()


def test_compare_to_buyhold_outperforms(monkeypatch, tmp_path):
    p = tmp_path / "results.json"
    p.write_text(json.dumps({
        "SPY": {
            "total_return_pct": 34.2, "benchmark_return_pct": 28.1,
            "win_rate_pct": 61.0, "avg_gain_pct": 12.3, "avg_loss_pct": 6.1,
            "max_drawdown_pct": 14.2, "sharpe_ratio": 1.4,
            "total_trades": 23, "winning_trades": 14, "losing_trades": 9,
        }
    }), encoding="utf-8")
    monkeypatch.setattr(tool, "_RESULTS_PATH", p)
    result = tool.compare_to_buyhold("SPY")
    assert "outperforms" in result
    assert "6.1" in result


def test_compare_to_buyhold_missing_symbol(monkeypatch, tmp_path):
    p = tmp_path / "results.json"
    p.write_text(json.dumps({"SPY": {}}), encoding="utf-8")
    monkeypatch.setattr(tool, "_RESULTS_PATH", p)
    result = tool.compare_to_buyhold("TSLA")
    assert "TSLA" in result
    assert "run_backtest" in result
