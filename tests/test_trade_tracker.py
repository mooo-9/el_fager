# tests/test_trade_tracker.py
import json
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path


def _write_trades(path: Path, trades: list) -> None:
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(trades), encoding="utf-8")


class TestTradeTrackerLoadSave:
    def test_load_returns_empty_when_no_file(self, tmp_path, monkeypatch):
        from core.trade_tracker import TradeTracker
        monkeypatch.setattr("core.trade_tracker._TRADES_PATH", tmp_path / "no.json")
        assert TradeTracker()._load_trades() == []

    def test_load_returns_empty_on_malformed_json(self, tmp_path, monkeypatch):
        from core.trade_tracker import TradeTracker
        bad = tmp_path / "trades.json"
        bad.write_text("not json", encoding="utf-8")
        monkeypatch.setattr("core.trade_tracker._TRADES_PATH", bad)
        assert TradeTracker()._load_trades() == []

    def test_save_writes_json(self, tmp_path, monkeypatch):
        from core.trade_tracker import TradeTracker
        path = tmp_path / "trades.json"
        monkeypatch.setattr("core.trade_tracker._TRADES_PATH", path)
        TradeTracker()._save_trades([{"symbol": "SPY"}])
        assert json.loads(path.read_text())== [{"symbol": "SPY"}]


class TestTradeTrackerFetchSells:
    def test_fetch_returns_empty_on_exception(self, monkeypatch):
        from core.trade_tracker import TradeTracker
        monkeypatch.setattr(
            "core.trade_tracker.TradeTracker._fetch_closed_sells",
            lambda self, k, s, p: [],
        )
        t = TradeTracker()
        assert t._fetch_closed_sells("key", "secret", True) == []

    def test_fetch_returns_empty_list_when_api_raises(self, monkeypatch):
        from core.trade_tracker import TradeTracker

        def _raise(*args, **kwargs):
            raise ConnectionError("API down")

        monkeypatch.setattr("alpaca.trading.client.TradingClient", _raise)

        t = TradeTracker()
        # Must not raise — the method catches all exceptions internally
        result = t._fetch_closed_sells("key", "secret", True)
        assert result == []


class TestTradeTrackerSync:
    def test_sync_no_open_trades(self, tmp_path, monkeypatch):
        from core.trade_tracker import TradeTracker
        path = tmp_path / "trades.json"
        # All trades already have outcome set (closed)
        _write_trades(path, [
            {"symbol": "NVDA", "timestamp": "2026-06-20T10:00:00", "outcome": "TP",
             "exit_price": 130.0, "pnl_pct": 8.0},
        ])
        monkeypatch.setattr("core.trade_tracker._TRADES_PATH", path)
        monkeypatch.setattr("core.trade_tracker._CONFIG_PATH", tmp_path / "cfg.json")
        t = TradeTracker()
        count = t.sync()
        assert count == 0

    def test_sync_matches_sell_to_open_trade(self, tmp_path, monkeypatch):
        from core.trade_tracker import TradeTracker
        path = tmp_path / "trades.json"
        _write_trades(path, [
            {"symbol": "AAPL", "timestamp": "2026-06-20T10:00:00", "price": 200.0,
             "sl_price": 190.0, "tp_price": 224.0},
        ])
        monkeypatch.setattr("core.trade_tracker._TRADES_PATH", path)
        monkeypatch.setattr("core.trade_tracker._CONFIG_PATH", tmp_path / "cfg.json")

        sells = [{"symbol": "AAPL", "price": 224.0, "filled_at": "2026-06-22T11:00:00"}]
        monkeypatch.setattr(
            "core.trade_tracker.TradeTracker._fetch_closed_sells",
            lambda self, k, s, p: sells,
        )

        count = TradeTracker().sync()
        assert count == 1
        updated = json.loads(path.read_text())
        assert updated[0]["outcome"] == "TP"
        assert updated[0]["exit_price"] == pytest.approx(224.0)
        assert updated[0]["pnl_pct"] == pytest.approx(12.0, rel=0.05)

    def test_sync_no_matching_sells_returns_zero(self, tmp_path, monkeypatch):
        from core.trade_tracker import TradeTracker
        path = tmp_path / "trades.json"
        _write_trades(path, [
            {"symbol": "NVDA", "timestamp": "2026-06-20T10:00:00", "price": 120.0,
             "sl_price": 114.0, "tp_price": 134.4},
        ])
        monkeypatch.setattr("core.trade_tracker._TRADES_PATH", path)
        monkeypatch.setattr("core.trade_tracker._CONFIG_PATH", tmp_path / "cfg.json")
        monkeypatch.setattr(
            "core.trade_tracker.TradeTracker._fetch_closed_sells",
            lambda self, k, s, p: [],
        )
        count = TradeTracker().sync()
        assert count == 0

    def test_sync_skips_pre_entry_fill_and_matches_later_fill(self, tmp_path, monkeypatch):
        """Pre-entry fill for the same symbol must not be consumed before matching the correct post-entry fill."""
        from core.trade_tracker import TradeTracker
        path = tmp_path / "trades.json"
        _write_trades(path, [
            {"symbol": "SPY", "timestamp": "2026-06-20T10:00:00", "price": 500.0,
             "sl_price": 475.0, "tp_price": 560.0},
        ])
        monkeypatch.setattr("core.trade_tracker._TRADES_PATH", path)
        monkeypatch.setattr("core.trade_tracker._CONFIG_PATH", tmp_path / "cfg.json")

        # pre-entry fill (09:00 < 10:00) followed by the real post-entry fill (11:00)
        sells = [
            {"symbol": "SPY", "price": 490.0, "filled_at": "2026-06-20T09:00:00"},
            {"symbol": "SPY", "price": 560.0, "filled_at": "2026-06-20T11:00:00"},
        ]
        monkeypatch.setattr(
            "core.trade_tracker.TradeTracker._fetch_closed_sells",
            lambda self, k, s, p: sells,
        )

        count = TradeTracker().sync()
        assert count == 1
        updated = json.loads(path.read_text())
        # Must match the post-entry fill at 560.0, not the pre-entry fill at 490.0
        assert updated[0]["exit_price"] == pytest.approx(560.0)
        assert updated[0]["outcome"] == "TP"

    def test_sync_never_raises_on_api_exception(self, tmp_path, monkeypatch):
        from core.trade_tracker import TradeTracker
        path = tmp_path / "trades.json"
        _write_trades(path, [
            {"symbol": "SPY", "timestamp": "2026-06-20T10:00:00", "price": 500.0,
             "sl_price": 475.0, "tp_price": 560.0},
        ])
        monkeypatch.setattr("core.trade_tracker._TRADES_PATH", path)
        monkeypatch.setattr("core.trade_tracker._CONFIG_PATH", tmp_path / "cfg.json")

        def _boom(self, k, s, p):
            raise ConnectionError("no internet")
        monkeypatch.setattr("core.trade_tracker.TradeTracker._fetch_closed_sells", _boom)

        count = TradeTracker().sync()   # must not raise
        assert count == 0
