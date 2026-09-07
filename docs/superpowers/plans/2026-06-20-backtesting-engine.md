# Backtesting Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a historical backtesting engine that replays 2 years of Alpaca hourly bar data, applies the existing signal and risk logic, and reports 5 performance metrics vs. a buy-and-hold benchmark.

**Architecture:** `core/backtester.py` contains pure simulation logic (no API calls); `tools/backtest_tool.py` wraps it as 4 Jarvis voice commands and persists results to `data/backtest_results.json`; `core/brain.py` is modified to register the 4 tools.

**Tech Stack:** alpaca-py (already installed, v0.43.4), stdlib only (json, os, pathlib, datetime, zoneinfo). No new pip deps.

## Global Constraints

- Python 3.14 type hints: `list[float]`, `X | None`, `dict[str, ...]` — NEVER `Optional`, `List`, `Dict`, `Tuple`
- cp1252 safety: NEVER use `->` (U+2192), `⚠` (U+26A0), `⭐` (U+2B50), emojis, or Arabic in tool return strings. Em-dash `—` IS safe (cp1252 0x97).
- All Alpaca SDK imports MUST be deferred inside functions (same pattern as `core/trading_engine.py`)
- `zoneinfo.ZoneInfo` for any timezone logic — never `pytz`
- `data/backtest_results.json` is gitignored (covered by `data/` in `.gitignore`) — never stage it
- No new pip dependencies

---

## Existing interfaces consumed by this feature

From `core/signals.py`:
```python
class MACDResult(NamedTuple):
    macd: float; signal: float; histogram: float

class SignalStrength:
    STRONG_BUY = "STRONG_BUY"
    # ... other constants

def rsi(prices: list[float], period: int = 14) -> float | None
def macd(prices: list[float], fast=12, slow=26, signal_period=9) -> MACDResult | None
def classify_signal(closes: list[float], rsi_value: float | None, macd_result: MACDResult | None) -> str
```

From `core/risk_manager.py`:
```python
def calc_position_size(portfolio_value: float, price_per_share: float) -> float  # fractional shares
def get_stop_loss_price(entry_price: float) -> float   # entry * (1 - stop_loss_pct/100)
def get_take_profit_price(entry_price: float) -> float  # entry * (1 + take_profit_pct/100)
```
Defaults: stop_loss_pct=8 (sl = entry * 0.92), take_profit_pct=15 (tp = entry * 1.15), max_position_pct=10.

---

### Task 1: core/backtester.py — Simulation Engine

**Files:**
- Create: `core/backtester.py`
- Create (test): `tests/test_backtester.py`

**Interfaces produced (Task 2 consumes these):**
```python
SymbolResult = NamedTuple('SymbolResult', [
    ('symbol', str),
    ('total_return_pct', float),
    ('benchmark_return_pct', float),
    ('win_rate_pct', float),
    ('avg_gain_pct', float),
    ('avg_loss_pct', float),
    ('max_drawdown_pct', float),
    ('sharpe_ratio', float),
    ('total_trades', int),
    ('winning_trades', int),
    ('losing_trades', int),
])

def _simulate(bars: list[dict], symbol: str, portfolio_value: float = 10_000.0) -> SymbolResult
def _fetch_bars(symbol: str, days: int, api_key: str, secret_key: str) -> list[dict]
def run_backtest(symbol: str, days: int, api_key: str, secret_key: str) -> SymbolResult
def run_full_backtest(symbols: list[str], days: int, api_key: str, secret_key: str) -> dict[str, SymbolResult]
```

Each bar dict has keys: `'open'`, `'high'`, `'low'`, `'close'` — all floats.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_backtester.py`:

```python
import pytest
import core.backtester as bt


def _flat_bars(n: int, price: float = 100.0) -> list[dict]:
    """n independent bar dicts all at the same price."""
    return [
        {"open": price, "high": price * 1.001, "low": price * 0.999, "close": price}
        for _ in range(n)
    ]


def _bar(open_: float, high: float, low: float, close: float) -> dict:
    return {"open": open_, "high": high, "low": low, "close": close}


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
    bars = _flat_bars(200, 100.0)
    bars[101] = _bar(100.0, 101.0, 99.0, 100.0)
    bars[110] = _bar(114.0, 116.0, 113.0, 115.0)  # high=116 >= tp=115
    result = bt._simulate(bars, "TEST")
    assert result.total_trades == 1
    assert result.winning_trades == 1
    assert result.losing_trades == 0
    assert result.win_rate_pct == 100.0
    assert result.avg_gain_pct == pytest.approx(15.0, rel=0.01)


def test_simulate_sl_hit(monkeypatch):
    """Signal at bar 100 -> fill at bar 101 open=100.0 -> SL hit at bar 110 low=91.0."""
    calls = [0]
    def mock_sig(*a):
        calls[0] += 1
        return "STRONG_BUY" if calls[0] == 1 else "HOLD"
    monkeypatch.setattr(bt, "rsi", lambda *a, **k: 50.0)
    monkeypatch.setattr(bt, "macd", lambda *a, **k: type("M", (), {"histogram": 0.0})())
    monkeypatch.setattr(bt, "classify_signal", mock_sig)
    bars = _flat_bars(200, 100.0)
    bars[101] = _bar(100.0, 101.0, 99.0, 100.0)
    bars[110] = _bar(93.0, 93.5, 91.0, 92.0)  # low=91 <= sl=92
    result = bt._simulate(bars, "TEST")
    assert result.total_trades == 1
    assert result.winning_trades == 0
    assert result.losing_trades == 1
    assert result.win_rate_pct == 0.0
    assert result.avg_loss_pct == pytest.approx(8.0, rel=0.01)


def test_simulate_benchmark_return():
    """buy-and-hold return = (last_close - first_close) / first_close * 100."""
    bars = _flat_bars(200, 100.0)
    bars[-1] = _bar(150.0, 151.0, 149.0, 150.0)
    # flat bars at 100 -> RSI=100 -> AMBIGUOUS_SELL -> no STRONG_BUY -> 0 trades
    result = bt._simulate(bars, "TEST")
    assert result.benchmark_return_pct == pytest.approx(50.0, rel=0.01)
    assert result.total_trades == 0
```

- [ ] **Step 2: Run tests to confirm they fail**

```
cd "C:\claude proj\el_fager"
python -m pytest tests/test_backtester.py -v
```

Expected: ImportError or collection errors — `core.backtester` does not exist yet.

- [ ] **Step 3: Write `core/backtester.py`**

```python
"""
Backtesting engine — replays Alpaca hourly bars and simulates the trading strategy.
Pure simulation logic (_simulate, helpers) is free of API calls and fully unit-testable.
Alpaca imports are deferred inside _fetch_bars / run_backtest / run_full_backtest.
"""
from typing import NamedTuple

from core.signals import rsi, macd, classify_signal, SignalStrength
from core.risk_manager import calc_position_size, get_stop_loss_price, get_take_profit_price

_MIN_BARS = 100  # minimum history bars before signal computation begins


SymbolResult = NamedTuple('SymbolResult', [
    ('symbol', str),
    ('total_return_pct', float),
    ('benchmark_return_pct', float),
    ('win_rate_pct', float),
    ('avg_gain_pct', float),
    ('avg_loss_pct', float),
    ('max_drawdown_pct', float),
    ('sharpe_ratio', float),
    ('total_trades', int),
    ('winning_trades', int),
    ('losing_trades', int),
])


def _max_drawdown(values: list[float]) -> float:
    """Return max peak-to-trough drop as a positive percentage."""
    if len(values) < 2:
        return 0.0
    peak = values[0]
    max_dd = 0.0
    for v in values:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (peak - v) / peak * 100
            if dd > max_dd:
                max_dd = dd
    return max_dd


def _sharpe(values: list[float]) -> float:
    """Annualized Sharpe ratio from a bar-level portfolio value series."""
    if len(values) < 2:
        return 0.0
    returns = [
        (values[i] - values[i - 1]) / values[i - 1]
        for i in range(1, len(values))
        if values[i - 1] != 0
    ]
    if len(returns) < 2:
        return 0.0
    n = len(returns)
    mean_r = sum(returns) / n
    variance = sum((r - mean_r) ** 2 for r in returns) / (n - 1)
    std_r = variance ** 0.5
    if std_r == 0:
        return 0.0
    annualization = (252 * 6.5) ** 0.5  # hourly bars: 6.5 trading hours/day
    return round(mean_r / std_r * annualization, 2)


def _simulate(
    bars: list[dict],
    symbol: str,
    portfolio_value: float = 10_000.0,
) -> SymbolResult:
    """
    Pure simulation. bars is a chronological list of {open, high, low, close} dicts.
    No API calls. Fully unit-testable.

    Fill rule: buy at NEXT bar's open (pending_entry flag).
    Exit rule: check bar's low vs SL and bar's high vs TP each bar.
    """
    _empty = SymbolResult(
        symbol=symbol, total_return_pct=0.0, benchmark_return_pct=0.0,
        win_rate_pct=0.0, avg_gain_pct=0.0, avg_loss_pct=0.0,
        max_drawdown_pct=0.0, sharpe_ratio=0.0,
        total_trades=0, winning_trades=0, losing_trades=0,
    )
    if len(bars) <= _MIN_BARS:
        return _empty

    cash = portfolio_value
    open_pos: dict | None = None
    pending_entry = False
    trade_pnls: list[float] = []
    portfolio_values: list[float] = [portfolio_value]

    for i in range(_MIN_BARS, len(bars)):
        bar = bars[i]

        # Execute pending entry at this bar's open
        if pending_entry and open_pos is None:
            fill_price = bar['open']
            qty = calc_position_size(cash, fill_price)
            if qty > 0:
                cash -= qty * fill_price
                open_pos = {
                    'entry_price': fill_price,
                    'sl_price': get_stop_loss_price(fill_price),
                    'tp_price': get_take_profit_price(fill_price),
                    'qty': qty,
                }
            pending_entry = False

        # Check SL / TP
        if open_pos is not None:
            if bar['low'] <= open_pos['sl_price']:
                pnl = (open_pos['sl_price'] - open_pos['entry_price']) / open_pos['entry_price'] * 100
                cash += open_pos['qty'] * open_pos['sl_price']
                trade_pnls.append(pnl)
                open_pos = None
            elif bar['high'] >= open_pos['tp_price']:
                pnl = (open_pos['tp_price'] - open_pos['entry_price']) / open_pos['entry_price'] * 100
                cash += open_pos['qty'] * open_pos['tp_price']
                trade_pnls.append(pnl)
                open_pos = None

        # Check for new signal when flat and not the last bar
        if open_pos is None and not pending_entry and i < len(bars) - 1:
            window = [b['close'] for b in bars[i - _MIN_BARS:i]]
            rsi_val = rsi(window)
            macd_result = macd(window)
            signal = classify_signal(window, rsi_val, macd_result)
            if signal == SignalStrength.STRONG_BUY:
                pending_entry = True

        # Record portfolio value for metrics
        pos_val = open_pos['qty'] * bar['close'] if open_pos is not None else 0.0
        portfolio_values.append(cash + pos_val)

    # Close remaining open position at last bar's close
    if open_pos is not None:
        last_price = bars[-1]['close']
        pnl = (last_price - open_pos['entry_price']) / open_pos['entry_price'] * 100
        cash += open_pos['qty'] * last_price
        trade_pnls.append(pnl)

    # Compute final metrics
    total_trades = len(trade_pnls)
    winning = [p for p in trade_pnls if p > 0]
    losing = [p for p in trade_pnls if p <= 0]
    win_rate = len(winning) / total_trades * 100 if total_trades > 0 else 0.0
    avg_gain = sum(winning) / len(winning) if winning else 0.0
    avg_loss = abs(sum(losing) / len(losing)) if losing else 0.0

    final_value = portfolio_values[-1]
    total_return = (final_value - portfolio_value) / portfolio_value * 100
    benchmark_return = (bars[-1]['close'] - bars[0]['close']) / bars[0]['close'] * 100

    return SymbolResult(
        symbol=symbol,
        total_return_pct=round(total_return, 2),
        benchmark_return_pct=round(benchmark_return, 2),
        win_rate_pct=round(win_rate, 1),
        avg_gain_pct=round(avg_gain, 2),
        avg_loss_pct=round(avg_loss, 2),
        max_drawdown_pct=round(_max_drawdown(portfolio_values), 2),
        sharpe_ratio=_sharpe(portfolio_values),
        total_trades=total_trades,
        winning_trades=len(winning),
        losing_trades=len(losing),
    )


def _fetch_bars(symbol: str, days: int, api_key: str, secret_key: str) -> list[dict]:
    """Fetch hourly OHLCV bars from Alpaca for the past `days` days."""
    from datetime import datetime, timedelta, timezone
    from alpaca.data.historical.stock import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    client = StockHistoricalDataClient(api_key, secret_key)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    req = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame.Hour,
        start=start,
        end=end,
    )
    try:
        bars_resp = client.get_stock_bars(req)
        df = bars_resp.df
    except Exception:
        return []
    if df.empty:
        return []
    df = df.reset_index()
    if 'symbol' in df.columns:
        df = df[df['symbol'] == symbol]
    if 'timestamp' in df.columns:
        df = df.sort_values('timestamp')
    result = []
    for _, row in df.iterrows():
        result.append({
            'open': float(row['open']),
            'high': float(row['high']),
            'low': float(row['low']),
            'close': float(row['close']),
        })
    return result


def run_backtest(symbol: str, days: int, api_key: str, secret_key: str) -> SymbolResult:
    """Fetch bars and simulate the strategy for one symbol."""
    return _simulate(_fetch_bars(symbol, days, api_key, secret_key), symbol)


def run_full_backtest(
    symbols: list[str],
    days: int,
    api_key: str,
    secret_key: str,
) -> dict[str, SymbolResult]:
    """Run backtest for each symbol and return a mapping of symbol -> SymbolResult."""
    return {sym: _simulate(_fetch_bars(sym, days, api_key, secret_key), sym) for sym in symbols}
```

- [ ] **Step 4: Run tests — expect all 8 to pass**

```
python -m pytest tests/test_backtester.py -v
```

Expected output (8 passed):
```
tests/test_backtester.py::test_max_drawdown_basic PASSED
tests/test_backtester.py::test_max_drawdown_no_drawdown PASSED
tests/test_backtester.py::test_sharpe_positive_returns PASSED
tests/test_backtester.py::test_sharpe_no_variance PASSED
tests/test_backtester.py::test_simulate_insufficient_bars PASSED
tests/test_backtester.py::test_simulate_no_signals PASSED
tests/test_backtester.py::test_simulate_tp_hit PASSED
tests/test_backtester.py::test_simulate_sl_hit PASSED
tests/test_backtester.py::test_simulate_benchmark_return PASSED
========== 9 passed in ...s ==========
```

(9 tests — count in the file above.)

- [ ] **Step 5: Also run existing tests to confirm nothing broke**

```
python -m pytest tests/test_signals.py tests/test_risk_manager.py -v
```

Expected: 26 passed.

- [ ] **Step 6: Commit**

```
git add core/backtester.py tests/test_backtester.py
git commit -m "feat: add backtesting engine with simulation, metrics, and Alpaca data fetch"
```

---

### Task 2: tools/backtest_tool.py — Jarvis Tool Interface

**Files:**
- Create: `tools/backtest_tool.py`
- Create (test): `tests/test_backtest_tool.py`

**Interfaces consumed (from Task 1):**
```python
from core.backtester import run_backtest, run_full_backtest, SymbolResult
```

**Interfaces produced (Task 3 consumes these function names):**
```python
def run_backtest(symbol: str = "SPY", days: int = 730) -> str
def run_full_backtest() -> str
def get_backtest_results() -> str
def compare_to_buyhold(symbol: str) -> str
```

Note: `tools/backtest_tool.py` exports functions with the same names as `core/backtester.py`. The tool layer uses lazy imports (`from core.backtester import ... as _fn`) to avoid naming collisions at module level.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_backtest_tool.py`:

```python
import json
import pytest
from unittest.mock import patch
from pathlib import Path
import tools.backtest_tool as tool
from core.backtester import SymbolResult

_SAMPLE = SymbolResult(
    symbol="SPY",
    total_return_pct=34.2,
    benchmark_return_pct=28.1,
    win_rate_pct=61.0,
    avg_gain_pct=12.3,
    avg_loss_pct=6.1,
    max_drawdown_pct=14.2,
    sharpe_ratio=1.4,
    total_trades=23,
    winning_trades=14,
    losing_trades=9,
)


def test_run_backtest_no_keys(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "your_alpaca_key_here")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "your_secret_here")
    assert "not configured" in tool.run_backtest("SPY")


def test_run_backtest_success(monkeypatch, tmp_path):
    monkeypatch.setenv("ALPACA_API_KEY", "PKTEST123")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "SKTEST456")
    monkeypatch.setattr(tool, "_RESULTS_PATH", tmp_path / "results.json")
    with patch("core.backtester.run_backtest", return_value=_SAMPLE):
        result = tool.run_backtest("SPY")
    assert "34.2" in result
    assert "28.1" in result
    assert "outperforms" in result
    assert "61" in result


def test_get_backtest_results_no_file(monkeypatch, tmp_path):
    monkeypatch.setattr(tool, "_RESULTS_PATH", tmp_path / "nonexistent.json")
    assert "No backtest results" in tool.get_backtest_results()


def test_compare_to_buyhold_outperforms(monkeypatch, tmp_path):
    p = tmp_path / "results.json"
    p.write_text(json.dumps({
        "SPY": {
            "total_return_pct": 34.2, "benchmark_return_pct": 28.1,
            "win_rate_pct": 61.0, "avg_gain_pct": 12.3, "avg_loss_pct": 6.1,
            "max_drawdown_pct": 14.2, "sharpe_ratio": 1.4,
            "total_trades": 23, "winning_trades": 14, "losing_trades": 9,
        }
    }), encoding="utf-8")
    monkeypatch.setattr(tool, "_RESULTS_PATH", p)
    result = tool.compare_to_buyhold("SPY")
    assert "outperforms" in result
    assert "6.1" in result


def test_compare_to_buyhold_missing_symbol(monkeypatch, tmp_path):
    p = tmp_path / "results.json"
    p.write_text(json.dumps({"SPY": {}}), encoding="utf-8")
    monkeypatch.setattr(tool, "_RESULTS_PATH", p)
    result = tool.compare_to_buyhold("TSLA")
    assert "TSLA" in result
    assert "run_backtest" in result
```

- [ ] **Step 2: Run tests — confirm they fail**

```
python -m pytest tests/test_backtest_tool.py -v
```

Expected: ImportError — `tools.backtest_tool` does not exist yet.

- [ ] **Step 3: Write `tools/backtest_tool.py`**

```python
"""
Backtest tool — 4 Jarvis voice commands for strategy backtesting.
Wraps core/backtester.py and persists results to data/backtest_results.json.
"""
import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

_RESULTS_PATH = Path("data/backtest_results.json")
_PLACEHOLDER = "your_alpaca_key_here"


def _api_keys() -> tuple[str, str]:
    return os.getenv("ALPACA_API_KEY", ""), os.getenv("ALPACA_SECRET_KEY", "")


def _keys_configured() -> bool:
    key, secret = _api_keys()
    return bool(key) and key != _PLACEHOLDER and bool(secret)


def _save_results(symbol: str, result) -> None:
    _RESULTS_PATH.parent.mkdir(exist_ok=True)
    data: dict = {}
    if _RESULTS_PATH.exists():
        try:
            data = json.loads(_RESULTS_PATH.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data[symbol] = {
        "total_return_pct": result.total_return_pct,
        "benchmark_return_pct": result.benchmark_return_pct,
        "win_rate_pct": result.win_rate_pct,
        "avg_gain_pct": result.avg_gain_pct,
        "avg_loss_pct": result.avg_loss_pct,
        "max_drawdown_pct": result.max_drawdown_pct,
        "sharpe_ratio": result.sharpe_ratio,
        "total_trades": result.total_trades,
        "winning_trades": result.winning_trades,
        "losing_trades": result.losing_trades,
    }
    import datetime
    data["_run_at"] = datetime.datetime.now().isoformat()
    _RESULTS_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def run_backtest(symbol: str = "SPY", days: int = 730) -> str:
    """Backtest the trading strategy on historical data for one symbol."""
    if not _keys_configured():
        return "Alpaca API keys not configured. Add ALPACA_API_KEY and ALPACA_SECRET_KEY to .env first."
    key, secret = _api_keys()
    from core.backtester import run_backtest as _run
    result = _run(symbol.upper(), days, key, secret)
    _save_results(symbol.upper(), result)
    if result.total_trades == 0:
        return (
            f"Backtest for {symbol.upper()} over {days} days completed with no trades fired. "
            f"Strategy signals may be too strict or data insufficient."
        )
    direction = "outperforms" if result.total_return_pct > result.benchmark_return_pct else "underperforms"
    years = days // 365
    return (
        f"Backtest complete for {symbol.upper()} over {years} year{'s' if years != 1 else ''}. "
        f"Strategy returned {result.total_return_pct:.1f}% vs buy-and-hold {result.benchmark_return_pct:.1f}% "
        f"-- strategy {direction} the benchmark. "
        f"Win rate {result.win_rate_pct:.0f}%, average gain {result.avg_gain_pct:.1f}%, "
        f"average loss {result.avg_loss_pct:.1f}%. "
        f"Max drawdown {result.max_drawdown_pct:.1f}%. Sharpe ratio {result.sharpe_ratio:.1f}. "
        f"{result.total_trades} trades executed. Results saved."
    )


def run_full_backtest() -> str:
    """Backtest the strategy across all active symbols and report combined results."""
    if not _keys_configured():
        return "Alpaca API keys not configured. Add ALPACA_API_KEY and ALPACA_SECRET_KEY to .env first."
    config_path = Path("data/trading_config.json")
    symbols = ["SPY", "QQQ", "AAPL", "NVDA", "MSFT"]
    if config_path.exists():
        try:
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
            symbols = cfg.get("active_symbols", symbols)
        except Exception:
            pass
    key, secret = _api_keys()
    from core.backtester import run_full_backtest as _run
    results = _run(symbols, 730, key, secret)
    for sym, result in results.items():
        _save_results(sym, result)
    if not results:
        return "Full backtest returned no results."
    best = max(results, key=lambda s: results[s].total_return_pct)
    worst = min(results, key=lambda s: results[s].total_return_pct)
    avg_sharpe = round(sum(r.sharpe_ratio for r in results.values()) / len(results), 1)
    avg_return = round(sum(r.total_return_pct for r in results.values()) / len(results), 1)
    return (
        f"Full backtest across {len(symbols)} symbols complete. "
        f"Best performer: {best} at {results[best].total_return_pct:.1f}% return. "
        f"Worst performer: {worst} at {results[worst].total_return_pct:.1f}% return. "
        f"Average return {avg_return:.1f}%, average Sharpe {avg_sharpe:.1f}. "
        f"Full breakdown saved."
    )


def get_backtest_results() -> str:
    """Return last saved backtest results as readable text."""
    if not _RESULTS_PATH.exists():
        return "No backtest results saved yet. Run run_backtest or run_full_backtest first."
    try:
        data = json.loads(_RESULTS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return "Backtest results file exists but could not be read."
    run_at = data.pop("_run_at", "unknown time")
    if not data:
        return "No symbol results in backtest file."
    lines = [f"Backtest results (run at {run_at}):"]
    for sym, r in data.items():
        direction = "outperforms" if r['total_return_pct'] > r['benchmark_return_pct'] else "underperforms"
        lines.append(
            f"  {sym}: strategy {r['total_return_pct']:.1f}% vs buy-and-hold "
            f"{r['benchmark_return_pct']:.1f}% ({direction}). "
            f"Win rate {r['win_rate_pct']:.0f}%, Sharpe {r['sharpe_ratio']:.1f}, "
            f"max drawdown {r['max_drawdown_pct']:.1f}%, {r['total_trades']} trades."
        )
    return "\n".join(lines)


def compare_to_buyhold(symbol: str) -> str:
    """Compare strategy return vs simply holding the symbol over the backtest period."""
    if not _RESULTS_PATH.exists():
        return f"No backtest results found. Run run_backtest('{symbol.upper()}') first."
    try:
        data = json.loads(_RESULTS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return "Could not read backtest results."
    sym = symbol.upper()
    if sym not in data:
        return f"No backtest results for {sym}. Run run_backtest('{sym}') first."
    r = data[sym]
    diff = round(r['total_return_pct'] - r['benchmark_return_pct'], 1)
    if diff > 0:
        verdict = (
            f"Strategy outperforms buy-and-hold by {diff} percentage points "
            f"-- active trading adds value on {sym}."
        )
    elif diff < 0:
        verdict = (
            f"Strategy underperforms buy-and-hold by {abs(diff)} percentage points "
            f"-- consider removing {sym} from the watchlist."
        )
    else:
        verdict = f"Strategy matches buy-and-hold exactly on {sym}."
    return (
        f"{sym}: strategy {r['total_return_pct']:.1f}% vs buy-and-hold "
        f"{r['benchmark_return_pct']:.1f}%. {verdict}"
    )
```

- [ ] **Step 4: Run tests — expect all 5 to pass**

```
python -m pytest tests/test_backtest_tool.py -v
```

Expected:
```
tests/test_backtest_tool.py::test_run_backtest_no_keys PASSED
tests/test_backtest_tool.py::test_run_backtest_success PASSED
tests/test_backtest_tool.py::test_get_backtest_results_no_file PASSED
tests/test_backtest_tool.py::test_compare_to_buyhold_outperforms PASSED
tests/test_backtest_tool.py::test_compare_to_buyhold_missing_symbol PASSED
========== 5 passed in ...s ==========
```

- [ ] **Step 5: Run full test suite**

```
python -m pytest tests/ -v
```

Expected: all previous 26 + 9 + 5 = 40 passed (or 9+5+26 in whatever order pytest discovers them).

- [ ] **Step 6: Commit**

```
git add tools/backtest_tool.py tests/test_backtest_tool.py
git commit -m "feat: add backtest_tool.py with 4 Jarvis voice commands for strategy backtesting"
```

---

### Task 3: core/brain.py — Register 4 Backtest Tools

**Files:**
- Modify: `core/brain.py`

**No new tests required.** Verify the file imports cleanly with `python -c "import core.brain"`.

This task makes 5 additive edits to `core/brain.py`. Nothing is removed.

**Context:** The file currently has ~5900 lines. All edits are appends/insertions at specific anchor points. The anchor strings below are unique in the file — use them exactly.

- [ ] **Step 1: SYSTEM_PROMPT — add backtest routing block**

Find this exact line in SYSTEM_PROMPT (currently the last line of the trading block):
```
All trading reports are exceptions to the 1-2 sentence rule — deliver the full report.
```

Insert AFTER it (same indentation, before the closing `"""`):

```
- For backtesting and strategy validation: use run_backtest(symbol, days), run_full_backtest(), get_backtest_results(), compare_to_buyhold(symbol). Backtest reports are exceptions to the 1-2 sentence rule.
- When Mo says "backtest SPY" or "test the strategy" -> run_backtest(symbol).
- When Mo says "backtest all symbols" or "full backtest" -> run_full_backtest().
- When Mo says "backtest results" or "how did the strategy do?" -> get_backtest_results().
- When Mo says "compare to buy and hold [TICKER]" -> compare_to_buyhold(symbol).
```

- [ ] **Step 2: TOOLS list — append 4 schemas**

Find this exact block (end of the trading tools section):
```python
        {
            "name": "remove_trading_symbol",
            "description": "Remove a ticker symbol from the active trading watchlist.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Ticker to remove (e.g. 'TSLA')"},
                },
                "required": ["symbol"],
            },
        },
```

Append AFTER it (still inside the TOOLS list):

```python
        {
            "name": "run_backtest",
            "description": "Backtest the trading strategy on 2 years of hourly historical data for one symbol. Returns total return, win rate, avg gain/loss, max drawdown, Sharpe ratio vs buy-and-hold.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Stock ticker (e.g. 'SPY', 'AAPL'). Default 'SPY'."},
                    "days": {"type": "integer", "description": "Days of history to test. Default 730 (2 years)."},
                },
                "required": [],
            },
        },
        {
            "name": "run_full_backtest",
            "description": "Backtest the strategy across all 5 active watchlist symbols and report combined results.",
            "input_schema": {"type": "object", "properties": {}, "required": []},
        },
        {
            "name": "get_backtest_results",
            "description": "Return the last saved backtest results for all symbols that have been tested.",
            "input_schema": {"type": "object", "properties": {}, "required": []},
        },
        {
            "name": "compare_to_buyhold",
            "description": "Compare strategy return vs simply buying and holding a symbol. Shows whether active trading adds value.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Ticker to compare (e.g. 'AAPL')."},
                },
                "required": ["symbol"],
            },
        },
```

- [ ] **Step 3: _TOOL_GROUP_NAMES — add "backtest" frozenset**

Find this exact block:
```python
    "trading": frozenset({
        "start_trading_engine", "stop_trading_engine", "get_trading_status",
        "get_trading_portfolio", "get_trade_history", "get_trading_summary",
```

Insert AFTER the closing `}),` of the entire "trading" frozenset:

```python
    "backtest": frozenset({
        "run_backtest", "run_full_backtest", "get_backtest_results", "compare_to_buyhold",
    }),
```

- [ ] **Step 4: _GROUP_TRIGGERS — add "backtest" trigger list**

Find this exact line:
```python
    "trading":    ["start trading", "stop trading", "trading engine", "trading status",
```

Insert AFTER the closing `],` of the entire "trading" list:

```python
    "backtest":   ["backtest", "test strategy", "how is the strategy", "strategy performance",
                   "did the strategy work", "historical performance", "backtest results",
                   "strategy test", "how did the strategy do", "compare to buy and hold",
                   "buy and hold", "اختبار الاستراتيجية"],
```

- [ ] **Step 5: _dispatch_tool — add 4 elif cases**

Find this exact block (last trading dispatch case + else):
```python
            elif name == "remove_trading_symbol":
                from tools.trading_tool import remove_trading_symbol
                return remove_trading_symbol(**tool_input)
            else:
                return f"Unknown tool: {name}"
```

Replace with:

```python
            elif name == "remove_trading_symbol":
                from tools.trading_tool import remove_trading_symbol
                return remove_trading_symbol(**tool_input)
            elif name == "run_backtest":
                from tools.backtest_tool import run_backtest as _run_bt
                return _run_bt(**tool_input)
            elif name == "run_full_backtest":
                from tools.backtest_tool import run_full_backtest as _run_fbt
                return _run_fbt()
            elif name == "get_backtest_results":
                from tools.backtest_tool import get_backtest_results as _get_bt
                return _get_bt()
            elif name == "compare_to_buyhold":
                from tools.backtest_tool import compare_to_buyhold as _compare_bt
                return _compare_bt(**tool_input)
            else:
                return f"Unknown tool: {name}"
```

- [ ] **Step 6: Verify brain.py imports cleanly**

```
python -c "import core.brain; print('brain ok')"
```

Expected: `brain ok` with no errors.

- [ ] **Step 7: Run full test suite one final time**

```
python -m pytest tests/ -v
```

Expected: all 40 tests pass (26 original + 9 backtester + 5 backtest_tool).

- [ ] **Step 8: Commit**

```
git add core/brain.py
git commit -m "feat: register 4 backtest tools in brain.py (SYSTEM_PROMPT, TOOLS, routing, dispatch)"
```

---

## Self-Review Checklist

**Spec coverage:**
- [x] `core/backtester.py` — simulation engine with bar replay: Task 1
- [x] `tools/backtest_tool.py` — 4 Jarvis tools: Task 2
- [x] `data/backtest_results.json` — persisted results (gitignored): Task 2
- [x] `core/brain.py` — SYSTEM_PROMPT + TOOLS + routing + dispatch: Task 3
- [x] Starting capital $10,000: Task 1 `_simulate(portfolio_value=10_000.0)`
- [x] Fill at next bar's open (`pending_entry` flag): Task 1
- [x] SL -8% / TP +15%: delegated to `get_stop_loss_price` / `get_take_profit_price`
- [x] Buy-and-hold benchmark per symbol: `benchmark_return = (bars[-1]['close'] - bars[0]['close']) / bars[0]['close'] * 100`
- [x] 5 metrics: total_return, win_rate, avg_gain/loss, max_drawdown, Sharpe: Task 1
- [x] No Claude consultation in backtest: `_simulate` never calls Anthropic API
- [x] cp1252 safety: all return strings use `--` not `->`, no emojis or Arabic
- [x] Alpaca imports deferred inside `_fetch_bars` / `run_backtest` / `run_full_backtest`
- [x] Python 3.14 types throughout: `list[dict]`, `dict[str, SymbolResult]`, `tuple[str, str]`

**Placeholder scan:** None found.

**Type consistency:**
- `SymbolResult` defined in Task 1, consumed in Task 2 (`from core.backtester import SymbolResult`)
- `run_backtest` / `run_full_backtest` in core exported with exact matching names imported in tool layer via `as _run` aliases
- `_RESULTS_PATH` is a `Path` object — `monkeypatch.setattr(tool, "_RESULTS_PATH", tmp_path / "x.json")` correctly overrides it in tests
