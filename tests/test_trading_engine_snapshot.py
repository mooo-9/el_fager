import json
import pytest


class TestWriteStatusSnapshot:
    def test_writes_expected_json_shape(self, tmp_path, monkeypatch):
        from core.trading_engine import TradingEngine
        path = tmp_path / "trading_status.json"
        monkeypatch.setattr("core.trading_engine._STATUS_PATH", path)

        positions = [{"symbol": "AAPL", "qty": 1.0, "avg_entry_price": 150.0,
                      "unrealized_pl": 5.0, "unrealized_plpc": 3.3}]
        signals = [{"symbol": "NVDA", "direction": "BUY", "conviction": 80.0, "status": "EXECUTED"}]

        TradingEngine()._write_status_snapshot(10500.0, 200.0, positions, signals)

        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["portfolio_value"] == 10500.0
        assert data["cash"] == 200.0
        assert data["positions"] == positions
        assert data["signals"] == signals
        assert "updated_at" in data

    def test_creates_data_directory_if_missing(self, tmp_path, monkeypatch):
        from core.trading_engine import TradingEngine
        path = tmp_path / "nested" / "trading_status.json"
        monkeypatch.setattr("core.trading_engine._STATUS_PATH", path)

        TradingEngine()._write_status_snapshot(1000.0, 0.0, [], [])

        assert path.exists()
