import pytest
import core.backtester as bt
from core.risk_manager import get_stop_loss_price, get_take_profit_price


def _flat_bars(n: int, price: float = 100.0) -> list[dict]:
    """n independent bar dicts all at the same price."""
    return [
        {"open": price, "high": price * 1.001, "low": price * 0.999, "close": price}
        for _ in range(n)
    ]


def _bar(open_: float, high: float, low: float, close: float) -> dict:
    return {"open": open_, "high": high, "low": low, "close": close}


def _pin_sl_tp(monkeypatch, sl_pct: float = 5.0, tp_pct: float = 12.0) -> None:
    """Pin the exit levels these tests are written around.

    Live percentages come from data/trading_config.json, which Mo can change by
    voice - without this the expected pnl depends on whatever is on disk.
    """
    monkeypatch.setattr(bt, "get_stop_loss_price",
                        lambda entry: round(entry * (1 - sl_pct / 100), 2))
    monkeypatch.setattr(bt, "get_take_profit_price",
                        lambda entry: round(entry * (1 + tp_pct / 100), 2))


# --- _max_drawdown ---

def test_max_drawdown_basic():
    # Peak 110 at index 1, valley 90 at index 2 → (110-90)/110*100 ≈ 18.18%
    values = [100.0, 110.0, 90.0, 95.0]
    assert bt._max_drawdown(values) == pytest.approx(18.18, rel=0.01)


def test_max_drawdown_no_drawdown():
    assert bt._max_drawdown([100.0, 101.0, 102.0, 103.0]) == 0.0


# --- _sharpe ---

def test_sharpe_positive_returns():
    values = [100.0 + i * 0.1 for i in range(200)]
    assert bt._sharpe(values) > 0.0


def test_sharpe_no_variance():
    assert bt._sharpe([100.0] * 50) == 0.0


# --- _simulate ---

def test_simulate_insufficient_bars():
    result = bt._simulate(_flat_bars(50), "TEST")
    assert result.total_trades == 0
    assert result.total_return_pct == 0.0


def test_simulate_no_signals(monkeypatch):
    monkeypatch.setattr(bt, "rsi", lambda *a, **k: 50.0)
    monkeypatch.setattr(bt, "macd", lambda *a, **k: type("M", (), {"histogram": 0.0})())
    monkeypatch.setattr(bt, "classify_signal", lambda *a: "HOLD")
    result = bt._simulate(_flat_bars(200), "TEST")
    assert result.total_trades == 0
    assert result.total_return_pct == 0.0


def test_simulate_tp_hit(monkeypatch):
    """Signal at bar 100 -> fill at bar 101 open=100.0 -> TP hit at bar 110 high=116.0."""
    calls = [0]
    def mock_sig(*a):
        calls[0] += 1
        return "STRONG_BUY" if calls[0] == 1 else "HOLD"
    monkeypatch.setattr(bt, "rsi", lambda *a, **k: 50.0)
    monkeypatch.setattr(bt, "macd", lambda *a, **k: type("M", (), {"histogram": 0.0})())
    monkeypatch.setattr(bt, "classify_signal", mock_sig)
    _pin_sl_tp(monkeypatch)
    bars = _flat_bars(200, 100.0)
    bars[101] = _bar(100.0, 101.0, 99.0, 100.0)
    # Derived from risk_manager so the test tracks the configured take-profit
    # instead of going stale when the default changes.
    tp = get_take_profit_price(100.0)
    expected_gain = (tp - 100.0) / 100.0 * 100
    bars[110] = _bar(tp, tp + 1.0, tp - 1.0, tp)  # high clears tp
    result = bt._simulate(bars, "TEST")
    assert result.total_trades == 1
    assert result.winning_trades == 1
    assert result.losing_trades == 0
    assert result.win_rate_pct == 100.0
    assert result.avg_gain_pct == pytest.approx(expected_gain, rel=0.01)


def test_simulate_sl_hit(monkeypatch):
    """Signal at bar 100 -> fill at bar 101 open=100.0 -> SL hit at bar 110 low=91.0."""
    calls = [0]
    def mock_sig(*a):
        calls[0] += 1
        return "STRONG_BUY" if calls[0] == 1 else "HOLD"
    monkeypatch.setattr(bt, "rsi", lambda *a, **k: 50.0)
    monkeypatch.setattr(bt, "macd", lambda *a, **k: type("M", (), {"histogram": 0.0})())
    monkeypatch.setattr(bt, "classify_signal", mock_sig)
    _pin_sl_tp(monkeypatch)
    bars = _flat_bars(200, 100.0)
    bars[101] = _bar(100.0, 101.0, 99.0, 100.0)
    # Derived from risk_manager so the test tracks the configured stop-loss
    # instead of going stale when the default changes.
    sl = get_stop_loss_price(100.0)
    expected_loss = abs((sl - 100.0) / 100.0 * 100)
    bars[110] = _bar(sl, sl + 1.0, sl - 1.0, sl)  # low clears sl
    result = bt._simulate(bars, "TEST")
    assert result.total_trades == 1
    assert result.winning_trades == 0
    assert result.losing_trades == 1
    assert result.win_rate_pct == 0.0
    assert result.avg_loss_pct == pytest.approx(expected_loss, rel=0.01)


def test_simulate_benchmark_return():
    """buy-and-hold return = (last_close - first_close) / first_close * 100."""
    bars = _flat_bars(200, 100.0)
    bars[-1] = _bar(150.0, 151.0, 149.0, 150.0)
    # flat bars at 100 -> RSI=100 -> AMBIGUOUS_SELL -> no STRONG_BUY -> 0 trades
    result = bt._simulate(bars, "TEST")
    assert result.benchmark_return_pct == pytest.approx(50.0, rel=0.01)
    assert result.total_trades == 0
