"""Unit tests for core/trading_engine.py — the autonomous 15-minute loop.

All Alpaca/analyst/strategy calls are mocked; no network, no real orders.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

import core.trading_engine as te
from core.trading_engine import TradingEngine


def _analysis(conviction=80.0, direction="BUY", rationale="strong momentum"):
    a = MagicMock()
    a.conviction = conviction
    a.direction = direction
    a.rationale = rationale
    return a


def _account(portfolio_value=100_000.0):
    acct = MagicMock()
    acct.portfolio_value = str(portfolio_value)
    return acct


def _make_engine(speak=None):
    return TradingEngine(speak_fn=speak)


@pytest.fixture
def cycle_mocks():
    """Patch everything _run_cycle imports; yield a namespace of the mocks."""
    with patch("core.trade_tracker.TradeTracker") as tracker_cls, \
         patch("core.agents.market_analyst.MarketAnalyst") as analyst_cls, \
         patch("core.agents.strategy_engine.StrategyEngine") as strategy_cls, \
         patch("core.risk_manager.can_open_position", return_value=(True, "ok")) as can_open, \
         patch("core.risk_manager.calc_position_size", return_value=5) as calc_size, \
         patch("core.risk_manager.get_stop_loss_price", return_value=92.0) as sl, \
         patch("core.risk_manager.get_take_profit_price", return_value=115.0) as tp, \
         patch("core.risk_manager.is_daily_limit_hit", return_value=False) as limit_hit:
        analyst = analyst_cls.return_value
        analyst.analyze.return_value = _analysis()
        analyst._fetch_ohlcv.return_value = ([100.0, 101.0, 102.0], None)
        strategy = strategy_cls.return_value
        strategy.select_strategy.return_value = ("trend", 1.0)

        ns = MagicMock()
        ns.tracker_cls = tracker_cls
        ns.analyst = analyst
        ns.strategy = strategy
        ns.can_open = can_open
        ns.calc_size = calc_size
        ns.limit_hit = limit_hit
        yield ns


def _run(engine, cfg, positions=(), portfolio_value=100_000.0):
    client = MagicMock()
    client.get_account.return_value = _account(portfolio_value)
    client.get_all_positions.return_value = list(positions)
    with patch.object(engine, "_get_clients", return_value=(client, MagicMock())), \
         patch.object(engine, "_load_config", return_value=cfg), \
         patch.object(engine, "_place_buy") as place_buy:
        engine._run_cycle()
    return client, place_buy


_CFG = {"active_symbols": ["NVDA"], "auto_trade_threshold": 72, "mode": "paper"}


class TestRunCycle:
    def test_trade_tracker_synced_at_cycle_start(self, cycle_mocks):
        engine = _make_engine()
        _run(engine, _CFG)
        cycle_mocks.tracker_cls.return_value.sync.assert_called_once()

    def test_buys_when_conviction_meets_threshold(self, cycle_mocks):
        engine = _make_engine()
        cycle_mocks.analyst.analyze.return_value = _analysis(conviction=80.0)
        _, place_buy = _run(engine, _CFG)
        place_buy.assert_called_once()
        args = place_buy.call_args.args
        assert args[1] == "NVDA"          # symbol
        assert args[2] == 5               # qty
        assert args[5] == 80.0            # adjusted conviction

    def test_no_buy_below_threshold(self, cycle_mocks):
        engine = _make_engine()
        cycle_mocks.analyst.analyze.return_value = _analysis(conviction=60.0)
        _, place_buy = _run(engine, _CFG)
        place_buy.assert_not_called()

    def test_sell_direction_blocks_buy_even_at_high_conviction(self, cycle_mocks):
        engine = _make_engine()
        cycle_mocks.analyst.analyze.return_value = _analysis(conviction=95.0, direction="SELL")
        _, place_buy = _run(engine, _CFG)
        place_buy.assert_not_called()

    def test_hold_direction_does_not_block_buy(self, cycle_mocks):
        # Phase 7a decision: only SELL blocks; HOLD at high conviction may buy.
        engine = _make_engine()
        cycle_mocks.analyst.analyze.return_value = _analysis(conviction=80.0, direction="HOLD")
        _, place_buy = _run(engine, _CFG)
        place_buy.assert_called_once()

    def test_strategy_modifier_boosts_conviction(self, cycle_mocks):
        engine = _make_engine()
        cycle_mocks.analyst.analyze.return_value = _analysis(conviction=65.0)
        cycle_mocks.strategy.select_strategy.return_value = ("bull", 1.2)
        _, place_buy = _run(engine, _CFG)
        place_buy.assert_called_once()
        assert place_buy.call_args.args[5] == pytest.approx(78.0)

    def test_adjusted_conviction_capped_at_100(self, cycle_mocks):
        engine = _make_engine()
        cycle_mocks.analyst.analyze.return_value = _analysis(conviction=95.0)
        cycle_mocks.strategy.select_strategy.return_value = ("bull", 1.2)
        _, place_buy = _run(engine, _CFG)
        assert place_buy.call_args.args[5] == 100.0

    def test_strategy_failure_falls_back_to_raw_conviction(self, cycle_mocks):
        engine = _make_engine()
        cycle_mocks.analyst.analyze.return_value = _analysis(conviction=75.0)
        cycle_mocks.strategy.select_strategy.side_effect = RuntimeError("no regime data")
        _, place_buy = _run(engine, _CFG)
        place_buy.assert_called_once()
        assert place_buy.call_args.args[5] == 75.0

    def test_auto_trade_paused_skips_all_analysis(self, cycle_mocks):
        engine = _make_engine()
        cfg = dict(_CFG, auto_trade_paused=True)
        _, place_buy = _run(engine, cfg)
        place_buy.assert_not_called()
        cycle_mocks.analyst.analyze.assert_not_called()

    def test_held_symbol_is_skipped(self, cycle_mocks):
        engine = _make_engine()
        pos = MagicMock()
        pos.symbol = "NVDA"
        _, place_buy = _run(engine, _CFG, positions=[pos])
        place_buy.assert_not_called()

    def test_position_limit_blocks_buy(self, cycle_mocks):
        engine = _make_engine()
        cycle_mocks.can_open.return_value = (False, "Max positions reached (5)")
        _, place_buy = _run(engine, _CFG)
        place_buy.assert_not_called()

    def test_zero_position_size_skips_trade(self, cycle_mocks):
        engine = _make_engine()
        cycle_mocks.calc_size.return_value = 0
        _, place_buy = _run(engine, _CFG)
        place_buy.assert_not_called()

    def test_daily_loss_limit_stops_engine(self, cycle_mocks):
        spoken = []
        engine = _make_engine(speak=spoken.append)
        cycle_mocks.limit_hit.return_value = True
        _, place_buy = _run(engine, _CFG)
        place_buy.assert_not_called()
        assert engine._stop_event.is_set()
        assert any("loss limit" in s.lower() for s in spoken)

    def test_analysis_error_on_one_symbol_does_not_kill_cycle(self, cycle_mocks):
        engine = _make_engine()
        cfg = dict(_CFG, active_symbols=["SPY", "NVDA"])
        good = _analysis(conviction=80.0)
        cycle_mocks.analyst.analyze.side_effect = [RuntimeError("403"), good]
        _, place_buy = _run(engine, cfg)
        place_buy.assert_called_once()
        assert place_buy.call_args.args[1] == "NVDA"


class TestPlaceBuy:
    def test_trade_log_records_conviction_and_rationale(self, tmp_path, monkeypatch):
        monkeypatch.setattr(te, "_TRADES_PATH", tmp_path / "trades.json")
        engine = _make_engine()
        order = MagicMock()
        order.filled_avg_price = "100.50"
        order.id = "order-123"
        client = MagicMock()
        client.submit_order.return_value = order

        engine._place_buy(client, "NVDA", 5, 92.0, 115.0, 78.3, "bullish MACD cross")

        import json
        trades = json.loads((tmp_path / "trades.json").read_text(encoding="utf-8"))
        assert len(trades) == 1
        t = trades[0]
        assert t["symbol"] == "NVDA"
        assert t["conviction"] == 78.3
        assert t["rationale"] == "bullish MACD cross"
        assert t["signal"] == "conviction"
        assert t["sl_price"] == 92.0
        assert t["tp_price"] == 115.0
        assert t["alpaca_order_id"] == "order-123"

    def test_submits_bracket_order(self, tmp_path, monkeypatch):
        monkeypatch.setattr(te, "_TRADES_PATH", tmp_path / "trades.json")
        engine = _make_engine()
        order = MagicMock()
        order.filled_avg_price = "100.50"
        order.id = "order-123"
        client = MagicMock()
        client.submit_order.return_value = order

        engine._place_buy(client, "NVDA", 5, 92.0, 115.0, 78.3, "r")

        client.submit_order.assert_called_once()
        req = client.submit_order.call_args.args[0]
        assert req.symbol == "NVDA"
        assert req.qty == 5
        assert req.order_class == "bracket"
        assert float(req.take_profit.limit_price) == 115.0
        assert float(req.stop_loss.stop_price) == 92.0


    def test_unfilled_order_polls_then_falls_back_to_est_price(self, tmp_path, monkeypatch):
        """Regression: market orders have filled_avg_price=None at submit time;
        the trade log used to record price 0.0."""
        monkeypatch.setattr(te, "_TRADES_PATH", tmp_path / "trades.json")
        monkeypatch.setattr(te.time, "sleep", lambda s: None)
        engine = _make_engine()
        order = MagicMock()
        order.filled_avg_price = None
        order.id = "order-123"
        client = MagicMock()
        client.submit_order.return_value = order
        client.get_order_by_id.return_value = order  # never fills during poll

        engine._place_buy(client, "NVDA", 5, 92.0, 115.0, 78.3, "r",
                          est_price=101.25)

        import json
        t = json.loads((tmp_path / "trades.json").read_text(encoding="utf-8"))[0]
        assert t["price"] == 101.25
        assert t["price_estimated"] is True

    def test_late_fill_price_picked_up_by_poll(self, tmp_path, monkeypatch):
        monkeypatch.setattr(te, "_TRADES_PATH", tmp_path / "trades.json")
        monkeypatch.setattr(te.time, "sleep", lambda s: None)
        engine = _make_engine()
        order = MagicMock()
        order.filled_avg_price = None
        order.id = "order-123"
        filled = MagicMock()
        filled.filled_avg_price = "100.50"
        client = MagicMock()
        client.submit_order.return_value = order
        client.get_order_by_id.return_value = filled

        engine._place_buy(client, "NVDA", 5, 92.0, 115.0, 78.3, "r",
                          est_price=99.0)

        import json
        t = json.loads((tmp_path / "trades.json").read_text(encoding="utf-8"))[0]
        assert t["price"] == 100.50
        assert t["price_estimated"] is False


class TestMarketHours:
    def _with_now(self, engine, dt):
        fake = MagicMock(wraps=datetime)
        fake.now = MagicMock(return_value=dt)
        with patch.object(te, "datetime", fake):
            return engine._is_market_open()

    def test_open_during_weekday_session(self):
        engine = _make_engine()
        dt = datetime(2026, 7, 1, 11, 0, tzinfo=te._ET)  # Wednesday 11:00 ET
        assert self._with_now(engine, dt) is True

    def test_closed_before_open_bell(self):
        engine = _make_engine()
        dt = datetime(2026, 7, 1, 9, 0, tzinfo=te._ET)
        assert self._with_now(engine, dt) is False

    def test_closed_at_close_bell(self):
        engine = _make_engine()
        dt = datetime(2026, 7, 1, 16, 0, tzinfo=te._ET)
        assert self._with_now(engine, dt) is False

    def test_closed_on_weekend(self):
        engine = _make_engine()
        dt = datetime(2026, 7, 4, 11, 0, tzinfo=te._ET)  # Saturday
        assert self._with_now(engine, dt) is False


class TestLifecycle:
    def test_start_reports_mode_and_symbols(self):
        spoken = []
        engine = _make_engine(speak=spoken.append)
        with patch.object(engine, "_load_config", return_value=_CFG), \
             patch.object(te.threading, "Thread") as thread_cls:
            thread_cls.return_value.is_alive.return_value = True
            msg = engine.start()
        assert "paper mode" in msg
        assert "1 symbols" in msg
        assert spoken == [msg]

    def test_stop_when_not_running(self):
        engine = _make_engine()
        assert engine.stop() == "Trading engine is not running."
