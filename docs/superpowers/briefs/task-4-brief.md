# Task 4 Brief: StocksAgent

## Context
El Fager project at `C:\claude proj\el_fager`. Tasks 1-3 complete — 112 tests passing. You are implementing Task 4: StocksAgent, the orchestrator that ties MarketAnalyst, StrategyEngine, and ExplainEngine together with conviction-gated trading.

## Global Constraints
- Python 3.14 — no walrus operator
- DataFeed.IEX — ALL Alpaca bar/quote requests MUST include `feed=DataFeed.IEX`
- cp1252 safety — NO emojis, NO Arabic, NO U+2192 in any return string
- No new pip installs
- `python -m pytest` from `C:\claude proj\el_fager`; existing 112 tests must stay green
- Paper mode: config `mode: "paper"` enforced; never execute live trades

## Files to create
- `core/agents/stocks_agent.py`
- `tests/agents/test_stocks_agent.py`

## Interfaces consumed (all exist from prior tasks)
```python
# Task 1
from core.agents.market_analyst import MarketAnalyst, AnalysisResult
# Task 2
from core.agents.strategy_engine import StrategyEngine
# Task 3
from core.agents.explain_engine import ExplainEngine
# Existing
from core.agents.base_agent import BaseAgent
from core.risk_manager import can_open_position, calc_position_size, get_stop_loss_price, get_take_profit_price
```

## Key design decisions
- `_CONFIG_PATH = Path("data/trading_config.json")` — module-level variable, tests monkeypatch it
- StocksAgent.name == "stocks"
- Conviction thresholds read from config: `auto_trade_threshold` (default 85), `auto_trade_paused` (default False), `conviction_delay_seconds` (default 60)
- Direction "BUY" required for any trade; "SELL" or "HOLD" → no buy placed
- delayed trade (60-85% conviction) uses `threading.Timer` with daemon=True
- `_place_trade()` logs to `data/trades.json`

## Tests to write FIRST

```python
# tests/agents/test_stocks_agent.py
import json
from unittest.mock import patch, MagicMock
import core.agents.stocks_agent as sa
from core.agents.stocks_agent import StocksAgent
from core.agents.market_analyst import AnalysisResult


def _analysis(symbol="NVDA", conviction=75.0, direction="BUY"):
    return AnalysisResult(symbol, conviction, direction, 80.0, 70.0, 75.0, "test rationale")


class TestParseSymbol:
    def test_recognizes_nvda_lowercase(self):
        assert StocksAgent()._parse_symbol("analyze nvda for me") == "NVDA"

    def test_recognizes_uppercase_ticker_in_sentence(self):
        assert StocksAgent()._parse_symbol("What do you think about MSFT?") == "MSFT"

    def test_returns_none_when_no_symbol(self):
        assert StocksAgent()._parse_symbol("how are we doing overall?") is None

    def test_prefers_known_symbol_list_over_random_uppercase(self):
        result = StocksAgent()._parse_symbol("analyze aapl vs RANDOMCORP")
        assert result == "AAPL"


class TestHandleControlCommand:
    def test_pause_sets_config_true(self, tmp_path, monkeypatch):
        config_file = tmp_path / "trading_config.json"
        config_file.write_text(json.dumps({"auto_trade_paused": False}))
        monkeypatch.setattr(sa, "_CONFIG_PATH", config_file)
        result = StocksAgent()._handle_control_command("pause trading")
        assert result is not None
        assert "paused" in result.lower()
        assert json.loads(config_file.read_text())["auto_trade_paused"] is True

    def test_resume_sets_config_false(self, tmp_path, monkeypatch):
        config_file = tmp_path / "trading_config.json"
        config_file.write_text(json.dumps({"auto_trade_paused": True}))
        monkeypatch.setattr(sa, "_CONFIG_PATH", config_file)
        result = StocksAgent()._handle_control_command("resume trading")
        assert result is not None
        assert json.loads(config_file.read_text())["auto_trade_paused"] is False

    def test_set_threshold_to_90(self, tmp_path, monkeypatch):
        config_file = tmp_path / "trading_config.json"
        config_file.write_text(json.dumps({"auto_trade_threshold": 85}))
        monkeypatch.setattr(sa, "_CONFIG_PATH", config_file)
        result = StocksAgent()._handle_control_command("set auto-trade threshold to 90%")
        assert result is not None
        assert json.loads(config_file.read_text())["auto_trade_threshold"] == 90

    def test_set_threshold_rejects_out_of_range(self, tmp_path, monkeypatch):
        config_file = tmp_path / "trading_config.json"
        config_file.write_text(json.dumps({}))
        monkeypatch.setattr(sa, "_CONFIG_PATH", config_file)
        result = StocksAgent()._handle_control_command("set threshold to 110%")
        assert "must be between" in result.lower()

    def test_non_command_returns_none(self):
        assert StocksAgent()._handle_control_command("analyze NVDA") is None


class TestConvictionGating:
    def test_high_conviction_auto_executes(self, tmp_path, monkeypatch):
        config_file = tmp_path / "trading_config.json"
        config_file.write_text(json.dumps({
            "auto_trade_threshold": 85,
            "auto_trade_paused": False,
            "conviction_delay_seconds": 60,
        }))
        monkeypatch.setattr(sa, "_CONFIG_PATH", config_file)

        mock_analyst = MagicMock()
        mock_analyst.analyze.return_value = _analysis(conviction=90.0)
        mock_analyst._fetch_ohlcv.return_value = ([100.0] * 40, [1_000_000] * 40)

        agent = StocksAgent()
        with patch("core.agents.market_analyst.MarketAnalyst", return_value=mock_analyst):
            with patch("core.agents.strategy_engine.StrategyEngine") as MockSE:
                MockSE.return_value.select_strategy.return_value = ("momentum_swing", 1.0)
                with patch.object(agent, "_place_trade", return_value="Bought 0.01 NVDA @ $450.00.") as mock_trade:
                    result = agent._analyze_and_decide("NVDA")
                    mock_trade.assert_called_once_with("NVDA")
        assert "auto-executing" in result.lower() or "auto-exec" in result.lower()

    def test_paused_skips_trade_even_at_high_conviction(self, tmp_path, monkeypatch):
        config_file = tmp_path / "trading_config.json"
        config_file.write_text(json.dumps({"auto_trade_paused": True, "auto_trade_threshold": 85}))
        monkeypatch.setattr(sa, "_CONFIG_PATH", config_file)

        mock_analyst = MagicMock()
        mock_analyst.analyze.return_value = _analysis(conviction=95.0)
        mock_analyst._fetch_ohlcv.return_value = ([100.0] * 40, [1_000_000] * 40)

        agent = StocksAgent()
        with patch("core.agents.market_analyst.MarketAnalyst", return_value=mock_analyst):
            with patch("core.agents.strategy_engine.StrategyEngine") as MockSE:
                MockSE.return_value.select_strategy.return_value = ("momentum_swing", 1.0)
                with patch.object(agent, "_place_trade") as mock_trade:
                    result = agent._analyze_and_decide("NVDA")
                    mock_trade.assert_not_called()
        assert "paused" in result.lower()

    def test_low_conviction_asks_confirmation(self, tmp_path, monkeypatch):
        config_file = tmp_path / "trading_config.json"
        config_file.write_text(json.dumps({"auto_trade_threshold": 85, "auto_trade_paused": False}))
        monkeypatch.setattr(sa, "_CONFIG_PATH", config_file)

        mock_analyst = MagicMock()
        mock_analyst.analyze.return_value = _analysis(conviction=45.0)
        mock_analyst._fetch_ohlcv.return_value = ([100.0] * 40, [1_000_000] * 40)

        agent = StocksAgent()
        with patch("core.agents.market_analyst.MarketAnalyst", return_value=mock_analyst):
            with patch("core.agents.strategy_engine.StrategyEngine") as MockSE:
                MockSE.return_value.select_strategy.return_value = ("no_signal", 1.0)
                with patch.object(agent, "_place_trade") as mock_trade:
                    result = agent._analyze_and_decide("NVDA")
                    mock_trade.assert_not_called()
        assert "below 60" in result or "confirm" in result.lower()

    def test_sell_direction_skips_buy(self, tmp_path, monkeypatch):
        config_file = tmp_path / "trading_config.json"
        config_file.write_text(json.dumps({"auto_trade_threshold": 85, "auto_trade_paused": False}))
        monkeypatch.setattr(sa, "_CONFIG_PATH", config_file)

        mock_analyst = MagicMock()
        mock_analyst.analyze.return_value = _analysis(conviction=90.0, direction="SELL")
        mock_analyst._fetch_ohlcv.return_value = ([100.0] * 40, [1_000_000] * 40)

        agent = StocksAgent()
        with patch("core.agents.market_analyst.MarketAnalyst", return_value=mock_analyst):
            with patch("core.agents.strategy_engine.StrategyEngine") as MockSE:
                MockSE.return_value.select_strategy.return_value = ("no_signal", 1.0)
                with patch.object(agent, "_place_trade") as mock_trade:
                    result = agent._analyze_and_decide("NVDA")
                    mock_trade.assert_not_called()
        assert "SELL" in result or "sell" in result.lower()


class TestBaseAgentContract:
    def test_name_is_stocks(self):
        assert StocksAgent().name == "stocks"

    def test_description_is_non_empty_string(self):
        assert isinstance(StocksAgent().description, str)
        assert len(StocksAgent().description) > 0
```

## Implementation

```python
# core/agents/stocks_agent.py
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
        trades: list = []
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
        lines: list[str] = []
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
```

## Important note on mocking in tests
The tests mock `MarketAnalyst` and `StrategyEngine` by patching them at their SOURCE modules:
- `patch("core.agents.market_analyst.MarketAnalyst", return_value=mock_analyst)`
- `patch("core.agents.strategy_engine.StrategyEngine")`

This works because `_analyze_and_decide` imports them with `from core.agents.market_analyst import MarketAnalyst` at call time, and Python resolves the name from the source module.

## Steps
1. Write tests file first
2. Run `python -m pytest tests/agents/test_stocks_agent.py -v` — confirm ModuleNotFoundError
3. Write implementation file
4. Run `python -m pytest tests/agents/test_stocks_agent.py -v` — all 13 pass
5. Run `python -m pytest --tb=short -q` — full suite green (112 + 13 = 125 expected)
6. Commit: `git add core/agents/stocks_agent.py tests/agents/test_stocks_agent.py && git commit -m "feat: add StocksAgent with conviction-gated autonomous trading"`

## Report
Write to: `C:\claude proj\el_fager\docs\superpowers\briefs\task-4-report.md`
Include: Status, commit hash, test count, concerns.
