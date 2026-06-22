"""
Technical indicators for the trading engine.
Pure Python — no external deps, no API calls, fully unit-testable.
"""
from typing import NamedTuple


class MACDResult(NamedTuple):
    macd: float
    signal: float
    histogram: float


class SignalStrength:
    STRONG_BUY = "STRONG_BUY"
    STRONG_SELL = "STRONG_SELL"
    AMBIGUOUS_BUY = "AMBIGUOUS_BUY"
    AMBIGUOUS_SELL = "AMBIGUOUS_SELL"
    HOLD = "HOLD"


def ema(prices: list[float], period: int) -> list[float | None]:
    """Exponential moving average. Returns same-length list; first (period-1) values are None."""
    if len(prices) < period:
        return [None] * len(prices)
    k = 2.0 / (period + 1)
    result: list[float | None] = [None] * (period - 1)
    seed = sum(prices[:period]) / period
    result.append(seed)
    for price in prices[period:]:
        result.append(price * k + result[-1] * (1 - k))
    return result


def rsi(prices: list[float], period: int = 14) -> float | None:
    """RSI(period). Returns None when fewer than period+1 prices supplied."""
    if len(prices) < period + 1:
        return None
    deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    gains = [d if d > 0 else 0.0 for d in deltas]
    losses = [-d if d < 0 else 0.0 for d in deltas]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    if avg_gain == 0:
        return 0.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1 + rs))


def macd(
    prices: list[float],
    fast: int = 12,
    slow: int = 26,
    signal_period: int = 9,
) -> MACDResult | None:
    """MACD(fast, slow, signal). Returns None when not enough data."""
    if len(prices) < slow + signal_period:
        return None

    fast_ema = ema(prices, fast)
    slow_ema = ema(prices, slow)

    macd_line: list[float] = []
    for f, s in zip(fast_ema, slow_ema):
        if f is None or s is None:
            continue
        macd_line.append(f - s)

    if len(macd_line) < signal_period:
        return None

    signal_line = ema(macd_line, signal_period)
    last_signal = next((v for v in reversed(signal_line) if v is not None), None)
    if last_signal is None:
        return None

    last_macd = macd_line[-1]
    return MACDResult(
        macd=round(last_macd, 6),
        signal=round(last_signal, 6),
        histogram=round(last_macd - last_signal, 6),
    )


def classify_signal(
    closes: list[float],
    rsi_value: float | None,
    macd_result: MACDResult | None,
) -> str:
    """Classify signal strength. Returns a SignalStrength constant."""
    if rsi_value is None or macd_result is None:
        return SignalStrength.HOLD

    ema20 = ema(closes, 20)
    current_ema20 = next((v for v in reversed(ema20) if v is not None), None)
    current_price = closes[-1] if closes else None

    price_above_ema20 = (
        current_price is not None
        and current_ema20 is not None
        and current_price > current_ema20
    )
    price_below_ema20 = (
        current_price is not None
        and current_ema20 is not None
        and current_price < current_ema20
    )

    macd_bullish = macd_result.histogram > 0
    macd_bearish = macd_result.histogram < 0

    if rsi_value < 35 and macd_bullish and price_above_ema20:
        return SignalStrength.STRONG_BUY
    if rsi_value > 65 and macd_bearish and price_below_ema20:
        return SignalStrength.STRONG_SELL
    if rsi_value < 40:
        return SignalStrength.AMBIGUOUS_BUY
    if rsi_value > 60:
        return SignalStrength.AMBIGUOUS_SELL
    return SignalStrength.HOLD
