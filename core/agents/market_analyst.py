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

        rsi_result = rsi(closes)
        rsi_val = rsi_result if rsi_result is not None else 50.0
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
        score = raw
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
