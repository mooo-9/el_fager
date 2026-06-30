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

    # ── Price data ─────────────────────────────────────────────────────────────

    def _fetch_closes(self, data_client, symbol: str) -> list[float]:
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame
        from alpaca.data.enums import DataFeed
        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Hour,
            start=datetime.now(timezone.utc) - timedelta(days=10),
            limit=100,
            feed=DataFeed.IEX,
        )
        bars = data_client.get_stock_bars(request)
        df = bars.df
        if hasattr(df.index, "levels"):  # MultiIndex when multiple symbols passed
            df = df.loc[symbol]
        return df["close"].tolist()

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

    # ── Claude consultation ────────────────────────────────────────────────────

    def _consult_claude(
        self,
        symbol: str,
        closes: list[float],
        rsi_val: float,
        macd_hist: float,
        headlines: list[str],
        open_count: int,
        max_pos: int,
    ) -> str:
        import anthropic
        client = anthropic.Anthropic()
        candles = " | ".join(f"{p:.2f}" for p in closes[-20:])
        prompt = (
            f"Trading signal decision for {symbol}.\n"
            f"Price: ${closes[-1]:.2f} | RSI: {rsi_val:.1f} | MACD histogram: {macd_hist:.4f}\n"
            f"Last 20 hourly closes: {candles}\n"
            f"Open positions: {open_count}/{max_pos}\n"
            f"News: {'; '.join(headlines) if headlines else 'none available'}\n\n"
            "Reply with exactly one word on line 1 (BUY, SELL, or HOLD), "
            "then one sentence of reasoning on line 2 (max 15 words)."
        )
        try:
            resp = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=80,
                messages=[{"role": "user", "content": prompt}],
            )
            return resp.content[0].text.strip()
        except Exception as e:
            logger.warning(f"Claude consultation failed for {symbol}: {e}")
            return "HOLD"

    # ── Order execution ────────────────────────────────────────────────────────

    def _place_buy(
        self,
        trading_client,
        symbol: str,
        qty: float,
        sl_price: float,
        tp_price: float,
        rsi_val: float,
        macd_hist: float,
        signal: str,
        claude_reason: str | None,
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
            "signal": signal,
            "rsi": round(rsi_val, 2),
            "macd_histogram": round(macd_hist, 4),
            "sl_price": sl_price,
            "tp_price": tp_price,
            "claude_reason": claude_reason,
            "alpaca_order_id": str(order.id),
        }
        self._log_trade(trade)

        announcement = (
            f"Bought {qty:.2f} shares of {symbol} at ${filled_price:.2f}. "
            f"RSI {rsi_val:.0f}, stop-loss at ${sl_price:.2f}."
        )
        self._speak(announcement)
        logger.info(f"[Trading] {announcement}")

    # ── Main cycle ─────────────────────────────────────────────────────────────

    def _run_cycle(self) -> None:
        from core.signals import rsi, macd, classify_signal, SignalStrength
        from core.risk_manager import (
            can_open_position,
            calc_position_size,
            get_stop_loss_price,
            get_take_profit_price,
            is_daily_limit_hit,
        )
        from core.trade_tracker import TradeTracker
        TradeTracker().sync()

        trading_client, data_client = self._get_clients()
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
        max_pos = cfg.get("max_open_positions", 5)

        for symbol in symbols:
            if self._stop_event.is_set():
                break
            if symbol in held_symbols:
                continue

            try:
                closes = self._fetch_closes(data_client, symbol)
                if len(closes) < 40:
                    continue

                rsi_val = rsi(closes)
                macd_result = macd(closes)
                signal = classify_signal(closes, rsi_val, macd_result)

                if signal == SignalStrength.HOLD:
                    continue

                claude_reason: str | None = None

                if signal in (SignalStrength.AMBIGUOUS_BUY, SignalStrength.AMBIGUOUS_SELL):
                    headlines: list[str] = []
                    try:
                        from tools.stocks_tool import get_stock_news
                        raw = get_stock_news(symbol)
                        headlines = [
                            ln.strip()
                            for ln in raw.split("\n")
                            if ln.strip() and not ln.startswith("No news")
                        ][:3]
                    except Exception:
                        pass

                    decision = self._consult_claude(
                        symbol, closes, rsi_val or 50.0,
                        macd_result.histogram if macd_result else 0.0,
                        headlines, open_count, max_pos,
                    )
                    claude_reason = decision
                    first_word = decision.split()[0].upper() if decision else "HOLD"
                    if first_word == "BUY":
                        signal = SignalStrength.STRONG_BUY
                    elif first_word == "SELL":
                        signal = SignalStrength.STRONG_SELL
                    else:
                        continue

                if signal == SignalStrength.STRONG_BUY:
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
                        rsi_val or 50.0,
                        macd_result.histogram if macd_result else 0.0,
                        signal, claude_reason,
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
