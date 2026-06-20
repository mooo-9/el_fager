# Jarvis Investment Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire an autonomous 15-minute Alpaca paper-trading engine into El Fager so Jarvis monitors 5 US stocks, generates buy/sell signals via RSI+MACD, consults Claude for ambiguous signals, and executes bracket orders with hard risk guardrails.

**Architecture:** Four new files (`core/signals.py`, `core/risk_manager.py`, `core/trading_engine.py`, `tools/trading_tool.py`) plug into the existing architecture with zero changes to existing tools. `main.py` gets one line to wire the speak callback. `brain.py` gets new tool schemas, routing, and dispatch entries.

**Tech Stack:** `alpaca-py` SDK (Alpaca paper/live trading), `zoneinfo` stdlib (market hours, Python 3.14), `anthropic` SDK already installed, `python-dotenv` already installed.

## Global Constraints

- Python 3.14 — use `zoneinfo` not `pytz`. Use `list[float]` not `List[float]`. Use `X | None` not `Optional[X]`.
- All cp1252-safe strings in tool return values: no `→`, `⚠`, `⭐`, emojis, Arabic in return strings.
- Claude model: `claude-sonnet-4-6` (never change).
- Data files: `data/` directory, UTF-8, JSON. Always `path.parent.mkdir(exist_ok=True)` before writes.
- Paper mode by default — `ALPACA_MODE=paper` in `.env`. Live mode requires double confirmation.
- Bracket orders handle stop-loss/take-profit server-side — never add client-side exit polling.
- `_slim_tools(TOOLS)` auto-generates `_SLIM_TOOLS` — only update the `TOOLS` list in brain.py.
- Working directory when running: `C:\claude proj\el_fager` (all relative paths assume this).

---

## File Map

| File | Status | Responsibility |
|---|---|---|
| `core/signals.py` | **Create** | RSI(14), MACD(12,26,9), EMA(n), signal classification |
| `core/risk_manager.py` | **Create** | Position sizing, stop-loss/take-profit prices, daily circuit breaker |
| `core/trading_engine.py` | **Create** | 15-min background loop, Alpaca API, Claude consultation, TTS |
| `tools/trading_tool.py` | **Create** | 11 Jarvis-facing tool functions + speak callback registration |
| `tests/test_signals.py` | **Create** | Unit tests for signals.py (pure logic, no API calls) |
| `tests/test_risk_manager.py` | **Create** | Unit tests for risk_manager.py (pure logic, no API calls) |
| `data/trading_config.json` | **Create** | Default config (created at first start if missing) |
| `requirements.txt` | **Modify** | Add `alpaca-py>=0.8.2` |
| `.env` | **Modify** | Add `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, `ALPACA_MODE=paper` |
| `main.py` | **Modify** | Call `set_trading_speak_callback(voice_out.speak)` at startup |
| `core/brain.py` | **Modify** | SYSTEM_PROMPT section, TOOLS schemas, `_TOOL_GROUP_NAMES`, `_GROUP_TRIGGERS`, `_dispatch_tool` |

---

## Task 1: Dependencies & Environment Setup

**Files:**
- Modify: `requirements.txt`
- Modify: `.env`
- Create: `tests/__init__.py` (empty)
- Create: `data/trading_config.json`

**Interfaces:**
- Produces: `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, `ALPACA_MODE` env vars available to all subsequent tasks

- [ ] **Step 1: Install alpaca-py**

```powershell
cd "C:\claude proj\el_fager"
pip install "alpaca-py>=0.8.2"
```

Expected output includes: `Successfully installed alpaca-py-...`

- [ ] **Step 2: Add alpaca-py to requirements.txt**

Add at the end of `requirements.txt` (after the last entry):

```
# Phase 10 — Autonomous Trading Engine
alpaca-py>=0.8.2
```

- [ ] **Step 3: Add Alpaca env vars to .env**

Append to `.env`:

```
# Phase 10 — Alpaca Trading
# Get free paper-trading keys at alpaca.markets → sign up → API Keys
ALPACA_API_KEY=your_alpaca_key_here
ALPACA_SECRET_KEY=your_alpaca_secret_here
# paper = Alpaca sandbox (fake money, real market data) | live = real money
ALPACA_MODE=paper
```

- [ ] **Step 4: Create tests directory**

```powershell
New-Item -ItemType Directory -Force "C:\claude proj\el_fager\tests"
New-Item -ItemType File "C:\claude proj\el_fager\tests\__init__.py"
```

- [ ] **Step 5: Create default data/trading_config.json**

Create `data/trading_config.json`:

```json
{
  "mode": "paper",
  "active_symbols": ["SPY", "QQQ", "AAPL", "NVDA", "MSFT"],
  "max_position_pct": 10,
  "stop_loss_pct": 8,
  "take_profit_pct": 15,
  "daily_loss_limit_pct": 5,
  "max_open_positions": 5,
  "cycle_interval_minutes": 15
}
```

- [ ] **Step 6: Verify alpaca-py import works**

```powershell
python -c "from alpaca.trading.client import TradingClient; from alpaca.data.historical.stock import StockHistoricalDataClient; print('alpaca-py OK')"
```

Expected: `alpaca-py OK`

- [ ] **Step 7: Commit**

```powershell
git add requirements.txt .env data/trading_config.json tests/__init__.py
git commit -m "chore: add alpaca-py dep, env vars, tests dir, default trading config"
```

---

## Task 2: core/signals.py — Technical Indicators

**Files:**
- Create: `core/signals.py`
- Create: `tests/test_signals.py`

**Interfaces:**
- Produces:
  - `ema(prices: list[float], period: int) -> list[float | None]`
  - `rsi(prices: list[float], period: int = 14) -> float | None`
  - `MACDResult(macd: float, signal: float, histogram: float)` — NamedTuple
  - `macd(prices: list[float], fast: int = 12, slow: int = 26, signal_period: int = 9) -> MACDResult | None`
  - `SignalStrength.STRONG_BUY`, `.STRONG_SELL`, `.AMBIGUOUS_BUY`, `.AMBIGUOUS_SELL`, `.HOLD` — string constants
  - `classify_signal(closes: list[float], rsi_value: float | None, macd_result: MACDResult | None) -> str`
- Consumed by: `core/trading_engine.py` (Task 5)

- [ ] **Step 1: Write failing tests**

Create `tests/test_signals.py`:

```python
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
```

- [ ] **Step 2: Run tests — verify they FAIL (ImportError)**

```powershell
python -m pytest tests/test_signals.py -v 2>&1 | Select-Object -First 20
```

Expected: `ImportError` or `ModuleNotFoundError: No module named 'core.signals'`

- [ ] **Step 3: Create core/signals.py**

```python
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

    if rsi_value < 28 and macd_bullish and price_above_ema20:
        return SignalStrength.STRONG_BUY
    if rsi_value > 72 and macd_bearish and price_below_ema20:
        return SignalStrength.STRONG_SELL
    if rsi_value < 35:
        return SignalStrength.AMBIGUOUS_BUY
    if rsi_value > 65:
        return SignalStrength.AMBIGUOUS_SELL
    return SignalStrength.HOLD
```

- [ ] **Step 4: Run tests — verify they PASS**

```powershell
python -m pytest tests/test_signals.py -v
```

Expected: `14 passed` — all green.

- [ ] **Step 5: Commit**

```powershell
git add core/signals.py tests/test_signals.py
git commit -m "feat: add signals.py with RSI, MACD, EMA, classify_signal"
```

---

## Task 3: core/risk_manager.py — Risk Guardrails

**Files:**
- Create: `core/risk_manager.py`
- Create: `tests/test_risk_manager.py`

**Interfaces:**
- Consumes: `data/trading_config.json` (must exist or defaults apply)
- Produces:
  - `can_open_position(open_positions_count: int) -> tuple[bool, str]`
  - `calc_position_size(portfolio_value: float, price_per_share: float) -> float`
  - `get_stop_loss_price(entry_price: float) -> float`
  - `get_take_profit_price(entry_price: float) -> float`
  - `is_daily_limit_hit(portfolio_value: float, day_open_value: float) -> bool`
- Consumed by: `core/trading_engine.py` (Task 5)

- [ ] **Step 1: Write failing tests**

Create `tests/test_risk_manager.py`:

```python
"""Unit tests for core/risk_manager.py — pure logic, no file I/O."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import core.risk_manager as rm

_TEST_CFG = {
    "max_position_pct": 10,
    "stop_loss_pct": 8,
    "take_profit_pct": 15,
    "daily_loss_limit_pct": 5,
    "max_open_positions": 5,
}


def _patch(cfg=None):
    data = cfg or _TEST_CFG
    rm._load_config = lambda: data


def test_calc_position_size_basic():
    _patch()
    # 10% of $1000 at $100/share = 1.0 share
    assert abs(rm.calc_position_size(1000.0, 100.0) - 1.0) < 0.001


def test_calc_position_size_fractional():
    _patch()
    # 10% of $500 at $450/share = $50/$450 ~ 0.111
    qty = rm.calc_position_size(500.0, 450.0)
    assert 0.10 < qty < 0.12


def test_get_stop_loss_price():
    _patch()
    # entry $100, stop 8% -> $92
    assert abs(rm.get_stop_loss_price(100.0) - 92.0) < 0.01


def test_get_take_profit_price():
    _patch()
    # entry $100, tp 15% -> $115
    assert abs(rm.get_take_profit_price(100.0) - 115.0) < 0.01


def test_can_open_position_allows_when_under_limit():
    _patch()
    allowed, msg = rm.can_open_position(3)
    assert allowed is True
    assert msg == "ok"


def test_can_open_position_allows_at_four():
    _patch()
    allowed, _ = rm.can_open_position(4)
    assert allowed is True


def test_can_open_position_blocks_at_limit():
    _patch()
    allowed, msg = rm.can_open_position(5)
    assert allowed is False
    assert "5" in msg


def test_can_open_position_blocks_above_limit():
    _patch()
    allowed, _ = rm.can_open_position(10)
    assert allowed is False


def test_is_daily_limit_not_hit_small_drop():
    _patch()
    # 3% drop — under 5% limit
    assert rm.is_daily_limit_hit(970.0, 1000.0) is False


def test_is_daily_limit_not_hit_exact_boundary():
    _patch()
    # exactly 5% drop — boundary is >=, so this IS hit
    assert rm.is_daily_limit_hit(950.0, 1000.0) is True


def test_is_daily_limit_hit_large_drop():
    _patch()
    # 6% drop — over limit
    assert rm.is_daily_limit_hit(940.0, 1000.0) is True


def test_stop_loss_custom_pct():
    _patch({"max_position_pct": 10, "stop_loss_pct": 5,
            "take_profit_pct": 15, "daily_loss_limit_pct": 5, "max_open_positions": 5})
    assert abs(rm.get_stop_loss_price(200.0) - 190.0) < 0.01
```

- [ ] **Step 2: Run tests — verify they FAIL**

```powershell
python -m pytest tests/test_risk_manager.py -v 2>&1 | Select-Object -First 10
```

Expected: `ImportError` — `core.risk_manager` doesn't exist yet.

- [ ] **Step 3: Create core/risk_manager.py**

```python
"""
Risk guardrails for the trading engine.
All rules enforced before any order reaches Alpaca.
Config is re-read on every call so voice-command changes take effect immediately.
"""
import json
from pathlib import Path

_CONFIG_PATH = Path("data/trading_config.json")

_DEFAULTS = {
    "max_position_pct": 10,
    "stop_loss_pct": 8,
    "take_profit_pct": 15,
    "daily_loss_limit_pct": 5,
    "max_open_positions": 5,
}


def _load_config() -> dict:
    if not _CONFIG_PATH.exists():
        return dict(_DEFAULTS)
    try:
        return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return dict(_DEFAULTS)


def can_open_position(open_positions_count: int) -> tuple[bool, str]:
    """Return (allowed, reason). Checks only position count — caller checks symbol duplication."""
    cfg = _load_config()
    max_pos = cfg.get("max_open_positions", _DEFAULTS["max_open_positions"])
    if open_positions_count >= max_pos:
        return False, f"Max positions reached ({max_pos})"
    return True, "ok"


def calc_position_size(portfolio_value: float, price_per_share: float) -> float:
    """Return fractional qty capped at max_position_pct% of portfolio_value."""
    cfg = _load_config()
    max_pct = cfg.get("max_position_pct", _DEFAULTS["max_position_pct"]) / 100.0
    max_dollars = portfolio_value * max_pct
    return round(max_dollars / price_per_share, 6)


def get_stop_loss_price(entry_price: float) -> float:
    """Return stop price (entry * (1 - stop_loss_pct/100))."""
    cfg = _load_config()
    pct = cfg.get("stop_loss_pct", _DEFAULTS["stop_loss_pct"]) / 100.0
    return round(entry_price * (1.0 - pct), 2)


def get_take_profit_price(entry_price: float) -> float:
    """Return take-profit limit price (entry * (1 + take_profit_pct/100))."""
    cfg = _load_config()
    pct = cfg.get("take_profit_pct", _DEFAULTS["take_profit_pct"]) / 100.0
    return round(entry_price * (1.0 + pct), 2)


def is_daily_limit_hit(portfolio_value: float, day_open_value: float) -> bool:
    """True when portfolio has dropped >= daily_loss_limit_pct% from day_open_value."""
    if day_open_value <= 0:
        return False
    cfg = _load_config()
    limit_pct = cfg.get("daily_loss_limit_pct", _DEFAULTS["daily_loss_limit_pct"]) / 100.0
    drop = (day_open_value - portfolio_value) / day_open_value
    return drop >= limit_pct
```

- [ ] **Step 4: Run tests — verify they PASS**

```powershell
python -m pytest tests/test_risk_manager.py -v
```

Expected: `12 passed`.

- [ ] **Step 5: Commit**

```powershell
git add core/risk_manager.py tests/test_risk_manager.py
git commit -m "feat: add risk_manager.py with position sizing, stop-loss, circuit breaker"
```

---

## Task 4: tools/trading_tool.py — Jarvis Tool Interface

**Files:**
- Create: `tools/trading_tool.py`

**Interfaces:**
- Consumes:
  - `core/trading_engine.TradingEngine` (imported lazily to avoid circular imports)
  - `data/trading_config.json`
  - `data/trades.json`
  - `ALPACA_API_KEY`, `ALPACA_SECRET_KEY` env vars
- Produces (all called from `brain.py`):
  - `set_trading_speak_callback(fn: Callable) -> None`
  - `start_trading_engine() -> str`
  - `stop_trading_engine() -> str`
  - `get_trading_status() -> str`
  - `get_trading_portfolio() -> str`
  - `get_trade_history(n: int = 20) -> str`
  - `get_trading_summary() -> str`
  - `set_risk_params(max_position_pct, stop_loss_pct, take_profit_pct, daily_loss_limit_pct, max_open_positions) -> str`
  - `switch_to_paper_mode() -> str`
  - `switch_to_live_mode(confirmed: bool = False) -> str`
  - `add_trading_symbol(symbol: str) -> str`
  - `remove_trading_symbol(symbol: str) -> str`

- [ ] **Step 1: Create tools/trading_tool.py**

```python
"""
Trading tool — Alpaca-backed autonomous investment engine interface.
Data: data/trading_config.json, data/trades.json
"""
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Callable

_CONFIG_PATH = Path("data/trading_config.json")
_TRADES_PATH = Path("data/trades.json")

_engine = None          # TradingEngine singleton
_speak_fn: Callable[[str], None] | None = None


def set_trading_speak_callback(fn: Callable[[str], None]) -> None:
    """Called from main.py at startup to wire in the TTS speak function."""
    global _speak_fn
    _speak_fn = fn


def _get_engine():
    global _engine
    if _engine is None:
        from core.trading_engine import TradingEngine
        _engine = TradingEngine(speak_fn=_speak_fn)
    return _engine


def _load_config() -> dict:
    if not _CONFIG_PATH.exists():
        return _default_config()
    try:
        return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return _default_config()


def _save_config(cfg: dict) -> None:
    _CONFIG_PATH.parent.mkdir(exist_ok=True)
    _CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


def _default_config() -> dict:
    return {
        "mode": "paper",
        "active_symbols": ["SPY", "QQQ", "AAPL", "NVDA", "MSFT"],
        "max_position_pct": 10,
        "stop_loss_pct": 8,
        "take_profit_pct": 15,
        "daily_loss_limit_pct": 5,
        "max_open_positions": 5,
        "cycle_interval_minutes": 15,
    }


def _load_trades() -> list:
    if not _TRADES_PATH.exists():
        return []
    try:
        return json.loads(_TRADES_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []


# ── Tool functions ─────────────────────────────────────────────────────────────

def start_trading_engine() -> str:
    if not _CONFIG_PATH.exists():
        _save_config(_default_config())
    engine = _get_engine()
    return engine.start()


def stop_trading_engine() -> str:
    return _get_engine().stop()


def get_trading_status() -> str:
    engine = _get_engine()
    cfg = _load_config()
    running = engine.is_running()
    mode = cfg.get("mode", "paper")
    symbols = cfg.get("active_symbols", [])
    trades = _load_trades()
    last_ts = trades[-1]["timestamp"][:16] if trades else "No trades yet"
    return (
        f"Trading engine: {'RUNNING' if running else 'STOPPED'}\n"
        f"Mode: {mode.upper()}\n"
        f"Watching: {', '.join(symbols)}\n"
        f"Last trade: {last_ts}"
    )


def get_trading_portfolio() -> str:
    api_key = os.getenv("ALPACA_API_KEY", "")
    secret = os.getenv("ALPACA_SECRET_KEY", "")
    if not api_key or api_key == "your_alpaca_key_here":
        return "Alpaca API keys not configured. Add ALPACA_API_KEY and ALPACA_SECRET_KEY to .env"
    try:
        from alpaca.trading.client import TradingClient
        cfg = _load_config()
        paper = cfg.get("mode", "paper") == "paper"
        client = TradingClient(api_key, secret, paper=paper)
        account = client.get_account()
        positions = client.get_all_positions()
        lines = [
            f"Portfolio: ${float(account.portfolio_value):,.2f}",
            f"Cash: ${float(account.cash):,.2f}",
            f"Mode: {cfg.get('mode', 'paper').upper()}",
            f"Open positions: {len(positions)}",
            "---",
        ]
        if not positions:
            lines.append("No open positions.")
        for p in positions:
            pnl = float(p.unrealized_pl)
            pnl_pct = float(p.unrealized_plpc) * 100
            lines.append(
                f"{p.symbol}: {p.qty} shares @ ${float(p.avg_entry_price):.2f}"
                f" | P&L: ${pnl:+.2f} ({pnl_pct:+.1f}%)"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"Error fetching portfolio: {e}"


def get_trade_history(n: int = 20) -> str:
    trades = _load_trades()
    if not trades:
        return "No trades recorded yet."
    recent = list(reversed(trades[-n:]))
    lines = [f"Last {len(recent)} trade(s):"]
    for t in recent:
        ts = t.get("timestamp", "?")[:16]
        side = t.get("side", "?").upper()
        qty = t.get("qty", 0)
        price = t.get("price", 0)
        symbol = t.get("symbol", "?")
        signal = t.get("signal", "?")
        lines.append(f"{ts} | {side} {qty:.3f} {symbol} @ ${price:.2f} | {signal}")
    return "\n".join(lines)


def get_trading_summary() -> str:
    trades = _load_trades()
    if not trades:
        return "No trades yet. Start the engine with start_trading_engine."
    today = datetime.now().date().isoformat()
    today_trades = [t for t in trades if t.get("timestamp", "")[:10] == today]
    lines = [
        f"Total trades all time: {len(trades)}",
        f"Today's trades: {len(today_trades)}",
        "",
        get_trading_portfolio(),
    ]
    return "\n".join(lines)


def set_risk_params(
    max_position_pct: float | None = None,
    stop_loss_pct: float | None = None,
    take_profit_pct: float | None = None,
    daily_loss_limit_pct: float | None = None,
    max_open_positions: int | None = None,
) -> str:
    cfg = _load_config()
    changes = []
    if max_position_pct is not None:
        cfg["max_position_pct"] = float(max_position_pct)
        changes.append(f"max position -> {max_position_pct}%")
    if stop_loss_pct is not None:
        cfg["stop_loss_pct"] = float(stop_loss_pct)
        changes.append(f"stop-loss -> {stop_loss_pct}%")
    if take_profit_pct is not None:
        cfg["take_profit_pct"] = float(take_profit_pct)
        changes.append(f"take-profit -> {take_profit_pct}%")
    if daily_loss_limit_pct is not None:
        cfg["daily_loss_limit_pct"] = float(daily_loss_limit_pct)
        changes.append(f"daily limit -> {daily_loss_limit_pct}%")
    if max_open_positions is not None:
        cfg["max_open_positions"] = int(max_open_positions)
        changes.append(f"max positions -> {max_open_positions}")
    if not changes:
        return "No parameters provided — nothing changed."
    _save_config(cfg)
    return "Risk params updated: " + ", ".join(changes)


def switch_to_paper_mode() -> str:
    cfg = _load_config()
    cfg["mode"] = "paper"
    _save_config(cfg)
    engine = _get_engine()
    if engine.is_running():
        engine.stop()
        engine.start()
    return "Switched to PAPER mode. All orders route to Alpaca sandbox (fake money)."


def switch_to_live_mode(confirmed: bool = False) -> str:
    if not confirmed:
        return (
            "WARNING: This will trade with REAL money. "
            "Say 'confirm live trading' to proceed."
        )
    cfg = _load_config()
    cfg["mode"] = "live"
    _save_config(cfg)
    engine = _get_engine()
    if engine.is_running():
        engine.stop()
        engine.start()
    return "Switched to LIVE mode. Real-money trading is now active."


def add_trading_symbol(symbol: str) -> str:
    symbol = symbol.upper().strip()
    cfg = _load_config()
    symbols = cfg.get("active_symbols", [])
    if symbol in symbols:
        return f"{symbol} is already in the trading watchlist."
    symbols.append(symbol)
    cfg["active_symbols"] = symbols
    _save_config(cfg)
    return f"Added {symbol}. Now tracking: {', '.join(symbols)}"


def remove_trading_symbol(symbol: str) -> str:
    symbol = symbol.upper().strip()
    cfg = _load_config()
    symbols = cfg.get("active_symbols", [])
    if symbol not in symbols:
        return f"{symbol} is not in the trading watchlist."
    symbols.remove(symbol)
    cfg["active_symbols"] = symbols
    _save_config(cfg)
    return f"Removed {symbol}. Now tracking: {', '.join(symbols) or 'nothing'}"
```

- [ ] **Step 2: Verify the module imports cleanly (no circular import)**

```powershell
python -c "from tools.trading_tool import start_trading_engine, get_trading_status; print('trading_tool OK')"
```

Expected: `trading_tool OK`

- [ ] **Step 3: Commit**

```powershell
git add tools/trading_tool.py
git commit -m "feat: add trading_tool.py with 11 Jarvis-facing trading functions"
```

---

## Task 5: core/trading_engine.py — Background Loop

**Files:**
- Create: `core/trading_engine.py`
- Modify: `main.py` (one line: wire speak callback)

**Interfaces:**
- Consumes:
  - `core/signals.rsi`, `core/signals.macd`, `core/signals.classify_signal`, `core/signals.SignalStrength`
  - `core/risk_manager.can_open_position`, `.calc_position_size`, `.get_stop_loss_price`, `.get_take_profit_price`, `.is_daily_limit_hit`
  - `tools/stocks_tool.get_stock_news` (for Claude headlines)
  - `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, `ALPACA_MODE` env vars
  - `data/trading_config.json`
  - `data/trades.json` (writes)
  - `ANTHROPIC_API_KEY` (already in .env)
- Produces:
  - `TradingEngine(speak_fn: Callable | None)` class with:
    - `.start() -> str`
    - `.stop() -> str`
    - `.is_running() -> bool`
  - Imported by `trading_tool.py`

- [ ] **Step 1: Create core/trading_engine.py**

```python
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

    # ── Price data ─────────────────────────────────────────────────────────────

    def _fetch_closes(self, data_client, symbol: str) -> list[float]:
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame
        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Hour,
            start=datetime.now(timezone.utc) - timedelta(days=10),
            limit=100,
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
                    if qty < 0.001:
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
        while not self._stop_event.is_set():
            today = datetime.now().date()
            if self._last_day != today:
                self._day_open_value = None
                self._last_day = today

            if self._is_market_open():
                try:
                    self._run_cycle()
                except Exception as e:
                    logger.error(f"[Trading] Unhandled cycle error: {e}")

            cfg = self._load_config()
            interval = cfg.get("cycle_interval_minutes", 15) * 60
            self._stop_event.wait(timeout=interval)
```

- [ ] **Step 2: Verify engine imports without error**

```powershell
python -c "from core.trading_engine import TradingEngine; print('trading_engine OK')"
```

Expected: `trading_engine OK`

- [ ] **Step 3: Wire speak callback in main.py**

Find this block in `main.py` (around line 262):

```python
from tools.macro_tool import set_speak_callback as _macro_speak_cb
_macro_speak_cb(voice_out.speak)
```

Add immediately after it:

```python
from tools.trading_tool import set_trading_speak_callback as _trading_speak_cb
_trading_speak_cb(voice_out.speak)
```

- [ ] **Step 4: Verify main.py still imports cleanly**

```powershell
python -c "import main" 2>&1 | Select-Object -First 5
```

Expected: no `ImportError` or `ModuleNotFoundError`.

- [ ] **Step 5: Commit**

```powershell
git add core/trading_engine.py main.py
git commit -m "feat: add trading_engine.py with 15-min Alpaca loop and wire speak callback in main.py"
```

---

## Task 6: brain.py — SYSTEM_PROMPT, Tools, Routing, Dispatch

**Files:**
- Modify: `core/brain.py` (4 additions in specific locations)

**Interfaces:**
- Consumes: all 11 functions from `tools/trading_tool.py`
- Produces: Jarvis can understand and execute all trading voice commands

### Part A — SYSTEM_PROMPT addition

- [ ] **Step 1: Add trading section to SYSTEM_PROMPT**

Find the last line of the SYSTEM_PROMPT block (the triple-quote closing `"""` that ends the string). It is the line just before:

```python
TOOLS: list[dict[str, Any]] = [
```

Insert this block **before** the closing `"""`:

```
Developer utilities: hash_text, encode_base64, decode_base64, url_encode, url_decode, generate_password, generate_uuid, generate_qr.
```
(That line is already there — insert the trading block AFTER it, BEFORE the closing `"""`)

New block to insert:

```
Trading engine (autonomous investing):
Tools: start_trading_engine, stop_trading_engine, get_trading_status, get_trading_portfolio, get_trade_history, get_trading_summary, set_risk_params, switch_to_paper_mode, switch_to_live_mode, add_trading_symbol, remove_trading_symbol.

Trading engine runs in paper mode by default (Alpaca sandbox — fake money, real market data). Switch to live only when Mo explicitly confirms.
When Mo says "start trading", "start the trading engine", "start investing" -> start_trading_engine.
When Mo says "stop trading", "pause the engine" -> stop_trading_engine.
When Mo says "trading status", "is the engine running?" -> get_trading_status.
When Mo says "trading portfolio", "my trading positions", "what am I holding?" (in trading context) -> get_trading_portfolio.
When Mo says "trading history", "recent trades", "what did you trade?" -> get_trade_history.
When Mo says "trading summary", "trading P&L", "how's the engine doing?" -> get_trading_summary.
When Mo says "set stop-loss to X%", "set take-profit to X%", "set max position to X%" -> set_risk_params with the matching param.
When Mo says "switch to paper mode", "paper trading" -> switch_to_paper_mode.
When Mo says "switch to live trading", "go live" -> switch_to_live_mode (confirmed=False first, then confirmed=True only if Mo says "confirm live trading").
When Mo says "add [TICKER] to trading watchlist" -> add_trading_symbol(symbol).
When Mo says "remove [TICKER] from trading watchlist" -> remove_trading_symbol(symbol).
NEVER execute switch_to_live_mode(confirmed=True) unless Mo has explicitly said "confirm live trading" after seeing the warning.
All trading reports are exceptions to the 1-2 sentence rule — deliver the full report.
```

### Part B — TOOLS list addition

- [ ] **Step 2: Add 11 tool schemas to TOOLS list**

Find the last entry in the `TOOLS` list (it ends with `generate_qr` tool). After its closing `},` and before the `]` that closes the TOOLS list, add:

```python
    # ── Trading Engine ────────────────────────────────────────────────────────
    {
        "name": "start_trading_engine",
        "description": "Start the autonomous trading engine background loop. Monitors the active watchlist every 15 minutes and places bracket orders when signals fire. Paper mode by default.",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "stop_trading_engine",
        "description": "Stop the trading engine loop. Open positions remain with their bracket orders active on Alpaca's servers.",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "get_trading_status",
        "description": "Return trading engine state: running/stopped, paper/live mode, active watchlist, last trade timestamp.",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "get_trading_portfolio",
        "description": "Fetch live positions from Alpaca: symbol, qty, entry price, current P&L for each open position plus total portfolio value.",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "get_trade_history",
        "description": "Return the last N executed trades with timestamp, symbol, side, qty, price, and signal type.",
        "input_schema": {
            "type": "object",
            "properties": {
                "n": {"type": "integer", "description": "Number of trades to return. Default 20."}
            }
        }
    },
    {
        "name": "get_trading_summary",
        "description": "Return total trades, today's trades, and current portfolio value — a one-page trading dashboard.",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "set_risk_params",
        "description": "Update one or more risk parameters. All params are optional — only provided ones are changed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "max_position_pct": {"type": "number", "description": "Max % of portfolio per trade. Default 10."},
                "stop_loss_pct": {"type": "number", "description": "Auto-sell if position drops this %. Default 8."},
                "take_profit_pct": {"type": "number", "description": "Auto-sell if position gains this %. Default 15."},
                "daily_loss_limit_pct": {"type": "number", "description": "Stop trading if portfolio drops this % in a day. Default 5."},
                "max_open_positions": {"type": "integer", "description": "Maximum simultaneous open positions. Default 5."}
            }
        }
    },
    {
        "name": "switch_to_paper_mode",
        "description": "Route all orders to Alpaca paper trading sandbox (fake money, real market data). Safe to call anytime.",
        "input_schema": {"type": "object", "properties": {}, "required": []}
    },
    {
        "name": "switch_to_live_mode",
        "description": "Switch to real-money trading. Requires confirmed=True — only set that after Mo explicitly says 'confirm live trading' following the warning.",
        "input_schema": {
            "type": "object",
            "properties": {
                "confirmed": {"type": "boolean", "description": "Must be true. Only set after Mo explicitly confirms."}
            }
        }
    },
    {
        "name": "add_trading_symbol",
        "description": "Add a ticker symbol to the active trading watchlist (e.g. 'TSLA', 'AMZN').",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Ticker symbol, e.g. 'TSLA'"}
            },
            "required": ["symbol"]
        }
    },
    {
        "name": "remove_trading_symbol",
        "description": "Remove a ticker symbol from the active trading watchlist.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Ticker symbol to remove"}
            },
            "required": ["symbol"]
        }
    },
```

### Part C — _TOOL_GROUP_NAMES and _GROUP_TRIGGERS additions

- [ ] **Step 3: Add "trading" group to _TOOL_GROUP_NAMES**

Find the closing `}` of `_TOOL_GROUP_NAMES` (it comes right after the `"dev_utils"` entry). Add before that closing `}`:

```python
    "trading": frozenset({
        "start_trading_engine", "stop_trading_engine", "get_trading_status",
        "get_trading_portfolio", "get_trade_history", "get_trading_summary",
        "set_risk_params", "switch_to_paper_mode", "switch_to_live_mode",
        "add_trading_symbol", "remove_trading_symbol",
    }),
```

- [ ] **Step 4: Add "trading" entry to _GROUP_TRIGGERS**

Find the closing `}` of `_GROUP_TRIGGERS`. Add before that `}`:

```python
    "trading":    ["start trading", "stop trading", "trading engine", "trading status",
                   "trading portfolio", "trading history", "trade history", "recent trades",
                   "trading summary", "trading p&l", "set stop-loss", "set take-profit",
                   "set max position", "paper mode", "live trading", "confirm live",
                   "trading watchlist", "add to trading", "remove from trading",
                   "autonomous trading", "invest automatically", "auto invest",
                   "engine running", "is it trading", "what did you trade",
                   "استثمار تلقائي", "محرك التداول"],
```

### Part D — _dispatch_tool addition

- [ ] **Step 5: Add dispatch cases to _dispatch_tool**

Find the last `elif` block inside `_dispatch_tool`. After it, add:

```python
            # ── Trading Engine ───────────────────────────────────────────────
            elif name == "start_trading_engine":
                from tools.trading_tool import start_trading_engine
                return start_trading_engine()
            elif name == "stop_trading_engine":
                from tools.trading_tool import stop_trading_engine
                return stop_trading_engine()
            elif name == "get_trading_status":
                from tools.trading_tool import get_trading_status
                return get_trading_status()
            elif name == "get_trading_portfolio":
                from tools.trading_tool import get_trading_portfolio
                return get_trading_portfolio()
            elif name == "get_trade_history":
                from tools.trading_tool import get_trade_history
                return get_trade_history(**tool_input)
            elif name == "get_trading_summary":
                from tools.trading_tool import get_trading_summary
                return get_trading_summary()
            elif name == "set_risk_params":
                from tools.trading_tool import set_risk_params
                return set_risk_params(**tool_input)
            elif name == "switch_to_paper_mode":
                from tools.trading_tool import switch_to_paper_mode
                return switch_to_paper_mode()
            elif name == "switch_to_live_mode":
                from tools.trading_tool import switch_to_live_mode
                return switch_to_live_mode(**tool_input)
            elif name == "add_trading_symbol":
                from tools.trading_tool import add_trading_symbol
                return add_trading_symbol(**tool_input)
            elif name == "remove_trading_symbol":
                from tools.trading_tool import remove_trading_symbol
                return remove_trading_symbol(**tool_input)
```

- [ ] **Step 6: Verify brain.py imports cleanly**

```powershell
python -c "from core.brain import Brain, _select_tools; print('brain OK'); print(_select_tools('start trading engine')[-3:])"
```

Expected: `brain OK` and the last 3 tools include trading tools.

- [ ] **Step 7: Commit**

```powershell
git add core/brain.py
git commit -m "feat: register 11 trading tools in brain.py (SYSTEM_PROMPT, TOOLS, routing, dispatch)"
```

---

## Task 7: Paper Trading Smoke Test

**Files:**
- No new files — manual verification

**Interfaces:**
- Consumes: All previous tasks
- Verifies: Unit tests pass, engine starts, Alpaca API responds, signals compute on real data

- [ ] **Step 1: Run all unit tests**

```powershell
python -m pytest tests/test_signals.py tests/test_risk_manager.py -v
```

Expected: `26 passed` (14 signals + 12 risk_manager).

- [ ] **Step 2: Obtain Alpaca paper API keys**

1. Go to alpaca.markets → Sign Up (free)
2. Dashboard → API Keys → Generate New Key (Paper Trading)
3. Copy `API Key ID` and `Secret Key`
4. Update `.env`:
   - `ALPACA_API_KEY=your_actual_key`
   - `ALPACA_SECRET_KEY=your_actual_secret`

- [ ] **Step 3: Verify Alpaca paper account connects**

```powershell
python -c "
import os; from dotenv import load_dotenv; load_dotenv()
from alpaca.trading.client import TradingClient
client = TradingClient(os.getenv('ALPACA_API_KEY'), os.getenv('ALPACA_SECRET_KEY'), paper=True)
acct = client.get_account()
print(f'Account status: {acct.status}')
print(f'Portfolio value: \${float(acct.portfolio_value):,.2f}')
"
```

Expected:
```
Account status: ACTIVE
Portfolio value: $100,000.00
```
(Alpaca paper accounts start with $100,000.)

- [ ] **Step 4: Verify historical data fetch works**

```powershell
python -c "
import os; from dotenv import load_dotenv; load_dotenv()
from dotenv import load_dotenv; load_dotenv()
from datetime import datetime, timedelta, timezone
from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
client = StockHistoricalDataClient(os.getenv('ALPACA_API_KEY'), os.getenv('ALPACA_SECRET_KEY'))
req = StockBarsRequest(symbol_or_symbols='SPY', timeframe=TimeFrame.Hour, start=datetime.now(timezone.utc)-timedelta(days=5), limit=20)
bars = client.get_stock_bars(req)
closes = bars.df['close'].tolist()
print(f'Got {len(closes)} hourly closes for SPY. Last: \${closes[-1]:.2f}')
"
```

Expected: `Got 20 hourly closes for SPY. Last: $XXX.XX`

- [ ] **Step 5: Verify signals compute on real SPY data**

```powershell
python -c "
import os; from dotenv import load_dotenv; load_dotenv()
from datetime import datetime, timedelta, timezone
from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from core.signals import rsi, macd, classify_signal
client = StockHistoricalDataClient(os.getenv('ALPACA_API_KEY'), os.getenv('ALPACA_SECRET_KEY'))
req = StockBarsRequest(symbol_or_symbols='SPY', timeframe=TimeFrame.Hour, start=datetime.now(timezone.utc)-timedelta(days=10), limit=100)
bars = client.get_stock_bars(req)
closes = bars.df['close'].tolist()
rsi_val = rsi(closes)
macd_result = macd(closes)
signal = classify_signal(closes, rsi_val, macd_result)
print(f'SPY: RSI={rsi_val:.1f}, MACD hist={macd_result.histogram:.4f}, Signal={signal}')
"
```

Expected: Something like `SPY: RSI=54.3, MACD hist=0.1234, Signal=HOLD`

- [ ] **Step 6: Start the engine and confirm it runs for one cycle (paper mode)**

```powershell
python -c "
import os; from dotenv import load_dotenv; load_dotenv()
import time
from core.trading_engine import TradingEngine
engine = TradingEngine(speak_fn=print)
print(engine.start())
time.sleep(90)  # Wait for one full cycle pass
print('Engine running:', engine.is_running())
print(engine.stop())
"
```

Expected: Engine start message, then after 90 seconds it's still running, then stop message. No unhandled exceptions.

- [ ] **Step 7: Commit final state**

```powershell
git add .
git commit -m "test: paper trading smoke test passes — trading engine wired end-to-end"
```

---

## Self-Review Checklist (internal — do not skip)

After writing this plan, verify:

1. **Spec coverage:**
   - Architecture (4 new files + brain.py + main.py) — Task 1, 2, 3, 4, 5, 6 ✓
   - 15-min loop with market hours guard — Task 5 `_is_market_open`, `_loop` ✓
   - RSI/MACD/EMA signals — Task 2 ✓
   - Claude consultation for ambiguous signals — Task 5 `_consult_claude` ✓
   - Risk manager (position size, SL, TP, circuit breaker, max positions) — Task 3 ✓
   - Bracket orders server-side — Task 5 `_place_buy` uses `order_class="bracket"` ✓
   - All 11 tool functions — Task 4 ✓
   - TTS announcements — Task 5 `self._speak()` calls ✓
   - Live mode double-confirmation — Task 4 `switch_to_live_mode(confirmed=False)` ✓
   - Configurable risk params via voice — Task 4 `set_risk_params` ✓
   - Paper-first default — Task 1 `trading_config.json` mode=paper ✓
   - brain.py routing + dispatch — Task 6 ✓

2. **Type consistency:** `MACDResult` named tuple defined in Task 2, used by name in Task 5 ✓. `SignalStrength` constants used consistently ✓. `can_open_position` returns `tuple[bool, str]` — callers in Task 5 unpack `allowed, _` ✓.

3. **No placeholders:** All steps have exact code. No "TBD" ✓.
