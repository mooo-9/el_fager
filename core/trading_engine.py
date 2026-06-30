"""
TradingEngine — autonomous 15-minute trading loop.
Fetches OHLCV from Alpaca, computes signals, applies risk rules, executes bracket orders.
"""
import json
import logging
import os
import threading
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

_TRADES_PATH = Path("data/trades.json")
_CONFIG_PATH = Path("data/trading_config.json")
_ET = ZoneInfo("America/New_York")


class TradingEngine:
    def __init__(self, speak_fn: Callable[[str], None] | None = None):
        self._speak = speak_fn or (lambda s: None)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._day_open_value: float | None = None
        self._last_day: date | None = None

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def start(self) -> str:
        if self._thread and self._thread.is_alive():
            return "Trading engine is already running."
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="TradingEngine"
        )
        self._thread.start()
        cfg = self._load_config()
        mode = cfg.get("mode", "paper")
        symbols = cfg.get("active_symbols", [])
        msg = f"Trading engine started in {mode} mode. Monitoring {len(symbols)} symbols."
        self._speak(msg)
        return msg

    def stop(self) -> str:
        if not (self._thread and self._thread.is_alive()):
            return "Trading engine is not running."
        self._stop_event.set()
        msg = "Trading engine stopped. Open positions remain active with bracket orders."
        self._speak(msg)
        return msg

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    # ── Config ─────────────────────────────────────────────────────────────────

    def _load_config(self) -> dict:
        if not _CONFIG_PATH.exists():
            return {}
        try:
            return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}

    # ── Alpaca clients ─────────────────────────────────────────────────────────

    def _get_clients(self):
        from alpaca.trading.client import TradingClient
        from alpaca.data.historical.stock import StockHistoricalDataClient
        api_key = os.getenv("ALPACA_API_KEY", "")
        secret = os.getenv("ALPACA_SECRET_KEY", "")
        cfg = self._load_config()
        paper = cfg.get("mode", "paper") == "paper"
        trading = TradingClient(api_key, secret, paper=paper)
        data = StockHistoricalDataClient(api_key, secret)
        return trading, data

    # ── Market hours ───────────────────────────────────────────────────────────

    def _is_market_open(self) -> bool:
        now = datetime.now(_ET)
        if now.weekday() >= 5:
            return False
        open_t = now.replace(hour=9, minute=30, second=0, microsecond=0)
        close_t = now.replace(hour=16, minute=0, second=0, microsecond=0)
        return open_t <= now < close_t

    # ── Sleep prevention ───────────────────────────────────────────────────────

    _ES_CONTINUOUS      = 0x80000000
    _ES_SYSTEM_REQUIRED = 0x00000001

    def _prevent_sleep(self) -> None:
        try:
            import ctypes
            ctypes.windll.kernel32.SetThreadExecutionState(
                self._ES_CONTINUOUS | self._ES_SYSTEM_REQUIRED
            )
        except Exception:
            pass

    def _allow_sleep(self) -> None:
        try:
            import ctypes
            ctypes.windll.kernel32.SetThreadExecutionState(self._ES_CONTINUOUS)
        except Exception:
            pass

    # ── Trade logging ──────────────────────────────────────────────────────────

    def _log_trade(self, trade: dict) -> None:
        trades = []
        if _TRADES_PATH.exists():
            try:
                trades = json.loads(_TRADES_PATH.read_text(encoding="utf-8"))
            except Exception:
                trades = []
        trades.append(trade)
        _TRADES_PATH.parent.mkdir(exist_ok=True)
        _TRADES_PATH.write_text(
            json.dumps(trades, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    # ── Order execution ────────────────────────────────────────────────────────

    def _place_buy(
        self,
        trading_client,
        symbol: str,
        qty: float,
        sl_price: float,
        tp_price: float,
        conviction: float,
        rationale: str,
    ) -> None:
        from alpaca.trading.requests import (
            MarketOrderRequest,
            TakeProfitRequest,
            StopLossRequest,
        )
        from alpaca.trading.enums import OrderSide, TimeInForce

        order_data = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
            order_class="bracket",
            take_profit=TakeProfitRequest(limit_price=tp_price),
            stop_loss=StopLossRequest(stop_price=sl_price),
        )
        order = trading_client.submit_order(order_data)
        filled_price = float(order.filled_avg_price or 0)

        trade = {
            "id": str(uuid.uuid4()),
            "symbol": symbol,
            "side": "buy",
            "qty": qty,
            "price": filled_price,
            "timestamp": datetime.now().isoformat(),
            "signal": "conviction",
            "conviction": round(conviction, 1),
            "rationale": rationale,
            "sl_price": sl_price,
            "tp_price": tp_price,
            "alpaca_order_id": str(order.id),
        }
        self._log_trade(trade)

        announcement = (
            f"Bought {qty:.2f} shares of {symbol} at ${filled_price:.2f}. "
            f"Conviction {conviction:.0f}%, stop-loss at ${sl_price:.2f}."
        )
        self._speak(announcement)
        logger.info(f"[Trading] {announcement}")

    # ── Main cycle ─────────────────────────────────────────────────────────────

    def _run_cycle(self) -> None:
        from core.agents.market_analyst import MarketAnalyst
        from core.agents.strategy_engine import StrategyEngine
        from core.risk_manager import (
            can_open_position,
            calc_position_size,
            get_stop_loss_price,
            get_take_profit_price,
            is_daily_limit_hit,
        )
        from core.trade_tracker import TradeTracker
        TradeTracker().sync()

        trading_client, _ = self._get_clients()
        account = trading_client.get_account()
        portfolio_value = float(account.portfolio_value)

        if self._day_open_value is None:
            self._day_open_value = portfolio_value

        if is_daily_limit_hit(portfolio_value, self._day_open_value):
            msg = "Daily loss limit reached. Trading paused until tomorrow."
            self._speak(msg)
            logger.warning(f"[Trading] {msg}")
            self._stop_event.set()
            return

        positions = trading_client.get_all_positions()
        open_count = len(positions)
        held_symbols = {p.symbol for p in positions}

        cfg = self._load_config()
        symbols = cfg.get("active_symbols", [])

        if cfg.get("auto_trade_paused", False):
            return

        threshold = cfg.get("auto_trade_threshold", 72)
        analyst = MarketAnalyst()
        strategy = StrategyEngine()

        for symbol in symbols:
            if self._stop_event.is_set():
                break
            if symbol in held_symbols:
                continue

            try:
                analysis = analyst.analyze(symbol)
                closes, _ = analyst._fetch_ohlcv(symbol)

                try:
                    _, modifier = strategy.select_strategy(symbol, closes)
                    adjusted = min(100.0, analysis.conviction * modifier)
                except Exception:
                    adjusted = analysis.conviction

                if analysis.direction == "SELL" or adjusted < threshold:
                    continue

                allowed, _ = can_open_position(open_count)
                if not allowed:
                    continue

                current_price = closes[-1]
                qty = calc_position_size(portfolio_value, current_price)
                if qty < 1:
                    continue

                sl_price = get_stop_loss_price(current_price)
                tp_price = get_take_profit_price(current_price)

                self._place_buy(
                    trading_client, symbol, qty,
                    sl_price, tp_price,
                    adjusted, analysis.rationale,
                )
                open_count += 1
                held_symbols.add(symbol)

            except Exception as e:
                logger.warning(f"[Trading] Cycle error for {symbol}: {e}")

    # ── Loop ───────────────────────────────────────────────────────────────────

    def _loop(self) -> None:
        _awake = False
        while not self._stop_event.is_set():
            today = datetime.now().date()
            if self._last_day != today:
                self._day_open_value = None
                self._last_day = today

            market_open = self._is_market_open()

            if market_open and not _awake:
                self._prevent_sleep()
                _awake = True
            elif not market_open and _awake:
                self._allow_sleep()
                _awake = False

            if market_open:
                try:
                    self._run_cycle()
                except Exception as e:
                    logger.error(f"[Trading] Unhandled cycle error: {e}")

            cfg = self._load_config()
            interval = cfg.get("cycle_interval_minutes", 15) * 60
            self._stop_event.wait(timeout=interval)

        self._allow_sleep()
