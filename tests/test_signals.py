"""Unit tests for core/signals.py — pure logic, no API calls."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_ema_returns_none_for_first_period_minus_one_values():
    from core.signals import ema
    result = ema([1.0, 2.0, 3.0, 4.0, 5.0], period=3)
    assert result[0] is None
    assert result[1] is None
    assert result[2] is not None  # SMA seed at index period-1


def test_ema_seed_equals_sma():
    from core.signals import ema
    prices = [2.0, 4.0, 6.0]
    result = ema(prices, period=3)
    assert result[2] == 4.0  # (2+4+6)/3


def test_ema_rises_with_prices():
    from core.signals import ema
    prices = [1.0, 2.0, 3.0, 4.0, 5.0]
    result = ema(prices, period=3)
    assert result[3] > result[2]
    assert result[4] > result[3]


def test_rsi_returns_none_with_insufficient_data():
    from core.signals import rsi
    assert rsi([1.0, 2.0, 3.0], period=14) is None


def test_rsi_returns_100_when_all_gains():
    from core.signals import rsi
    prices = [float(i) for i in range(1, 20)]  # 1..19, always rising
    result = rsi(prices, period=14)
    assert result == 100.0


def test_rsi_returns_0_when_all_losses():
    from core.signals import rsi
    prices = [float(20 - i) for i in range(20)]  # 20..1, always falling
    result = rsi(prices, period=14)
    assert result == 0.0


def test_rsi_is_between_0_and_100_for_mixed_data():
    from core.signals import rsi
    import random
    random.seed(42)
    prices = [100.0 + random.uniform(-2, 2) for _ in range(30)]
    result = rsi(prices, period=14)
    assert result is not None
    assert 0.0 <= result <= 100.0


def test_macd_returns_none_with_insufficient_data():
    from core.signals import macd
    assert macd([1.0] * 30) is None  # needs slow(26) + signal(9) = 35 points


def test_macd_returns_named_tuple_with_enough_data():
    from core.signals import macd
    prices = [float(i % 10 + 1) for i in range(50)]
    result = macd(prices)
    assert result is not None
    assert hasattr(result, "macd")
    assert hasattr(result, "signal")
    assert hasattr(result, "histogram")
    assert result.histogram == round(result.macd - result.signal, 6)


def test_classify_signal_hold_when_indicators_none():
    from core.signals import classify_signal, SignalStrength
    result = classify_signal([100.0] * 30, rsi_value=None, macd_result=None)
    assert result == SignalStrength.HOLD


def test_classify_signal_strong_buy():
    from core.signals import classify_signal, SignalStrength, MACDResult
    mock_macd = MACDResult(macd=0.5, signal=0.3, histogram=0.2)
    # flat prices then jump — last price above EMA20
    closes = [99.0] * 20 + [102.0]
    result = classify_signal(closes, rsi_value=25.0, macd_result=mock_macd)
    assert result == SignalStrength.STRONG_BUY


def test_classify_signal_strong_sell():
    from core.signals import classify_signal, SignalStrength, MACDResult
    mock_macd = MACDResult(macd=-0.5, signal=-0.3, histogram=-0.2)
    closes = [101.0] * 20 + [98.0]
    result = classify_signal(closes, rsi_value=75.0, macd_result=mock_macd)
    assert result == SignalStrength.STRONG_SELL


def test_classify_signal_ambiguous_buy():
    from core.signals import classify_signal, SignalStrength, MACDResult
    mock_macd = MACDResult(macd=0.1, signal=0.3, histogram=-0.2)  # mixed: RSI low but MACD negative
    closes = [100.0] * 21
    result = classify_signal(closes, rsi_value=32.0, macd_result=mock_macd)
    assert result == SignalStrength.AMBIGUOUS_BUY


def test_classify_signal_ambiguous_sell():
    from core.signals import classify_signal, SignalStrength, MACDResult
    mock_macd = MACDResult(macd=-0.1, signal=-0.3, histogram=0.2)  # mixed: RSI high but MACD positive
    closes = [100.0] * 21
    result = classify_signal(closes, rsi_value=68.0, macd_result=mock_macd)
    assert result == SignalStrength.AMBIGUOUS_SELL
