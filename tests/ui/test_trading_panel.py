import json
import pytest


class TestTradingPanelConstruction:
    def test_widget_created(self, qapp):
        from ui.trading_panel import TradingPanel
        w = TradingPanel()
        assert w is not None
        w.close()

    def test_start_button_present(self, qapp):
        from ui.trading_panel import TradingPanel
        w = TradingPanel()
        assert w._start_btn is not None
        assert "START" in w._start_btn.text().upper()
        w.close()

    def test_stop_button_present(self, qapp):
        from ui.trading_panel import TradingPanel
        w = TradingPanel()
        assert w._stop_btn is not None
        assert "STOP" in w._stop_btn.text().upper()
        w.close()

    def test_backtest_button_present(self, qapp):
        from ui.trading_panel import TradingPanel
        w = TradingPanel()
        assert w._backtest_btn is not None
        assert "BACKTEST" in w._backtest_btn.text().upper()
        w.close()

    def test_signal_table_has_four_columns(self, qapp):
        from ui.trading_panel import TradingPanel
        w = TradingPanel()
        assert w._signal_table.columnCount() == 4
        w.close()


class TestTradingPanelSignals:
    def test_set_signals_populates_rows(self, qapp):
        from ui.trading_panel import TradingPanel
        w = TradingPanel()
        signals = [
            {"symbol": "NVDA", "direction": "BUY", "conviction": 88.0, "status": "Pending"},
            {"symbol": "AAPL", "direction": "HOLD", "conviction": 55.0, "status": "Watching"},
        ]
        w.set_signals(signals)
        assert w._signal_table.rowCount() == 2
        assert w._signal_table.item(0, 0).text() == "NVDA"
        assert w._signal_table.item(1, 0).text() == "AAPL"
        w.close()

    def test_set_signals_empty_clears_table(self, qapp):
        from ui.trading_panel import TradingPanel
        w = TradingPanel()
        w.set_signals([{"symbol": "SPY", "direction": "BUY", "conviction": 70.0, "status": "OK"}])
        w.set_signals([])
        assert w._signal_table.rowCount() == 0
        w.close()


class TestTradingPanelRefresh:
    def test_refresh_no_trades_file(self, qapp, tmp_path, monkeypatch):
        from ui.trading_panel import TradingPanel
        # Point _TRADES_PATH at a nonexistent file
        monkeypatch.setattr("ui.trading_panel._TRADES_PATH", tmp_path / "no_trades.json")
        w = TradingPanel()
        w.refresh()   # must not raise
        assert w._equity_points == []
        w.close()

    def test_refresh_with_trades_populates_log(self, qapp, tmp_path, monkeypatch):
        from ui.trading_panel import TradingPanel
        trades_file = tmp_path / "trades.json"
        trades_file.write_text(json.dumps([
            {"symbol": "NVDA", "side": "buy", "qty": 0.5, "price": 120.0,
             "timestamp": "2026-06-23T10:00:00", "signal": "test", "agent": "test",
             "sl_price": 114.0, "tp_price": 134.4, "id": "abc"},
        ]))
        monkeypatch.setattr("ui.trading_panel._TRADES_PATH", trades_file)
        w = TradingPanel()
        w.refresh()
        assert w._log_list.count() >= 1
        w.close()

    def test_refresh_with_malformed_file(self, qapp, tmp_path, monkeypatch):
        from ui.trading_panel import TradingPanel
        trades_file = tmp_path / "trades.json"
        trades_file.write_text("not valid json{{{{")
        monkeypatch.setattr("ui.trading_panel._TRADES_PATH", trades_file)
        w = TradingPanel()
        w.refresh()   # must not raise
        assert w._equity_points == []
        w.close()


class TestTradingPanelCallback:
    def test_set_callback_start(self, qapp):
        from ui.trading_panel import TradingPanel
        w = TradingPanel()
        called = []
        w.set_callback(on_start=lambda: called.append("start"), on_stop=None, on_backtest=None)
        w._start_btn.click()
        assert "start" in called
        w.close()
