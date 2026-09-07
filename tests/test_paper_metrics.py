import json
import pytest
from pathlib import Path


def _write(path: Path, trades: list) -> None:
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(trades), encoding="utf-8")


def _trade(symbol, pnl, outcome):
    return {
        "symbol": symbol, "price": 100.0, "qty": 0.1,
        "timestamp": "2026-06-01T10:00:00", "pnl_pct": pnl, "outcome": outcome,
    }


class TestPaperMetricsCompute:
    def test_no_trades_file_returns_zeros(self, tmp_path, monkeypatch):
        from core.paper_metrics import PaperMetrics
        monkeypatch.setattr("core.paper_metrics._TRADES_PATH", tmp_path / "none.json")
        m = PaperMetrics().compute()
        assert m["total_completed"] == 0
        assert m["win_rate"] == 0.0
        assert m["gate_pass"] is False

    def test_open_trades_not_counted(self, tmp_path, monkeypatch):
        from core.paper_metrics import PaperMetrics
        p = tmp_path / "trades.json"
        _write(p, [_trade("SPY", None, "OPEN"), _trade("SPY", None, "OPEN")])
        monkeypatch.setattr("core.paper_metrics._TRADES_PATH", p)
        m = PaperMetrics().compute()
        assert m["total_completed"] == 0

    def test_all_wins(self, tmp_path, monkeypatch):
        from core.paper_metrics import PaperMetrics
        p = tmp_path / "trades.json"
        _write(p, [_trade("A", 5.0, "TP"), _trade("B", 8.0, "TP"), _trade("C", 3.0, "TP")])
        monkeypatch.setattr("core.paper_metrics._TRADES_PATH", p)
        m = PaperMetrics().compute()
        assert m["total_completed"] == 3
        assert m["win_rate"] == pytest.approx(100.0)
        assert m["profit_factor"] == 0.0   # no losses so profit_factor = 0 (undefined)

    def test_all_losses(self, tmp_path, monkeypatch):
        from core.paper_metrics import PaperMetrics
        p = tmp_path / "trades.json"
        _write(p, [_trade("A", -4.0, "SL"), _trade("B", -5.0, "SL")])
        monkeypatch.setattr("core.paper_metrics._TRADES_PATH", p)
        m = PaperMetrics().compute()
        assert m["win_rate"] == 0.0
        assert m["profit_factor"] == 0.0

    def test_mixed_win_rate(self, tmp_path, monkeypatch):
        from core.paper_metrics import PaperMetrics
        p = tmp_path / "trades.json"
        _write(p, [
            _trade("A", 12.0, "TP"),
            _trade("B", -5.0, "SL"),
            _trade("C", 8.0, "TP"),
            _trade("D", -5.0, "SL"),
        ])
        monkeypatch.setattr("core.paper_metrics._TRADES_PATH", p)
        m = PaperMetrics().compute()
        assert m["win_rate"] == pytest.approx(50.0)
        assert m["profit_factor"] == pytest.approx(20.0 / 10.0)

    def test_sharpe_zero_for_fewer_than_five_trades(self, tmp_path, monkeypatch):
        from core.paper_metrics import PaperMetrics
        p = tmp_path / "trades.json"
        _write(p, [_trade("A", 5.0, "TP"), _trade("B", -3.0, "SL")])
        monkeypatch.setattr("core.paper_metrics._TRADES_PATH", p)
        m = PaperMetrics().compute()
        assert m["sharpe"] == 0.0

    def test_sharpe_positive_for_consistent_wins(self, tmp_path, monkeypatch):
        from core.paper_metrics import PaperMetrics
        p = tmp_path / "trades.json"
        trades = [_trade("A", 5.0 + i * 0.1, "TP") for i in range(10)]
        _write(p, trades)
        monkeypatch.setattr("core.paper_metrics._TRADES_PATH", p)
        m = PaperMetrics().compute()
        assert m["sharpe"] > 0.0

    def test_gate_fails_due_to_drawdown(self, tmp_path, monkeypatch):
        from core.paper_metrics import PaperMetrics
        p = tmp_path / "trades.json"
        # 14 wins then 17 losses in sequence → ~58% drawdown, far above 15% limit
        trades = [_trade("A", 12.0, "TP")] * 14 + [_trade("B", -5.0, "SL")] * 17
        _write(p, trades)
        monkeypatch.setattr("core.paper_metrics._TRADES_PATH", p)
        m = PaperMetrics().compute()
        assert m["total_completed"] == 31
        assert m["max_drawdown"] > 15.0
        assert m["gate_pass"] is False

    def test_gate_passes_with_50pct_win_rate_and_2to1_rr(self, tmp_path, monkeypatch):
        from core.paper_metrics import PaperMetrics
        p = tmp_path / "trades.json"
        # 50% win rate (below old 52% floor) but 2:1 R:R → profit_factor 2.4, low drawdown
        trades = []
        for _ in range(15):
            trades.append(_trade("A", 12.0, "TP"))
            trades.append(_trade("B", -5.0, "SL"))
        _write(p, trades)
        monkeypatch.setattr("core.paper_metrics._TRADES_PATH", p)
        m = PaperMetrics().compute()
        assert m["total_completed"] == 30
        assert m["win_rate"] == pytest.approx(50.0)
        assert m["profit_factor"] == pytest.approx(2.4, rel=0.01)
        assert m["max_drawdown"] < 15.0
        assert m["gate_pass"] is True


class TestPaperMetricsGateSummary:
    def test_summary_is_cp1252_safe(self, tmp_path, monkeypatch):
        from core.paper_metrics import PaperMetrics
        monkeypatch.setattr("core.paper_metrics._TRADES_PATH", tmp_path / "none.json")
        summary = PaperMetrics().gate_summary()
        for ch in summary:
            assert ord(ch) < 0x2000 or 0x2013 <= ord(ch) <= 0x2014, \
                f"Non-cp1252 char: U+{ord(ch):04X} '{ch}'"

    def test_summary_contains_pass_or_not_yet(self, tmp_path, monkeypatch):
        from core.paper_metrics import PaperMetrics
        monkeypatch.setattr("core.paper_metrics._TRADES_PATH", tmp_path / "none.json")
        summary = PaperMetrics().gate_summary()
        assert "PASS" in summary.upper() or "NOT YET" in summary.upper()
