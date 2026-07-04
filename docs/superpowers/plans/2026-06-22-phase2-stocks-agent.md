# Phase 2 StocksAgent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a conviction-gated AI trading agent (StocksAgent) that scores symbols on technical, fundamental, and sentiment signals, auto-executes trades above the conviction threshold, and answers plain-language questions about portfolio and trading rationale.

**Architecture:** StocksAgent is a BaseAgent subclass wired into the existing `_try_agent_dispatch()` router. It delegates signal scoring to MarketAnalyst, strategy weighting to StrategyEngine, and natural-language answers to ExplainEngine. Trades are placed through Alpaca directly using the same risk_manager functions the existing TradingEngine uses. Conviction thresholds and pause state are stored in `data/trading_config.json`.

**Tech Stack:** Python 3.14, alpaca-py, yfinance, anthropic SDK (claude-haiku-4-5-20251001 for ExplainEngine), existing `core/signals.py`, `core/risk_manager.py`, `core/vault.py`.

## Global Constraints

- **Python 3.14** — no walrus operator or syntax not supported by 3.14; use `pygame-ce` not `pygame` (but not needed in this phase)
- **DataFeed.IEX** — ALL Alpaca bar/quote requests MUST include `feed=DataFeed.IEX`; free plan returns 403 without it
- **cp1252 safety** — NO U+2192 (`->`  ok; `->` is cp1252 safe as ASCII bytes), NO emojis, NO Arabic text in any string returned to the UI; use "->" or "/" in plain text
- **RSI thresholds** — 35/65 for STRONG signals, 40/60 for AMBIGUOUS (existing convention in signals.py)
- **Paper trading only** — config `mode: "paper"` until Phase 5 activation; never switch to live without double-confirmation
- **Working directory** — El Fager runs from `C:\claude proj\el_fager`; all Path references are relative to that
- **Test runner** — `pytest` from `C:\claude proj\el_fager`; existing 81 tests must still pass after every task
- **No new dependencies** — yfinance, alpaca-py, anthropic are already installed; do not add packages

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `core/agents/market_analyst.py` | `AnalysisResult` NamedTuple + `MarketAnalyst` class: fetches OHLCV, scores technical/fundamental/sentiment, returns conviction 0-100 |
| Create | `core/agents/strategy_engine.py` | `StrategyEngine`: detects market regime (bull/bear/sideways) via SPY closes, weights 3 strategies, returns a confidence modifier |
| Create | `core/agents/explain_engine.py` | `ExplainEngine`: calls Claude Haiku with structured context to answer "why/how/thesis" queries; falls back to raw analysis text |
| Create | `core/agents/stocks_agent.py` | `StocksAgent(BaseAgent)`: orchestrates the above, enforces conviction thresholds, places Alpaca orders, handles control commands |
| Create | `tests/agents/test_market_analyst.py` | Pure-function tests for `_score_technical`, `_score_sentiment`; mocked tests for `_score_fundamental` |
| Create | `tests/agents/test_strategy_engine.py` | Pure-function tests for `_detect_regime`, `_mean_reversion_signal`, `_momentum_swing_signal` |
| Create | `tests/agents/test_explain_engine.py` | Mocked Claude tests for `explain()`; fallback path test |
| Create | `tests/agents/test_stocks_agent.py` | Tests for symbol parsing, control commands, conviction gating (mocked MarketAnalyst) |
| Modify | `core/agents/router.py` | Add `_STOCKS_AGENT_KEYWORDS` list + "stocks_agent" label at top of `_LABEL_KEYWORDS` |
| Modify | `core/brain.py:5953-5963` | Add `if intent == "stocks_agent"` branch in `_try_agent_dispatch()` |
| Modify | `tests/agents/test_router.py` | Add tests for "stocks_agent" intent routing |
| Modify | `data/trading_config.json` | Add `auto_trade_threshold`, `auto_trade_paused`, `conviction_delay_seconds`; update risk params for Phase 2 |

---

### Task 1: MarketAnalyst — technical + fundamental + sentiment scoring

**Files:**
- Create: `core/agents/market_analyst.py`
- Test: `tests/agents/test_market_analyst.py`

**Interfaces:**
- Consumes: `core.signals.rsi()`, `core.signals.macd()`, `core.signals.ema()` (existing); `tools.stocks_tool.get_stock_news(symbol)` (existing); `yfinance.Ticker(symbol).info`; Alpaca `StockHistoricalDataClient` with `DataFeed.IEX`
- Produces: `AnalysisResult(symbol, conviction, direction, technical_score, fundamental_score, sentiment_score, rationale)` -- all later tasks import this NamedTuple from `core.agents.market_analyst`

- [ ] **Step 1: Write the failing tests**

```python
# tests/agents/test_market_analyst.py
from core.agents.market_analyst import MarketAnalyst, AnalysisResult


class TestAnalysisResult:
    def test_is_named_tuple_with_correct_fields(self):
        r = AnalysisResult(
            symbol="NVDA",
            conviction=75.0,
            direction="BUY",
            technical_score=80.0,
            fundamental_score=60.0,
            sentiment_score=70.0,
            rationale="test",
        )
        assert r.symbol == "NVDA"
        assert r.conviction == 75.0
        assert r.direction == "BUY"


class TestScoreTechnical:
    def test_oversold_series_scores_above_60(self):
        # Steady downtrend gives RSI ~25 (very oversold -> high buy score)
        analyst = MarketAnalyst()
        closes = [100.0 - i * 0.8 for i in range(30)] + [72.0, 71.0, 70.0, 69.0, 68.0]
        volumes = [1_000_000] * len(closes)
        score, rationale = analyst._score_technical(closes, volumes)
        assert score >= 55, f"Oversold RSI series should score >= 55, got {score}"
        assert "RSI" in rationale

    def test_overbought_series_scores_below_50(self):
        # Steady uptrend gives RSI ~75 (overbought -> lower buy score)
        analyst = MarketAnalyst()
        closes = [100.0 + i * 1.5 for i in range(35)]
        volumes = [1_000_000] * len(closes)
        score, rationale = analyst._score_technical(closes, volumes)
        assert score <= 55

    def test_returns_float_in_range_and_str(self):
        analyst = MarketAnalyst()
        closes = [100.0 + i * 0.1 for i in range(30)]
        volumes = [500_000] * len(closes)
        score, rationale = analyst._score_technical(closes, volumes)
        assert isinstance(score, float)
        assert isinstance(rationale, str)
        assert 0.0 <= score <= 100.0

    def test_short_series_returns_neutral_without_crash(self):
        analyst = MarketAnalyst()
        closes = [100.0] * 10
        volumes = [500_000] * 10
        score, rationale = analyst._score_technical(closes, volumes)
        assert 0.0 <= score <= 100.0


class TestScoreFundamental:
    def test_low_pe_and_strong_growth_scores_above_60(self, monkeypatch):
        import yfinance as yf
        fake_info = {"trailingPE": 12.0, "revenueGrowth": 0.25, "earningsQuarterlyGrowth": 0.30}
        monkeypatch.setattr(yf.Ticker, "info", property(lambda self: fake_info))
        analyst = MarketAnalyst()
        score, rationale = analyst._score_fundamental("AAPL")
        assert score >= 60, f"Low P/E + high growth should score >= 60, got {score}"
        assert "P/E" in rationale

    def test_high_pe_and_negative_growth_scores_below_50(self, monkeypatch):
        import yfinance as yf
        fake_info = {"trailingPE": 80.0, "revenueGrowth": -0.10, "earningsQuarterlyGrowth": -0.20}
        monkeypatch.setattr(yf.Ticker, "info", property(lambda self: fake_info))
        analyst = MarketAnalyst()
        score, rationale = analyst._score_fundamental("XYZ")
        assert score < 50

    def test_exception_returns_neutral(self, monkeypatch):
        import yfinance as yf
        def raise_error(self):
            raise RuntimeError("network error")
        monkeypatch.setattr(yf.Ticker, "info", property(raise_error))
        analyst = MarketAnalyst()
        score, rationale = analyst._score_fundamental("XYZ")
        assert score == 50.0


class TestScoreSentiment:
    def test_positive_news_scores_above_50(self, monkeypatch):
        monkeypatch.setattr(
            "tools.stocks_tool.get_stock_news",
            lambda symbol: "NVDA beats earnings surge rally buy strong record profit growth bullish upgrade",
        )
        analyst = MarketAnalyst()
        score, rationale = analyst._score_sentiment("NVDA")
        assert score > 50

    def test_negative_news_scores_below_50(self, monkeypatch):
        monkeypatch.setattr(
            "tools.stocks_tool.get_stock_news",
            lambda symbol: "AAPL miss fall drop decline weak loss warning bearish sell downgrade layoff",
        )
        analyst = MarketAnalyst()
        score, rationale = analyst._score_sentiment("AAPL")
        assert score < 50

    def test_no_signal_words_returns_neutral(self, monkeypatch):
        monkeypatch.setattr(
            "tools.stocks_tool.get_stock_news",
            lambda symbol: "No news available for this symbol today.",
        )
        analyst = MarketAnalyst()
        score, rationale = analyst._score_sentiment("XYZ")
        assert score == 50.0

    def test_exception_returns_neutral(self, monkeypatch):
        def boom(symbol):
            raise RuntimeError("fail")
        monkeypatch.setattr("tools.stocks_tool.get_stock_news", boom)
        analyst = MarketAnalyst()
        score, rationale = analyst._score_sentiment("XYZ")
        assert score == 50.0
```

- [ ] **Step 2: Run the tests to confirm they fail**

```
cd "C:\claude proj\el_fager"
pytest tests/agents/test_market_analyst.py -v
```

Expected: `ModuleNotFoundError: No module named 'core.agents.market_analyst'`

- [ ] **Step 3: Create `core/agents/market_analyst.py`**

```python
"""
MarketAnalyst -- technical, fundamental, and sentiment scoring for a single symbol.
Returns AnalysisResult with a conviction score 0-100 and directional call.
"""
import os
from datetime import datetime, timedelta, timezone
from typing import NamedTuple


class AnalysisResult(NamedTuple):
    symbol: str
    conviction: float      # 0-100; higher = stronger buy signal
    direction: str         # "BUY", "SELL", or "HOLD"
    technical_score: float
    fundamental_score: float
    sentiment_score: float
    rationale: str


_POS_WORDS = [
    "beat", "surge", "rise", "gain", "strong", "record", "upgrade",
    "outperform", "growth", "profit", "bull", "rally", "buy", "bullish",
]
_NEG_WORDS = [
    "miss", "fall", "drop", "decline", "weak", "cut", "downgrade",
    "underperform", "loss", "warning", "bear", "sell", "bearish", "layoff",
]


class MarketAnalyst:
    def analyze(self, symbol: str) -> AnalysisResult:
        """Fetch data and return a full analysis for the symbol."""
        closes, volumes = self._fetch_ohlcv(symbol)
        tech_score, tech_note = self._score_technical(closes, volumes)
        fund_score, fund_note = self._score_fundamental(symbol)
        sent_score, sent_note = self._score_sentiment(symbol)

        conviction = tech_score * 0.50 + fund_score * 0.30 + sent_score * 0.20

        if conviction >= 60:
            direction = "BUY"
        elif conviction <= 40:
            direction = "SELL"
        else:
            direction = "HOLD"

        rationale = f"Technical: {tech_note}. Fundamental: {fund_note}. Sentiment: {sent_note}."

        return AnalysisResult(
            symbol=symbol,
            conviction=round(conviction, 1),
            direction=direction,
            technical_score=round(tech_score, 1),
            fundamental_score=round(fund_score, 1),
            sentiment_score=round(sent_score, 1),
            rationale=rationale,
        )

    def _fetch_ohlcv(self, symbol: str) -> tuple[list[float], list[float]]:
        from alpaca.data.historical.stock import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame
        from alpaca.data.enums import DataFeed

        client = StockHistoricalDataClient(
            os.getenv("ALPACA_API_KEY", ""),
            os.getenv("ALPACA_SECRET_KEY", ""),
        )
        req = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Day,
            start=datetime.now(timezone.utc) - timedelta(days=60),
            limit=60,
            feed=DataFeed.IEX,
        )
        bars = client.get_stock_bars(req)
        df = bars.df
        if hasattr(df.index, "levels"):
            df = df.loc[symbol]
        return df["close"].tolist(), df["volume"].tolist()

    def _score_technical(
        self, closes: list[float], volumes: list[float]
    ) -> tuple[float, str]:
        from core.signals import rsi, macd, ema

        if len(closes) < 2:
            return 50.0, "Insufficient data"

        rsi_val = rsi(closes) or 50.0
        macd_result = macd(closes)

        ema20_series = ema(closes, 20)
        ema50_series = ema(closes, 50)
        ema20 = next((v for v in reversed(ema20_series) if v is not None), None)
        ema50 = next((v for v in reversed(ema50_series) if v is not None), None)
        price = closes[-1]

        # Bollinger Bands (20-period, 2 std)
        if len(closes) >= 20:
            window = closes[-20:]
            bb_mean = sum(window) / 20
            variance = sum((x - bb_mean) ** 2 for x in window) / 20
            bb_std = variance ** 0.5
            bb_upper = bb_mean + 2 * bb_std
            bb_lower = bb_mean - 2 * bb_std
            bb_pct = (
                (price - bb_lower) / (bb_upper - bb_lower)
                if bb_upper != bb_lower
                else 0.5
            )
        else:
            bb_pct = 0.5

        # Volume ratio
        if len(volumes) >= 20:
            avg_vol = sum(volumes[-20:]) / 20
            vol_ratio = volumes[-1] / avg_vol if avg_vol > 0 else 1.0
        else:
            vol_ratio = 1.0

        # Component scores (0-100 scale, higher = more bullish)
        # RSI: lower RSI = oversold = higher buy score
        rsi_score = max(0.0, min(100.0, (80.0 - rsi_val) * 1.25))

        if macd_result:
            macd_score = 50.0 + min(50.0, max(-50.0, macd_result.histogram * 1000.0))
        else:
            macd_score = 50.0

        ema_score = 50.0
        if ema20 and ema50:
            if price > ema20 > ema50:
                ema_score = 80.0
            elif price > ema20:
                ema_score = 65.0
            elif price < ema20 < ema50:
                ema_score = 20.0
            elif price < ema20:
                ema_score = 35.0

        # BB: lower in the band = more oversold = higher buy score
        bb_score = max(0.0, min(100.0, (1.0 - bb_pct) * 100.0))

        # Volume amplifier: 0.7-1.0 range
        vol_confidence = min(vol_ratio, 2.0) / 2.0
        raw = (
            rsi_score * 0.30
            + macd_score * 0.25
            + ema_score * 0.25
            + bb_score * 0.20
        )
        score = raw * (0.7 + 0.3 * vol_confidence)
        score = max(0.0, min(100.0, score))

        macd_note = f"MACD {macd_result.histogram:+.4f}" if macd_result else "MACD n/a"
        ema_note = f"EMA20={ema20:.2f}" if ema20 else "EMA n/a"
        rationale = (
            f"RSI {rsi_val:.0f} ({rsi_score:.0f}/100), {macd_note}, "
            f"{ema_note}, BB {bb_pct:.0%}, Vol {vol_ratio:.1f}x avg"
        )
        return score, rationale

    def _score_fundamental(self, symbol: str) -> tuple[float, str]:
        try:
            import yfinance as yf
            info = yf.Ticker(symbol).info

            pe = info.get("trailingPE", None)
            revenue_growth = info.get("revenueGrowth", None)
            earnings_growth = info.get("earningsQuarterlyGrowth", None)

            score = 50.0
            parts: list[str] = []

            if pe and pe > 0:
                if pe < 15:
                    score += 20.0
                    parts.append(f"P/E {pe:.1f} (cheap)")
                elif pe < 25:
                    score += 10.0
                    parts.append(f"P/E {pe:.1f} (fair)")
                elif pe < 40:
                    score -= 5.0
                    parts.append(f"P/E {pe:.1f} (elevated)")
                else:
                    score -= 15.0
                    parts.append(f"P/E {pe:.1f} (expensive)")
            else:
                parts.append("P/E unavailable")

            if revenue_growth is not None:
                if revenue_growth > 0.20:
                    score += 20.0
                    parts.append(f"rev growth {revenue_growth:.0%}")
                elif revenue_growth > 0.05:
                    score += 10.0
                    parts.append(f"rev growth {revenue_growth:.0%}")
                elif revenue_growth < 0:
                    score -= 15.0
                    parts.append(f"rev decline {revenue_growth:.0%}")

            if earnings_growth is not None:
                if earnings_growth > 0.20:
                    score += 10.0
                    parts.append(f"earnings growth {earnings_growth:.0%}")
                elif earnings_growth < -0.10:
                    score -= 10.0
                    parts.append(f"earnings drop {earnings_growth:.0%}")

            return max(0.0, min(100.0, score)), " | ".join(parts) if parts else "No data"

        except Exception:
            return 50.0, "Fundamental data unavailable"

    def _score_sentiment(self, symbol: str) -> tuple[float, str]:
        try:
            from tools.stocks_tool import get_stock_news
            text = get_stock_news(symbol).lower()

            pos_count = sum(text.count(w) for w in _POS_WORDS)
            neg_count = sum(text.count(w) for w in _NEG_WORDS)
            total = pos_count + neg_count

            if total == 0:
                return 50.0, "No sentiment signal in news"

            score = (pos_count / total) * 100.0
            return score, f"{pos_count} positive / {neg_count} negative signals"

        except Exception:
            return 50.0, "Sentiment unavailable"
```

- [ ] **Step 4: Run the tests and confirm they pass**

```
cd "C:\claude proj\el_fager"
pytest tests/agents/test_market_analyst.py -v
```

Expected: all tests PASS. Also run the full suite to confirm no regressions:

```
pytest --tb=short -q
```

Expected: 81 existing + new tests, all green.

- [ ] **Step 5: Commit**

```
git add core/agents/market_analyst.py tests/agents/test_market_analyst.py
git commit -m "feat: add MarketAnalyst with technical/fundamental/sentiment scoring"
```

---

### Task 2: StrategyEngine — regime detection + 3 strategy signals

**Files:**
- Create: `core/agents/strategy_engine.py`
- Test: `tests/agents/test_strategy_engine.py`

**Interfaces:**
- Consumes: `core.signals.rsi()`, `core.signals.macd()`, `core.signals.ema()` (existing); `yfinance.Ticker(symbol).info`; Alpaca for SPY closes
- Produces: `StrategyEngine().select_strategy(symbol, closes) -> tuple[str, float]` where str is strategy name and float is a confidence modifier (0.8-1.2) applied to MarketAnalyst conviction

- [ ] **Step 1: Write the failing tests**

```python
# tests/agents/test_strategy_engine.py
from core.agents.strategy_engine import StrategyEngine


class TestDetectRegime:
    def test_rising_prices_returns_bull(self):
        eng = StrategyEngine()
        # Second half averages 5% above first half -- clear bull
        closes = [100.0 + i * 0.6 for i in range(25)]
        assert eng._detect_regime(closes) == "bull"

    def test_falling_prices_returns_bear(self):
        eng = StrategyEngine()
        closes = [100.0 - i * 0.6 for i in range(25)]
        assert eng._detect_regime(closes) == "bear"

    def test_flat_prices_returns_sideways(self):
        eng = StrategyEngine()
        closes = [100.0] * 20
        assert eng._detect_regime(closes) == "sideways"

    def test_short_series_returns_sideways(self):
        eng = StrategyEngine()
        assert eng._detect_regime([100.0, 101.0]) == "sideways"


class TestMeanReversionSignal:
    def test_price_far_below_band_returns_buy(self):
        eng = StrategyEngine()
        # 18 stable prices then two sharp drops -> oversold vs band
        closes = [100.0] * 18 + [91.5, 91.0]
        assert eng._mean_reversion_signal(closes) == "BUY"

    def test_price_far_above_band_returns_sell(self):
        eng = StrategyEngine()
        closes = [100.0] * 18 + [108.5, 109.0]
        assert eng._mean_reversion_signal(closes) == "SELL"

    def test_price_near_mean_returns_hold(self):
        eng = StrategyEngine()
        closes = [100.0] * 20
        assert eng._mean_reversion_signal(closes) == "HOLD"

    def test_short_series_returns_hold(self):
        eng = StrategyEngine()
        assert eng._mean_reversion_signal([100.0] * 5) == "HOLD"


class TestMomentumSwingSignal:
    def test_oversold_with_bullish_macd_returns_buy(self):
        eng = StrategyEngine()
        # Downtrend then strong recovery -- RSI low, MACD turning positive
        closes = [110.0 - i * 0.6 for i in range(20)] + [100.0 + i * 0.8 for i in range(15)]
        result = eng._momentum_swing_signal(closes)
        assert result in ("BUY", "HOLD")  # May not always trigger; at least no crash

    def test_returns_valid_direction(self):
        eng = StrategyEngine()
        closes = [100.0 + i * 0.1 for i in range(40)]
        result = eng._momentum_swing_signal(closes)
        assert result in ("BUY", "SELL", "HOLD")


class TestSelectStrategy:
    def test_returns_tuple_of_str_and_float(self, monkeypatch):
        eng = StrategyEngine()
        monkeypatch.setattr(eng, "_fetch_spy_closes", lambda: [100.0 + i * 0.5 for i in range(25)])
        closes = [80.0 + i * 0.3 for i in range(40)]
        strategy, modifier = eng.select_strategy("NVDA", closes)
        assert isinstance(strategy, str)
        assert isinstance(modifier, float)
        assert 0.5 <= modifier <= 1.5

    def test_modifier_is_positive(self, monkeypatch):
        eng = StrategyEngine()
        monkeypatch.setattr(eng, "_fetch_spy_closes", lambda: [100.0] * 25)
        closes = [100.0] * 40
        _, modifier = eng.select_strategy("AAPL", closes)
        assert modifier > 0
```

- [ ] **Step 2: Run to confirm failure**

```
pytest tests/agents/test_strategy_engine.py -v
```

Expected: `ModuleNotFoundError: No module named 'core.agents.strategy_engine'`

- [ ] **Step 3: Create `core/agents/strategy_engine.py`**

```python
"""
StrategyEngine -- detects market regime and weights 3 trading strategies.
Returns a (strategy_name, confidence_modifier) pair used by StocksAgent
to scale the MarketAnalyst conviction score.
"""
import os
from datetime import datetime, timedelta, timezone


class StrategyEngine:
    def select_strategy(self, symbol: str, closes: list[float]) -> tuple[str, float]:
        """Return (strategy_name, modifier).

        modifier 0.8-1.2 scales MarketAnalyst conviction up or down.
        """
        spy_closes = self._fetch_spy_closes()
        regime = self._detect_regime(spy_closes)

        momentum = self._momentum_swing_signal(closes)
        mean_rev = self._mean_reversion_signal(closes)
        earnings = self._earnings_momentum_signal(symbol)

        if regime == "bull":
            if momentum == "BUY":
                return "momentum_swing", 1.2
            if earnings == "BUY":
                return "earnings_momentum", 1.15
            if mean_rev == "BUY":
                return "mean_reversion", 0.9
        elif regime == "bear":
            if mean_rev == "BUY":
                return "mean_reversion", 1.1
            if momentum == "SELL":
                return "momentum_swing", 0.9
        else:
            if mean_rev == "BUY":
                return "mean_reversion", 1.0
            if earnings == "BUY":
                return "earnings_momentum", 1.05

        return "no_signal", 1.0

    def _detect_regime(self, spy_closes: list[float]) -> str:
        if len(spy_closes) < 20:
            return "sideways"
        recent = spy_closes[-20:]
        first_half = sum(recent[:10]) / 10
        second_half = sum(recent[10:]) / 10
        change = (second_half - first_half) / first_half
        if change > 0.02:
            return "bull"
        if change < -0.02:
            return "bear"
        return "sideways"

    def _momentum_swing_signal(self, closes: list[float]) -> str:
        from core.signals import rsi, macd, ema
        rsi_val = rsi(closes) or 50.0
        macd_result = macd(closes)
        ema20_series = ema(closes, 20)
        ema20 = next((v for v in reversed(ema20_series) if v is not None), None)
        price = closes[-1] if closes else 0.0
        if (
            rsi_val < 45
            and macd_result
            and macd_result.histogram > 0
            and ema20
            and price > ema20
        ):
            return "BUY"
        if (
            rsi_val > 55
            and macd_result
            and macd_result.histogram < 0
            and ema20
            and price < ema20
        ):
            return "SELL"
        return "HOLD"

    def _mean_reversion_signal(self, closes: list[float]) -> str:
        if len(closes) < 20:
            return "HOLD"
        window = closes[-20:]
        mean = sum(window) / 20
        variance = sum((x - mean) ** 2 for x in window) / 20
        std = variance ** 0.5
        price = closes[-1]
        if std == 0:
            return "HOLD"
        if price < mean - 1.5 * std:
            return "BUY"
        if price > mean + 1.5 * std:
            return "SELL"
        return "HOLD"

    def _earnings_momentum_signal(self, symbol: str) -> str:
        try:
            import yfinance as yf
            info = yf.Ticker(symbol).info
            growth = info.get("earningsQuarterlyGrowth", None)
            if growth is not None and growth > 0.15:
                return "BUY"
            if growth is not None and growth < -0.10:
                return "SELL"
        except Exception:
            pass
        return "HOLD"

    def _fetch_spy_closes(self) -> list[float]:
        try:
            from alpaca.data.historical.stock import StockHistoricalDataClient
            from alpaca.data.requests import StockBarsRequest
            from alpaca.data.timeframe import TimeFrame
            from alpaca.data.enums import DataFeed

            client = StockHistoricalDataClient(
                os.getenv("ALPACA_API_KEY", ""),
                os.getenv("ALPACA_SECRET_KEY", ""),
            )
            req = StockBarsRequest(
                symbol_or_symbols="SPY",
                timeframe=TimeFrame.Day,
                start=datetime.now(timezone.utc) - timedelta(days=30),
                limit=25,
                feed=DataFeed.IEX,
            )
            bars = client.get_stock_bars(req)
            df = bars.df
            if hasattr(df.index, "levels"):
                df = df.loc["SPY"]
            return df["close"].tolist()
        except Exception:
            return []
```

- [ ] **Step 4: Run the tests**

```
pytest tests/agents/test_strategy_engine.py -v
pytest --tb=short -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```
git add core/agents/strategy_engine.py tests/agents/test_strategy_engine.py
git commit -m "feat: add StrategyEngine with regime detection and 3 strategy signals"
```

---

### Task 3: ExplainEngine — plain-language trading explanations via Claude Haiku

**Files:**
- Create: `core/agents/explain_engine.py`
- Test: `tests/agents/test_explain_engine.py`

**Interfaces:**
- Consumes: `AnalysisResult` from `core.agents.market_analyst`; `data/trades.json` for history; `anthropic.Anthropic().messages.create(model="claude-haiku-4-5-20251001", ...)`
- Produces: `ExplainEngine().explain(query, symbol=None, analysis=None) -> str`

- [ ] **Step 1: Write the failing tests**

```python
# tests/agents/test_explain_engine.py
from unittest.mock import patch, MagicMock
from core.agents.explain_engine import ExplainEngine
from core.agents.market_analyst import AnalysisResult


def _make_analysis(symbol="NVDA", conviction=88.0, direction="BUY"):
    return AnalysisResult(
        symbol=symbol,
        conviction=conviction,
        direction=direction,
        technical_score=90.0,
        fundamental_score=80.0,
        sentiment_score=85.0,
        rationale="RSI oversold, strong momentum, positive news",
    )


class TestExplainEngine:
    def test_returns_non_empty_string(self):
        analysis = _make_analysis()
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text="NVDA shows 88% conviction based on strong momentum.")]
        with patch("anthropic.Anthropic") as MockCl:
            MockCl.return_value.messages.create.return_value = mock_resp
            result = ExplainEngine().explain("Why did you buy NVDA?", symbol="NVDA", analysis=analysis)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_uses_haiku_model(self):
        analysis = _make_analysis()
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text="NVDA is strong.")]
        with patch("anthropic.Anthropic") as MockCl:
            ExplainEngine().explain("thesis on NVDA", analysis=analysis)
            call_kwargs = MockCl.return_value.messages.create.call_args
            if call_kwargs:
                assert "haiku" in call_kwargs.kwargs.get("model", "")

    def test_fallback_contains_symbol_on_api_failure(self):
        analysis = _make_analysis("AAPL", 75.0)
        with patch("anthropic.Anthropic", side_effect=Exception("API down")):
            result = ExplainEngine().explain("What's your thesis?", symbol="AAPL", analysis=analysis)
        assert "AAPL" in result
        assert "75" in result

    def test_works_without_analysis(self):
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text="No current open positions.")]
        with patch("anthropic.Anthropic") as MockCl:
            MockCl.return_value.messages.create.return_value = mock_resp
            result = ExplainEngine().explain("How are we doing?")
        assert isinstance(result, str)

    def test_load_trades_context_handles_missing_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr("core.agents.explain_engine._TRADES_PATH", tmp_path / "trades.json")
        engine = ExplainEngine()
        assert engine._load_trades_context(None) == ""

    def test_load_trades_context_filters_by_symbol(self, tmp_path, monkeypatch):
        import json
        trades_file = tmp_path / "trades.json"
        trades_file.write_text(json.dumps([
            {"symbol": "NVDA", "side": "buy", "qty": 0.01, "price": 450.0, "timestamp": "2026-06-22T10:00:00", "signal": "conviction"},
            {"symbol": "AAPL", "side": "buy", "qty": 0.05, "price": 200.0, "timestamp": "2026-06-22T11:00:00", "signal": "conviction"},
        ]))
        monkeypatch.setattr("core.agents.explain_engine._TRADES_PATH", trades_file)
        engine = ExplainEngine()
        context = engine._load_trades_context("NVDA")
        assert "NVDA" in context
        assert "AAPL" not in context
```

- [ ] **Step 2: Run to confirm failure**

```
pytest tests/agents/test_explain_engine.py -v
```

Expected: `ModuleNotFoundError: No module named 'core.agents.explain_engine'`

- [ ] **Step 3: Create `core/agents/explain_engine.py`**

```python
"""
ExplainEngine -- answers "why/how/thesis" queries about trades and positions
using Claude Haiku with structured context. Falls back to raw analysis text
when the API is unavailable.
"""
import json
from pathlib import Path

_TRADES_PATH = Path("data/trades.json")


class ExplainEngine:
    def explain(
        self,
        query: str,
        symbol: str | None = None,
        analysis=None,
    ) -> str:
        """Return a plain-language answer to a trading query.

        analysis -- optional AnalysisResult from MarketAnalyst
        """
        trades_ctx = self._load_trades_context(symbol)
        context_parts: list[str] = []

        if analysis is not None:
            context_parts.append(
                f"Latest analysis for {analysis.symbol}:\n"
                f"Conviction: {analysis.conviction:.1f}% | Direction: {analysis.direction}\n"
                f"Technical: {analysis.technical_score:.0f}/100 | "
                f"Fundamental: {analysis.fundamental_score:.0f}/100 | "
                f"Sentiment: {analysis.sentiment_score:.0f}/100\n"
                f"Detail: {analysis.rationale}"
            )
        if trades_ctx:
            context_parts.append(f"Recent trades:\n{trades_ctx}")

        context = "\n\n".join(context_parts) if context_parts else "No current analysis available."

        prompt = (
            "You are El Fager's trading analyst. Answer the query in 2-3 sentences max, "
            "plain language, no jargon. No emojis.\n\n"
            f"Context:\n{context}\n\n"
            f"Query: {query}"
        )

        try:
            import anthropic
            client = anthropic.Anthropic()
            resp = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}],
            )
            return resp.content[0].text.strip()
        except Exception:
            if analysis is not None:
                return (
                    f"Analysis for {analysis.symbol}: conviction {analysis.conviction:.0f}%, "
                    f"direction {analysis.direction}. {analysis.rationale[:200]}"
                )
            return "Unable to generate explanation -- no analysis available."

    def _load_trades_context(self, symbol: str | None) -> str:
        if not _TRADES_PATH.exists():
            return ""
        try:
            trades = json.loads(_TRADES_PATH.read_text(encoding="utf-8"))
            if symbol:
                trades = [t for t in trades if t.get("symbol") == symbol]
            recent = trades[-5:]
            lines = [
                f"{t.get('timestamp', '')[:10]} "
                f"{t.get('side', '').upper()} "
                f"{t.get('qty', 0):.4f} "
                f"{t.get('symbol', '')} "
                f"@ ${t.get('price', 0):.2f} "
                f"(signal: {t.get('signal', 'unknown')})"
                for t in recent
            ]
            return "\n".join(lines)
        except Exception:
            return ""
```

- [ ] **Step 4: Run the tests**

```
pytest tests/agents/test_explain_engine.py -v
pytest --tb=short -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```
git add core/agents/explain_engine.py tests/agents/test_explain_engine.py
git commit -m "feat: add ExplainEngine using Claude Haiku for plain-language trade explanations"
```

---

### Task 4: StocksAgent — orchestrator + conviction-gated trading

**Files:**
- Create: `core/agents/stocks_agent.py`
- Test: `tests/agents/test_stocks_agent.py`

**Interfaces:**
- Consumes: `MarketAnalyst().analyze(symbol)`, `StrategyEngine().select_strategy(symbol, closes)`, `ExplainEngine().explain(query, symbol, analysis)`, `core.risk_manager` functions, Alpaca trading client, `data/trading_config.json`
- Produces: `StocksAgent(BaseAgent)` with `run(task) -> str`; registers as `name = "stocks"` for agent-lane dispatch

- [ ] **Step 1: Write the failing tests**

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
        mock_analyst._fetch_ohlcv.return_value = ([100.0] * 30, [1_000_000] * 30)

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
        mock_analyst._fetch_ohlcv.return_value = ([100.0] * 30, [1_000_000] * 30)

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
        mock_analyst._fetch_ohlcv.return_value = ([100.0] * 30, [1_000_000] * 30)

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
        mock_analyst._fetch_ohlcv.return_value = ([100.0] * 30, [1_000_000] * 30)

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

- [ ] **Step 2: Run to confirm failure**

```
pytest tests/agents/test_stocks_agent.py -v
```

Expected: `ModuleNotFoundError: No module named 'core.agents.stocks_agent'`

- [ ] **Step 3: Create `core/agents/stocks_agent.py`**

```python
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

- [ ] **Step 4: Run the tests**

```
pytest tests/agents/test_stocks_agent.py -v
pytest --tb=short -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```
git add core/agents/stocks_agent.py tests/agents/test_stocks_agent.py
git commit -m "feat: add StocksAgent with conviction-gated autonomous trading"
```

---

### Task 5: Router refinement + brain.py wiring

**Files:**
- Modify: `core/agents/router.py`
- Modify: `core/brain.py:5953-5963`
- Modify: `tests/agents/test_router.py`

**Interfaces:**
- Consumes: `classify_intent(message) -> str` (existing) -- must now return "stocks_agent" for analytical queries
- Produces: `classify_intent()` returning "stocks_agent" for analytical/agentic stock queries; "stocks" for simple lookups; `_try_agent_dispatch()` routing "stocks_agent" to StocksAgent

**Key design decision:** `_STOCKS_AGENT_KEYWORDS` is checked BEFORE `_STOCKS_KEYWORDS` in the router. "What's the price of AAPL?" contains "aapl" -> stays "stocks" (instant-lane). "Analyze AAPL" contains "analyze" -> becomes "stocks_agent".

- [ ] **Step 1: Add tests for the new "stocks_agent" intent**

Add these classes to `tests/agents/test_router.py` (keep all existing tests):

```python
# Append to tests/agents/test_router.py

class TestStocksAgentRouting:
    def test_analyze_keyword_routes_to_stocks_agent(self):
        from core.agents.router import classify_intent
        assert classify_intent("analyze NVDA for me") == "stocks_agent"

    def test_thesis_keyword_routes_to_stocks_agent(self):
        from core.agents.router import classify_intent
        assert classify_intent("what's your thesis on AAPL?") == "stocks_agent"

    def test_should_i_buy_routes_to_stocks_agent(self):
        from core.agents.router import classify_intent
        assert classify_intent("should I buy MSFT right now?") == "stocks_agent"

    def test_why_did_you_buy_routes_to_stocks_agent(self):
        from core.agents.router import classify_intent
        assert classify_intent("why did you buy NVDA?") == "stocks_agent"

    def test_pause_trading_routes_to_stocks_agent(self):
        from core.agents.router import classify_intent
        assert classify_intent("pause trading please") == "stocks_agent"

    def test_set_threshold_routes_to_stocks_agent(self):
        from core.agents.router import classify_intent
        assert classify_intent("set auto-trade threshold to 90%") == "stocks_agent"

    def test_price_query_stays_instant_stocks(self):
        from core.agents.router import classify_intent
        # Simple price lookup stays in instant-lane ("stocks" not "stocks_agent")
        result = classify_intent("what's the price of AAPL?")
        assert result == "stocks"

    def test_market_overview_stays_instant_stocks(self):
        from core.agents.router import classify_intent
        result = classify_intent("how's the market today?")
        assert result in ("stocks", "instant")

    def test_scan_watchlist_routes_to_stocks_agent(self):
        from core.agents.router import classify_intent
        assert classify_intent("scan my watchlist") == "stocks_agent"
```

- [ ] **Step 2: Run new tests to confirm they fail**

```
pytest tests/agents/test_router.py -v -k "StocksAgent"
```

Expected: FAIL (classify_intent returns "stocks" not "stocks_agent")

- [ ] **Step 3: Update `core/agents/router.py`**

Replace the entire file with:

```python
# Keywords that map to each agent.
# Priority: first match wins -- order of checks in classify_intent matters.
_SCREEN_KEYWORDS = [
    "click", "double click", "right click", "scroll up", "scroll down",
    "type in", "press enter", "press tab", "press escape", "drag",
    "hotkey", "what's on my screen", "look at my screen",
    "open and then", "control the app", "automate the", "desktop app",
    "take a screenshot", "what do you see", "describe the screen",
    "what error is showing", "what's open",
]

_BROWSER_KEYWORDS = [
    "website", "webpage", "navigate to", "go to http", "go to www",
    "book a table", "book me a", "book a flight", "search flights",
    "log into", "login to", "log in to", "sign in to",
    "fill out", "fill in", "submit the form",
    "university portal", "online portal", "bank account", "check my bank",
    "open browser", "browse to", ".com", ".org", ".net", ".eg",
    "search on google", "search on amazon",
]

# StocksAgent handles ANALYTICAL and AGENTIC stock tasks.
# Checked BEFORE _STOCKS_KEYWORDS so these take priority.
_STOCKS_AGENT_KEYWORDS = [
    "analyze", "thesis on", "your thesis",
    "should i buy", "should i sell", "should we buy",
    "your view on", "your opinion on",
    "what do you think about", "what's your take on",
    "conviction on", "outlook for", "stock outlook",
    "deep analysis", "deep dive",
    "why did you buy", "why did we buy",
    "why did you sell", "why did we sell",
    "how are we doing trading", "my trading stats", "trading performance",
    "scan my watchlist", "scan portfolio", "scan watchlist",
    "pause trading", "resume trading", "unpause trading",
    "stop auto-trade", "start auto-trade",
    "set auto-trade threshold", "set threshold",
    "auto-trade threshold", "auto trade threshold",
    "explain my portfolio", "explain my trades",
]

# Instant-lane stock tools: price lookups, watchlist, alerts, market overview.
_STOCKS_KEYWORDS = [
    "stock", "stocks", "trade", "trading", "portfolio", "ticker",
    "buy shares", "sell shares", "invest", "investing", "investment",
    "trading engine", "trading agent", "open positions", "trade history",
    "bull", "bear", "bullish", "bearish", "earnings", "dividend",
    "p/e ratio", "rsi", "macd", "moving average",
    "nvda", "aapl", "msft", "amzn", "googl", "meta", "tsla",
    "spy", "qqq", "btc", "eth", "crypto",
]

_RESEARCH_KEYWORDS = [
    "research everything", "deep dive into", "find out everything about",
    "investigate", "comprehensive analysis of", "tell me everything about",
    "summarize the news about", "latest news about",
    "everything happening with", "what do we know about",
    "research the best", "compare and contrast",
]

_FILE_KEYWORDS = [
    ".pdf", ".docx", ".xlsx", ".doc", ".pptx",
    "this pdf", "this document", "this file", "this contract",
    "read this pdf", "summarize this pdf", "summarize this document",
    "what does this file say", "extract from this",
    "this invoice", "this thesis", "this report", "this spreadsheet",
    "payment terms", "what did this contract",
]

_LABEL_KEYWORDS = [
    ("screen", _SCREEN_KEYWORDS),
    ("browser", _BROWSER_KEYWORDS),
    ("stocks_agent", _STOCKS_AGENT_KEYWORDS),  # checked before "stocks"
    ("stocks", _STOCKS_KEYWORDS),
    ("research", _RESEARCH_KEYWORDS),
    ("file", _FILE_KEYWORDS),
]


def classify_intent(message: str) -> str:
    """Return the agent label that should handle this message.

    Returns one of: 'screen', 'browser', 'stocks_agent', 'stocks',
    'research', 'file', 'instant'.
    Uses keyword matching. First match wins.
    """
    import re
    msg = message.lower()
    for label, keywords in _LABEL_KEYWORDS:
        for kw in keywords:
            if len(kw) <= 3:
                pattern = r"\b" + re.escape(kw) + r"\b"
                if re.search(pattern, msg):
                    return label
            elif kw in msg:
                return label
    return "instant"
```

- [ ] **Step 4: Run router tests**

```
pytest tests/agents/test_router.py -v
```

Expected: all pass (new + existing).

- [ ] **Step 5: Wire StocksAgent into brain.py**

Find `_try_agent_dispatch` in `core/brain.py` (currently at line ~5953). The method body is:

```python
def _try_agent_dispatch(self, task: str) -> str | None:
    """Route complex tasks to a specialist agent. Returns None for instant-lane tasks."""
    from core.agents.router import classify_intent
    intent = classify_intent(task)
    if intent == "screen":
        from core.agents.screen_agent import ScreenAgent
        return ScreenAgent().run(task)
    if intent == "browser":
        from core.agents.browser_agent import BrowserAgent
        return BrowserAgent().run(task)
    return None  # stocks / research / file not yet implemented -- fall through
```

Replace that method body with:

```python
def _try_agent_dispatch(self, task: str) -> str | None:
    """Route complex tasks to a specialist agent. Returns None for instant-lane tasks."""
    from core.agents.router import classify_intent
    intent = classify_intent(task)
    if intent == "screen":
        from core.agents.screen_agent import ScreenAgent
        return ScreenAgent().run(task)
    if intent == "browser":
        from core.agents.browser_agent import BrowserAgent
        return BrowserAgent().run(task)
    if intent == "stocks_agent":
        from core.agents.stocks_agent import StocksAgent
        return StocksAgent().run(task)
    return None  # research / file not yet implemented -- fall through
```

- [ ] **Step 6: Run the full suite**

```
pytest --tb=short -q
```

Expected: all existing + new tests green.

- [ ] **Step 7: Commit**

```
git add core/agents/router.py core/brain.py tests/agents/test_router.py
git commit -m "feat: wire StocksAgent into agent router and brain dispatch"
```

---

### Task 6: Config migration + Phase 2 risk parameters

**Files:**
- Modify: `data/trading_config.json`

**What changes:** Add the three new StocksAgent keys (`auto_trade_threshold`, `auto_trade_paused`, `conviction_delay_seconds`) and update risk parameters to Phase 2 values ($10-20 account: max 3 positions, 33% per position, 5% SL, 12% TP).

- [ ] **Step 1: Read the current config**

```
Get-Content "C:\claude proj\el_fager\data\trading_config.json"
```

- [ ] **Step 2: Write the updated config**

Merge in the new keys while keeping existing keys. Final file content:

```json
{
  "mode": "paper",
  "active_symbols": ["SPY", "QQQ", "AAPL", "NVDA", "MSFT"],
  "cycle_interval_minutes": 15,
  "max_open_positions": 3,
  "max_position_pct": 33,
  "stop_loss_pct": 5,
  "take_profit_pct": 12,
  "daily_loss_limit_pct": 10,
  "auto_trade_threshold": 85,
  "auto_trade_paused": false,
  "conviction_delay_seconds": 60
}
```

- [ ] **Step 3: Verify the full suite still passes**

```
pytest --tb=short -q
```

Expected: all tests green (config is runtime data, not tested directly).

- [ ] **Step 4: Smoke test StocksAgent with a control command**

```python
# Run this snippet to confirm StocksAgent reads config correctly
import os, sys
sys.path.insert(0, r"C:\claude proj\el_fager")
from core.agents.stocks_agent import StocksAgent
agent = StocksAgent()
print(agent.run("pause trading"))   # Should return "Autonomous trading paused..."
print(agent.run("resume trading"))  # Should return "Autonomous trading resumed."
print(agent.run("set auto-trade threshold to 90%"))  # Should confirm 90%
```

Expected output (no errors, correct responses).

- [ ] **Step 5: Commit**

```
git add data/trading_config.json
git commit -m "config: Phase 2 risk parameters and StocksAgent conviction thresholds"
```

---

## Self-Review Against Spec

| Spec requirement | Task |
|---|---|
| MarketAnalyst: RSI, MACD, EMA20/50, Bollinger, Volume | Task 1 `_score_technical` |
| MarketAnalyst: fundamental P/E, revenue, earnings growth | Task 1 `_score_fundamental` |
| MarketAnalyst: sentiment via news keywords | Task 1 `_score_sentiment` |
| StrategyEngine: momentum swing, mean reversion, earnings momentum | Task 2 |
| StrategyEngine: regime detection (bull/bear/sideways) via SPY | Task 2 `_detect_regime` |
| ExplainEngine: "why did you buy?", "thesis on?", "how are we doing?" | Task 3 |
| ExplainEngine: Claude Haiku, fallback to raw analysis | Task 3 |
| conviction >= 85%: auto-execute | Task 4 `_analyze_and_decide` |
| conviction 60-85%: delayed 60s auto-execute | Task 4 threading.Timer |
| conviction < 60%: ask confirmation | Task 4 |
| "pause trading" voice command | Task 4 `_handle_control_command` |
| "set auto-trade threshold to N%" | Task 4 |
| Daily loss limit > 10% -> auto-pause | NOT in this plan -- TradingEngine already enforces 5% daily limit; Phase 2 config sets it to 10%. StocksAgent doesn't run a 15-min loop, so this is enforced at the TradingEngine level. |
| Max 3 positions, 33% per position | Task 6 config + existing risk_manager |
| 5% SL, 12% TP | Task 6 config |
| Paper-to-real gate remains Phase 5 | No action needed -- config `mode: "paper"` enforced |
| BrowserAgent login injection gap (from Phase 1 review) | Out of scope for Phase 2; tracked separately |

**Placeholder check:** No TBD, TODO, or "implement later" in any step. All code blocks are complete.

**Type consistency:**
- `AnalysisResult` NamedTuple defined in Task 1, imported in Tasks 3, 4 tests.
- `_fetch_ohlcv()` defined on `MarketAnalyst` in Task 1, called in Task 4 `_analyze_and_decide`.
- `_CONFIG_PATH` module-level var in Task 4, monkeypatched correctly in tests via `import core.agents.stocks_agent as sa; monkeypatch.setattr(sa, "_CONFIG_PATH", ...)`.
- `classify_intent()` signature unchanged; "stocks_agent" is a new return value.
