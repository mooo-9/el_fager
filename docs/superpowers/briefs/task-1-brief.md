# Task 1 Brief: MarketAnalyst

## Context
You are implementing Task 1 of Phase 2 of El Fager — a personal Windows AI assistant with an autonomous trading agent. The project is at `C:\claude proj\el_fager`. Phase 1 (ScreenAgent + BrowserAgent) is complete with 82 tests passing (master branch, base commit 263230c).

This task creates the `MarketAnalyst` class and `AnalysisResult` NamedTuple — the signal-scoring engine that StocksAgent (Task 4) will call.

## Global Constraints (must be obeyed)
- Python 3.14 — no walrus operator
- DataFeed.IEX — ALL Alpaca bar requests MUST include `feed=DataFeed.IEX`
- cp1252 safety — NO emojis, NO Arabic text, NO U+2192 in any return string
- No new pip installs — yfinance, alpaca-py, anthropic already installed
- Run pytest from `C:\claude proj\el_fager`; all existing tests must remain green

## What to build

### Files to create
- `core/agents/market_analyst.py`
- `tests/agents/test_market_analyst.py`

### Interfaces produced (later tasks depend on these exact names)
```python
class AnalysisResult(NamedTuple):
    symbol: str
    conviction: float      # 0-100; higher = stronger buy signal
    direction: str         # "BUY", "SELL", or "HOLD"
    technical_score: float
    fundamental_score: float
    sentiment_score: float
    rationale: str

class MarketAnalyst:
    def analyze(self, symbol: str) -> AnalysisResult: ...
    def _fetch_ohlcv(self, symbol: str) -> tuple[list[float], list[float]]: ...
    def _score_technical(self, closes: list[float], volumes: list[float]) -> tuple[float, str]: ...
    def _score_fundamental(self, symbol: str) -> tuple[float, str]: ...
    def _score_sentiment(self, symbol: str) -> tuple[float, str]: ...
```

## Tests to write (write these FIRST before implementation)

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
    def test_oversold_series_scores_above_55(self):
        analyst = MarketAnalyst()
        closes = [100.0 - i * 0.8 for i in range(30)] + [72.0, 71.0, 70.0, 69.0, 68.0]
        volumes = [1_000_000] * len(closes)
        score, rationale = analyst._score_technical(closes, volumes)
        assert score >= 55, f"Oversold RSI series should score >= 55, got {score}"
        assert "RSI" in rationale

    def test_overbought_series_scores_below_55(self):
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

## Implementation to write (after tests fail)

```python
# core/agents/market_analyst.py
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

        bb_score = max(0.0, min(100.0, (1.0 - bb_pct) * 100.0))

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

## Steps
1. Write tests file first
2. Run `python -m pytest tests/agents/test_market_analyst.py -v` — confirm ModuleNotFoundError
3. Write implementation file
4. Run tests — confirm all pass
5. Run full suite `python -m pytest --tb=short -q` — confirm all existing tests still pass
6. Commit: `git add core/agents/market_analyst.py tests/agents/test_market_analyst.py && git commit -m "feat: add MarketAnalyst with technical/fundamental/sentiment scoring"`

## Report
Write your report to: `docs/superpowers/briefs/task-1-report.md`

Report must include:
- Status: DONE / DONE_WITH_CONCERNS / BLOCKED
- Commits made (short hashes)
- Test results summary (e.g., "12 passed, 0 failed")
- Any concerns or deviations from the brief
