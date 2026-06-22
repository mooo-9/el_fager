"""
StocksAgent -- conviction-gated autonomous trading agent.
Routes to MarketAnalyst for signal scoring, StrategyEngine for regime weighting,
ExplainEngine for natural-language answers, and Alpaca for order execution.
"""
import json
import re
import threading
from pathlib import Path

from core.agents.base_agent import BaseAgent

_CONFIG_PATH = Path("data/trading_config.json")

_KNOWN_SYMBOLS = {
    "nvda", "aapl", "msft", "amzn", "googl", "meta", "tsla",
    "spy", "qqq", "btc", "eth", "nflx", "amd", "intc",
    "baba", "orcl", "crm", "avgo", "cost",
}

_EXPLAIN_TRIGGERS = [
    "why did you", "why did we", "explain", "how are we doing",
    "how am i doing", "portfolio performance", "trade history",
    "what happened", "my trading stats",
]


class StocksAgent(BaseAgent):
    @property
    def name(self) -> str:
        return "stocks"

    @property
    def description(self) -> str:
        return "Multi-strategy market analyst with conviction-gated autonomous trading."

    def run(self, task: str) -> str:
        control_result = self._handle_control_command(task)
        if control_result is not None:
            return control_result

        symbol = self._parse_symbol(task)
        task_lower = task.lower()

        is_explain = any(kw in task_lower for kw in _EXPLAIN_TRIGGERS)
        if is_explain:
            from core.agents.explain_engine import ExplainEngine
            return ExplainEngine().explain(task, symbol=symbol)

        if symbol:
            return self._analyze_and_decide(symbol)

        is_scan = any(kw in task_lower for kw in ["scan", "watchlist", "portfolio check"])
        if is_scan:
            return self._scan_watchlist()

        from core.agents.explain_engine import ExplainEngine
        return ExplainEngine().explain(task)

    # -- Symbol parsing --------------------------------------------------------

    def _parse_symbol(self, task: str) -> str | None:
        words = re.sub(r"[^\w\s]", " ", task).lower().split()
        for word in words:
            if word in _KNOWN_SYMBOLS:
                return word.upper()
        match = re.search(r"\b([A-Z]{2,5})\b", task)
        if match:
            return match.group(1)
        return None

    # -- Control commands ------------------------------------------------------

    def _handle_control_command(self, task: str) -> str | None:
        task_lower = task.lower()

        if any(kw in task_lower for kw in ["pause trading", "stop auto-trade", "stop auto trade"]):
            return self._set_paused(True)

        if any(kw in task_lower for kw in ["resume trading", "unpause trading", "start auto-trade"]):
            return self._set_paused(False)

        match = re.search(r"set (?:auto.?trade )?threshold to (\d+)%?", task_lower)
        if match:
            return self._set_threshold(int(match.group(1)))

        return None

    def _set_paused(self, paused: bool) -> str:
        cfg = self._load_config()
        cfg["auto_trade_paused"] = paused
        self._save_config(cfg)
        if paused:
            return "Autonomous trading paused. Monitoring continues but no orders will be placed."
        return "Autonomous trading resumed."

    def _set_threshold(self, threshold: int) -> str:
        if not 50 <= threshold <= 99:
            return f"Threshold must be between 50 and 99. Got {threshold}."
        cfg = self._load_config()
        cfg["auto_trade_threshold"] = threshold
        self._save_config(cfg)
        return (
            f"Auto-trade threshold set to {threshold}%. "
            f"Trades execute automatically at {threshold}% conviction or higher."
        )

    # -- Analysis + decision ---------------------------------------------------

    def _analyze_and_decide(self, symbol: str) -> str:
        from core.agents.market_analyst import MarketAnalyst
        from core.agents.strategy_engine import StrategyEngine

        analyst = MarketAnalyst()
        analysis = analyst.analyze(symbol)

        try:
            closes, _ = analyst._fetch_ohlcv(symbol)
            _, modifier = StrategyEngine().select_strategy(symbol, closes)
            adjusted = min(100.0, analysis.conviction * modifier)
        except Exception:
            adjusted = analysis.conviction

        summary = (
            f"{symbol}: {analysis.conviction:.0f}% conviction ({analysis.direction}) "
            f"[Tech {analysis.technical_score:.0f} | "
            f"Fund {analysis.fundamental_score:.0f} | "
            f"Sent {analysis.sentiment_score:.0f}]"
        )

        cfg = self._load_config()

        if cfg.get("auto_trade_paused", False):
            return f"{summary}\n\nTrading is paused -- no order placed."

        threshold = cfg.get("auto_trade_threshold", 85)
        delay = cfg.get("conviction_delay_seconds", 60)

        if analysis.direction != "BUY":
            return f"{summary}\n\nDirection is {analysis.direction}. No buy order placed."

        if adjusted >= threshold:
            trade_result = self._place_trade(symbol)
            return (
                f"{summary}\n\n"
                f"Conviction {adjusted:.0f}% >= threshold {threshold}%. "
                f"Auto-executing buy.\n{trade_result}"
            )

        if adjusted >= 60:
            t = threading.Timer(delay, self._place_trade, args=(symbol,))
            t.daemon = True
            t.start()
            return (
                f"{summary}\n\n"
                f"Conviction {adjusted:.0f}% -- scheduling buy in {delay}s "
                f"unless you say 'pause trading'."
            )

        return (
            f"{summary}\n\n"
            f"Conviction {adjusted:.0f}% below 60% -- holding off. "
            f"Confirm if you want to proceed."
        )

    # -- Order execution -------------------------------------------------------

    def _place_trade(self, symbol: str) -> str:
        import os
        import uuid
        from datetime import datetime
        from alpaca.trading.client import TradingClient
        from alpaca.trading.requests import (
            MarketOrderRequest,
            TakeProfitRequest,
            StopLossRequest,
        )
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.data.historical.stock import StockHistoricalDataClient
        from alpaca.data.requests import LatestStockQuoteRequest
        from alpaca.data.enums import DataFeed
        from core.risk_manager import (
            can_open_position,
            calc_position_size,
            get_stop_loss_price,
            get_take_profit_price,
        )

        cfg = self._load_config()
        paper = cfg.get("mode", "paper") == "paper"
        api_key = os.getenv("ALPACA_API_KEY", "")
        secret = os.getenv("ALPACA_SECRET_KEY", "")

        trading = TradingClient(api_key, secret, paper=paper)
        account = trading.get_account()
        portfolio_value = float(account.portfolio_value)
        positions = trading.get_all_positions()

        allowed, reason = can_open_position(len(positions))
        if not allowed:
            return f"Cannot open position: {reason}"

        data_client = StockHistoricalDataClient(api_key, secret)
        quote_req = LatestStockQuoteRequest(symbol_or_symbols=symbol)
        quote = data_client.get_stock_latest_quote(quote_req)
        current_price = float(quote[symbol].ask_price)

        qty = calc_position_size(portfolio_value, current_price)
        if qty < 0.001:
            return (
                f"Position size too small (qty={qty:.6f}). "
                f"Portfolio too small for {symbol} at ${current_price:.2f}."
            )

        sl_price = get_stop_loss_price(current_price)
        tp_price = get_take_profit_price(current_price)

        order_data = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
            order_class="bracket",
            take_profit=TakeProfitRequest(limit_price=tp_price),
            stop_loss=StopLossRequest(stop_price=sl_price),
        )
        order = trading.submit_order(order_data)

        trade = {
            "id": str(uuid.uuid4()),
            "symbol": symbol,
            "side": "buy",
            "qty": qty,
            "price": float(order.filled_avg_price or current_price),
            "timestamp": datetime.now().isoformat(),
            "signal": "stocks_agent_conviction",
            "sl_price": sl_price,
            "tp_price": tp_price,
            "agent": "stocks_agent",
        }
        path = Path("data/trades.json")
        trades = []
        if path.exists():
            try:
                trades = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                trades = []
        trades.append(trade)
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(trades, indent=2, ensure_ascii=False), encoding="utf-8")

        return (
            f"Bought {qty:.4f} {symbol} @ ~${current_price:.2f}. "
            f"SL: ${sl_price:.2f} | TP: ${tp_price:.2f}."
        )

    # -- Watchlist scan --------------------------------------------------------

    def _scan_watchlist(self) -> str:
        from core.agents.market_analyst import MarketAnalyst
        cfg = self._load_config()
        symbols = cfg.get("active_symbols", ["SPY", "QQQ", "AAPL", "NVDA", "MSFT"])
        analyst = MarketAnalyst()
        lines = []
        for symbol in symbols[:5]:
            try:
                r = analyst.analyze(symbol)
                lines.append(
                    f"{symbol}: {r.conviction:.0f}% ({r.direction}) "
                    f"[T:{r.technical_score:.0f} F:{r.fundamental_score:.0f} S:{r.sentiment_score:.0f}]"
                )
            except Exception as e:
                lines.append(f"{symbol}: analysis failed ({e})")
        return "Watchlist scan:\n" + "\n".join(lines)

    # -- Config helpers --------------------------------------------------------

    def _load_config(self) -> dict:
        if not _CONFIG_PATH.exists():
            return {}
        try:
            return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_config(self, cfg: dict) -> None:
        _CONFIG_PATH.parent.mkdir(exist_ok=True)
        _CONFIG_PATH.write_text(
            json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8"
        )
