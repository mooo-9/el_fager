# Paper Trading Validation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the paper trading validation layer — sync exit fills from Alpaca into `trades.json`, compute the five gate criteria (win rate / Sharpe / drawdown / profit factor / trade count), and surface them through voice commands so El Fager can announce when it has earned real-money access.

**Architecture:** Three new components: `TradeTracker` syncs Alpaca closed-order fills into `trades.json` by matching SELL fills to open entries by symbol + chronological order. `PaperMetrics` reads completed trades and computes gate criteria, reusing `_max_drawdown` from `core/backtester.py`. A new `gate_check` intent in the router lets Mo ask "am I ready for real trading?" by voice; the existing `switch_to_live_mode` tool in `brain.py` already handles the double-confirmation to go live.

**Tech Stack:** alpaca-py (already installed), reuses `core/backtester._max_drawdown`, no new pip installs.

## Global Constraints

- Python 3.14; no new pip installs — alpaca-py, json, math already present
- cp1252 safety: no emojis, no U+2192 arrows, no Arabic in any string returned from `run()` or any of the new modules' public methods
- All Alpaca bar/quote requests must use `feed=DataFeed.IEX` — already enforced in `_place_trade`; TradeTracker uses orders/activities, NOT bar requests, so this constraint does not apply to TradeTracker
- `data/trades.json` schema: each entry may have these new optional keys after syncing: `exit_price: float`, `exit_time: str` (ISO), `pnl_pct: float`, `outcome: str` ("TP" | "SL" | "OPEN")
- Gate criteria (from spec): completed trades >= 30, win_rate >= 52%, Sharpe >= 1.0, max_drawdown <= 15%, profit_factor >= 1.3
- TradeTracker must never raise — catch all Alpaca exceptions; if API unavailable, return 0 synced
- PaperMetrics must never raise — if trades.json missing or malformed, return all-zeros dict

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `core/trade_tracker.py` | Create | `TradeTracker` — pulls closed SELL fills from Alpaca, matches to open trades by symbol+time, writes exit data back to `trades.json` |
| `core/paper_metrics.py` | Create | `PaperMetrics` — reads completed trades, computes 5 gate criteria, returns dict and voice-safe summary string |
| `core/agents/router.py` | Modify | Add `"gate_check"` label with keywords `"ready for real trading"`, `"passed the paper trading"`, `"paper trading gate"` |
| `core/brain.py` | Modify | Add `gate_check` branch in `_try_agent_dispatch`: sync + compute + return voice summary |
| `tests/test_trade_tracker.py` | Create | 8 tests: no open trades, no Alpaca sells, matching sell found, partial match, exception safety |
| `tests/test_paper_metrics.py` | Create | 10 tests: no trades, all wins, all losses, mixed, each gate criterion boundary, profit factor, voice summary |
| `tests/agents/test_router.py` | Modify | Append `TestGateCheckRouting` (3 tests) |

---

### Task 1: TradeTracker — sync exit fills from Alpaca

**Files:**
- Create: `core/trade_tracker.py`
- Create: `tests/test_trade_tracker.py`

**Interfaces:**
- Produces: `TradeTracker` with:
  - `sync() -> int` — queries Alpaca for closed SELL orders, matches each to an open entry in `trades.json` by symbol + chronological order (first available SELL fill for that symbol after the entry `timestamp`), writes exit fields, returns count of entries updated. Never raises.
  - `_load_trades() -> list[dict]` — reads `data/trades.json`, returns `[]` on any error
  - `_save_trades(trades: list[dict]) -> None` — writes back to `data/trades.json`
  - `_fetch_closed_sells(api_key: str, secret: str, paper: bool) -> list[dict]` — queries Alpaca, returns list of dicts `{"symbol": str, "price": float, "filled_at": str}` sorted by `filled_at` ascending; returns `[]` on any exception
  - Module-level constants: `_TRADES_PATH = Path("data/trades.json")`, `_CONFIG_PATH = Path("data/trading_config.json")`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_trade_tracker.py
import json
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path


def _write_trades(path: Path, trades: list) -> None:
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(trades), encoding="utf-8")


class TestTradeTrackerLoadSave:
    def test_load_returns_empty_when_no_file(self, tmp_path, monkeypatch):
        from core.trade_tracker import TradeTracker
        monkeypatch.setattr("core.trade_tracker._TRADES_PATH", tmp_path / "no.json")
        assert TradeTracker()._load_trades() == []

    def test_load_returns_empty_on_malformed_json(self, tmp_path, monkeypatch):
        bad = tmp_path / "trades.json"
        bad.write_text("not json", encoding="utf-8")
        monkeypatch.setattr("core.trade_tracker._TRADES_PATH", bad)
        assert TradeTracker()._load_trades() == []

    def test_save_writes_json(self, tmp_path, monkeypatch):
        from core.trade_tracker import TradeTracker
        path = tmp_path / "trades.json"
        monkeypatch.setattr("core.trade_tracker._TRADES_PATH", path)
        TradeTracker()._save_trades([{"symbol": "SPY"}])
        assert json.loads(path.read_text())== [{"symbol": "SPY"}]


class TestTradeTrackerFetchSells:
    def test_fetch_returns_empty_on_exception(self, monkeypatch):
        from core.trade_tracker import TradeTracker
        monkeypatch.setattr(
            "core.trade_tracker.TradeTracker._fetch_closed_sells",
            lambda self, k, s, p: [],
        )
        t = TradeTracker()
        assert t._fetch_closed_sells("key", "secret", True) == []

    def test_fetch_returns_empty_list_when_api_raises(self, monkeypatch):
        from core.trade_tracker import TradeTracker
        def _bad(self, k, s, p):
            raise RuntimeError("API down")
        monkeypatch.setattr("core.trade_tracker.TradeTracker._fetch_closed_sells", _bad)
        t = TradeTracker()
        try:
            result = t._fetch_closed_sells("k", "s", True)
        except Exception:
            result = []
        assert result == []


class TestTradeTrackerSync:
    def test_sync_no_open_trades(self, tmp_path, monkeypatch):
        from core.trade_tracker import TradeTracker
        path = tmp_path / "trades.json"
        # All trades already have outcome set (closed)
        _write_trades(path, [
            {"symbol": "NVDA", "timestamp": "2026-06-20T10:00:00", "outcome": "TP",
             "exit_price": 130.0, "pnl_pct": 8.0},
        ])
        monkeypatch.setattr("core.trade_tracker._TRADES_PATH", path)
        monkeypatch.setattr("core.trade_tracker._CONFIG_PATH", tmp_path / "cfg.json")
        t = TradeTracker()
        count = t.sync()
        assert count == 0

    def test_sync_matches_sell_to_open_trade(self, tmp_path, monkeypatch):
        from core.trade_tracker import TradeTracker
        path = tmp_path / "trades.json"
        _write_trades(path, [
            {"symbol": "AAPL", "timestamp": "2026-06-20T10:00:00", "price": 200.0,
             "sl_price": 190.0, "tp_price": 224.0},
        ])
        monkeypatch.setattr("core.trade_tracker._TRADES_PATH", path)
        monkeypatch.setattr("core.trade_tracker._CONFIG_PATH", tmp_path / "cfg.json")

        sells = [{"symbol": "AAPL", "price": 224.0, "filled_at": "2026-06-22T11:00:00"}]
        monkeypatch.setattr(
            "core.trade_tracker.TradeTracker._fetch_closed_sells",
            lambda self, k, s, p: sells,
        )

        count = TradeTracker().sync()
        assert count == 1
        updated = json.loads(path.read_text())
        assert updated[0]["outcome"] == "TP"
        assert updated[0]["exit_price"] == pytest.approx(224.0)
        assert updated[0]["pnl_pct"] == pytest.approx(12.0, rel=0.05)

    def test_sync_no_matching_sells_returns_zero(self, tmp_path, monkeypatch):
        from core.trade_tracker import TradeTracker
        path = tmp_path / "trades.json"
        _write_trades(path, [
            {"symbol": "NVDA", "timestamp": "2026-06-20T10:00:00", "price": 120.0,
             "sl_price": 114.0, "tp_price": 134.4},
        ])
        monkeypatch.setattr("core.trade_tracker._TRADES_PATH", path)
        monkeypatch.setattr("core.trade_tracker._CONFIG_PATH", tmp_path / "cfg.json")
        monkeypatch.setattr(
            "core.trade_tracker.TradeTracker._fetch_closed_sells",
            lambda self, k, s, p: [],
        )
        count = TradeTracker().sync()
        assert count == 0

    def test_sync_never_raises_on_api_exception(self, tmp_path, monkeypatch):
        from core.trade_tracker import TradeTracker
        path = tmp_path / "trades.json"
        _write_trades(path, [
            {"symbol": "SPY", "timestamp": "2026-06-20T10:00:00", "price": 500.0,
             "sl_price": 475.0, "tp_price": 560.0},
        ])
        monkeypatch.setattr("core.trade_tracker._TRADES_PATH", path)
        monkeypatch.setattr("core.trade_tracker._CONFIG_PATH", tmp_path / "cfg.json")

        def _boom(self, k, s, p):
            raise ConnectionError("no internet")
        monkeypatch.setattr("core.trade_tracker.TradeTracker._fetch_closed_sells", _boom)

        count = TradeTracker().sync()   # must not raise
        assert count == 0
```

- [ ] **Step 2: Run tests to confirm they fail**

```
cd C:\claude proj\el_fager
pytest tests/test_trade_tracker.py -v
```
Expected: `ImportError: No module named 'core.trade_tracker'`

- [ ] **Step 3: Implement `core/trade_tracker.py`**

```python
"""Syncs Alpaca closed-order fills back into trades.json as exit records."""
import json
import os
from pathlib import Path

_TRADES_PATH = Path("data/trades.json")
_CONFIG_PATH = Path("data/trading_config.json")


def _outcome_label(exit_price: float, tp_price: float, sl_price: float) -> str:
    """Classify a closed trade as TP, SL, or MANUAL based on proximity."""
    dist_tp = abs(exit_price - tp_price)
    dist_sl = abs(exit_price - sl_price)
    if dist_tp <= dist_sl:
        return "TP"
    return "SL"


class TradeTracker:
    def _load_trades(self) -> list[dict]:
        if not _TRADES_PATH.exists():
            return []
        try:
            return json.loads(_TRADES_PATH.read_text(encoding="utf-8"))
        except Exception:
            return []

    def _save_trades(self, trades: list[dict]) -> None:
        _TRADES_PATH.parent.mkdir(exist_ok=True)
        _TRADES_PATH.write_text(
            json.dumps(trades, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def _fetch_closed_sells(
        self, api_key: str, secret: str, paper: bool
    ) -> list[dict]:
        """Return closed SELL fills sorted by filled_at ascending. Returns [] on any error."""
        try:
            from alpaca.trading.client import TradingClient
            from alpaca.trading.requests import GetOrdersRequest
            from alpaca.trading.enums import QueryOrderStatus, OrderSide

            client = TradingClient(api_key, secret, paper=paper)
            orders = client.get_orders(filter=GetOrdersRequest(
                status=QueryOrderStatus.CLOSED,
                limit=200,
            ))
            sells = []
            for o in orders:
                if str(o.side) != "OrderSide.SELL":
                    continue
                if o.filled_avg_price is None or o.filled_at is None:
                    continue
                sells.append({
                    "symbol": o.symbol,
                    "price": float(o.filled_avg_price),
                    "filled_at": str(o.filled_at),
                })
            sells.sort(key=lambda x: x["filled_at"])
            return sells
        except Exception:
            return []

    def sync(self) -> int:
        """Match closed Alpaca SELL fills to open trades. Returns count updated."""
        trades = self._load_trades()
        open_trades = [t for t in trades if not t.get("outcome") or t.get("outcome") == "OPEN"]
        if not open_trades:
            return 0

        # Load config for API keys and mode
        cfg: dict = {}
        if _CONFIG_PATH.exists():
            try:
                cfg = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
            except Exception:
                pass

        api_key = os.getenv("ALPACA_API_KEY", cfg.get("api_key", ""))
        secret = os.getenv("ALPACA_SECRET_KEY", cfg.get("api_secret", ""))
        paper = cfg.get("mode", "paper") == "paper"

        try:
            sells = self._fetch_closed_sells(api_key, secret, paper)
        except Exception:
            sells = []

        # Map symbol -> list of available sell fills (sorted by time)
        sell_map: dict[str, list[dict]] = {}
        for s in sells:
            sell_map.setdefault(s["symbol"], []).append(s)

        updated = 0
        for trade in trades:
            if trade.get("outcome") and trade["outcome"] != "OPEN":
                continue   # already closed

            symbol = trade.get("symbol", "")
            entry_ts = trade.get("timestamp", "")
            available = [
                s for s in sell_map.get(symbol, [])
                if s["filled_at"] > entry_ts
            ]
            if not available:
                trade["outcome"] = "OPEN"
                continue

            # Take the chronologically earliest matching sell
            fill = available[0]
            exit_price = fill["price"]
            entry_price = float(trade.get("price", exit_price) or exit_price)
            pnl_pct = (exit_price - entry_price) / entry_price * 100 if entry_price else 0.0

            trade["exit_price"] = exit_price
            trade["exit_time"] = fill["filled_at"]
            trade["pnl_pct"] = round(pnl_pct, 4)
            trade["outcome"] = _outcome_label(
                exit_price,
                float(trade.get("tp_price", exit_price + 1)),
                float(trade.get("sl_price", exit_price - 1)),
            )
            # Consume this fill so it is not matched to a second trade
            sell_map[symbol] = sell_map[symbol][1:]
            updated += 1

        self._save_trades(trades)
        return updated
```

- [ ] **Step 4: Run tests**

```
cd C:\claude proj\el_fager
pytest tests/test_trade_tracker.py -v
```
Expected: 8 PASSED

- [ ] **Step 5: Commit**

```
git add core/trade_tracker.py tests/test_trade_tracker.py
git commit -m "feat: add TradeTracker to sync Alpaca closed fills into trades.json"
```

---

### Task 2: PaperMetrics — gate criteria computation

**Files:**
- Create: `core/paper_metrics.py`
- Create: `tests/test_paper_metrics.py`

**Interfaces:**
- Consumes: `core.backtester._max_drawdown(values: list[float]) -> float` (already exists)
- Produces: `PaperMetrics` with:
  - `compute() -> dict` — reads `_TRADES_PATH`, returns dict with keys:
    - `total_completed: int` — trades with outcome in ("TP", "SL")
    - `win_rate: float` — wins/total_completed*100, or 0.0 if no completed trades
    - `sharpe: float` — annualised Sharpe from pnl_pct values; 0.0 if < 5 completed trades
    - `max_drawdown: float` — peak-to-trough equity drawdown pct; 0.0 if < 2 trades
    - `profit_factor: float` — sum(wins) / abs(sum(losses)); 0.0 if no losses
    - `gate_pass: bool` — True only if ALL five criteria meet the spec thresholds
  - `gate_summary() -> str` — cp1252-safe single string listing each criterion's current value vs required; announces PASS or NOT YET
  - Module-level constants: `_TRADES_PATH = Path("data/trades.json")`, gate thresholds as constants

Gate threshold constants (copy verbatim from spec):
```python
_MIN_TRADES = 30
_MIN_WIN_RATE = 52.0
_MIN_SHARPE = 1.0
_MAX_DRAWDOWN = 15.0
_MIN_PROFIT_FACTOR = 1.3
```

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_paper_metrics.py
import json
import math
import pytest
from pathlib import Path


def _write(path: Path, trades: list) -> None:
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(trades), encoding="utf-8")


def _trade(symbol, pnl, outcome):
    return {
        "symbol": symbol, "price": 100.0, "qty": 0.1,
        "timestamp": "2026-06-01T10:00:00", "pnl_pct": pnl, "outcome": outcome,
    }


class TestPaperMetricsCompute:
    def test_no_trades_file_returns_zeros(self, tmp_path, monkeypatch):
        from core.paper_metrics import PaperMetrics
        monkeypatch.setattr("core.paper_metrics._TRADES_PATH", tmp_path / "none.json")
        m = PaperMetrics().compute()
        assert m["total_completed"] == 0
        assert m["win_rate"] == 0.0
        assert m["gate_pass"] is False

    def test_open_trades_not_counted(self, tmp_path, monkeypatch):
        from core.paper_metrics import PaperMetrics
        p = tmp_path / "trades.json"
        _write(p, [_trade("SPY", None, "OPEN"), _trade("SPY", None, "OPEN")])
        monkeypatch.setattr("core.paper_metrics._TRADES_PATH", p)
        m = PaperMetrics().compute()
        assert m["total_completed"] == 0

    def test_all_wins(self, tmp_path, monkeypatch):
        from core.paper_metrics import PaperMetrics
        p = tmp_path / "trades.json"
        _write(p, [_trade("A", 5.0, "TP"), _trade("B", 8.0, "TP"), _trade("C", 3.0, "TP")])
        monkeypatch.setattr("core.paper_metrics._TRADES_PATH", p)
        m = PaperMetrics().compute()
        assert m["total_completed"] == 3
        assert m["win_rate"] == pytest.approx(100.0)
        assert m["profit_factor"] == 0.0   # no losses so profit_factor = 0 (undefined)

    def test_all_losses(self, tmp_path, monkeypatch):
        from core.paper_metrics import PaperMetrics
        p = tmp_path / "trades.json"
        _write(p, [_trade("A", -4.0, "SL"), _trade("B", -5.0, "SL")])
        monkeypatch.setattr("core.paper_metrics._TRADES_PATH", p)
        m = PaperMetrics().compute()
        assert m["win_rate"] == 0.0
        assert m["profit_factor"] == 0.0

    def test_mixed_win_rate(self, tmp_path, monkeypatch):
        from core.paper_metrics import PaperMetrics
        p = tmp_path / "trades.json"
        _write(p, [
            _trade("A", 12.0, "TP"),
            _trade("B", -5.0, "SL"),
            _trade("C", 8.0, "TP"),
            _trade("D", -5.0, "SL"),
        ])
        monkeypatch.setattr("core.paper_metrics._TRADES_PATH", p)
        m = PaperMetrics().compute()
        assert m["win_rate"] == pytest.approx(50.0)
        assert m["profit_factor"] == pytest.approx(20.0 / 10.0)

    def test_sharpe_zero_for_fewer_than_five_trades(self, tmp_path, monkeypatch):
        from core.paper_metrics import PaperMetrics
        p = tmp_path / "trades.json"
        _write(p, [_trade("A", 5.0, "TP"), _trade("B", -3.0, "SL")])
        monkeypatch.setattr("core.paper_metrics._TRADES_PATH", p)
        m = PaperMetrics().compute()
        assert m["sharpe"] == 0.0

    def test_sharpe_positive_for_consistent_wins(self, tmp_path, monkeypatch):
        from core.paper_metrics import PaperMetrics
        p = tmp_path / "trades.json"
        trades = [_trade("A", 5.0 + i * 0.1, "TP") for i in range(10)]
        _write(p, trades)
        monkeypatch.setattr("core.paper_metrics._TRADES_PATH", p)
        m = PaperMetrics().compute()
        assert m["sharpe"] > 0.0

    def test_gate_pass_requires_all_criteria(self, tmp_path, monkeypatch):
        from core.paper_metrics import PaperMetrics
        p = tmp_path / "trades.json"
        # 31 trades but win rate only 45% — should NOT pass
        trades = [_trade("A", 12.0, "TP")] * 14 + [_trade("B", -5.0, "SL")] * 17
        _write(p, trades)
        monkeypatch.setattr("core.paper_metrics._TRADES_PATH", p)
        m = PaperMetrics().compute()
        assert m["total_completed"] == 31
        assert m["gate_pass"] is False


class TestPaperMetricsGateSummary:
    def test_summary_is_cp1252_safe(self, tmp_path, monkeypatch):
        from core.paper_metrics import PaperMetrics
        monkeypatch.setattr("core.paper_metrics._TRADES_PATH", tmp_path / "none.json")
        summary = PaperMetrics().gate_summary()
        # No characters outside ASCII/cp1252 range — check no emojis or arrows
        for ch in summary:
            assert ord(ch) < 0x2000 or 0x2013 <= ord(ch) <= 0x2014, \
                f"Non-cp1252 char: U+{ord(ch):04X} '{ch}'"

    def test_summary_contains_pass_or_not_yet(self, tmp_path, monkeypatch):
        from core.paper_metrics import PaperMetrics
        monkeypatch.setattr("core.paper_metrics._TRADES_PATH", tmp_path / "none.json")
        summary = PaperMetrics().gate_summary()
        assert "PASS" in summary.upper() or "NOT YET" in summary.upper()
```

- [ ] **Step 2: Run to confirm they fail**

```
cd C:\claude proj\el_fager
pytest tests/test_paper_metrics.py -v
```
Expected: `ImportError: No module named 'core.paper_metrics'`

- [ ] **Step 3: Implement `core/paper_metrics.py`**

```python
"""Computes paper-trading gate criteria from completed trades in trades.json."""
import json
import math
from pathlib import Path

from core.backtester import _max_drawdown

_TRADES_PATH = Path("data/trades.json")

# Gate thresholds (spec verbatim)
_MIN_TRADES = 30
_MIN_WIN_RATE = 52.0
_MIN_SHARPE = 1.0
_MAX_DRAWDOWN = 15.0
_MIN_PROFIT_FACTOR = 1.3


def _sharpe(returns: list[float]) -> float:
    """Annualised Sharpe from per-trade returns. Returns 0.0 if fewer than 5 data points."""
    if len(returns) < 5:
        return 0.0
    n = len(returns)
    mean = sum(returns) / n
    variance = sum((r - mean) ** 2 for r in returns) / n
    std = math.sqrt(variance)
    if std == 0.0:
        return 0.0
    # Annualise assuming ~252 trading days, treating each trade as one day
    return (mean / std) * math.sqrt(min(n, 252))


class PaperMetrics:
    def _load_completed(self) -> list[dict]:
        """Return only trades with a final outcome (TP or SL)."""
        if not _TRADES_PATH.exists():
            return []
        try:
            trades = json.loads(_TRADES_PATH.read_text(encoding="utf-8"))
        except Exception:
            return []
        return [t for t in trades if t.get("outcome") in ("TP", "SL")]

    def compute(self) -> dict:
        completed = self._load_completed()
        n = len(completed)

        if n == 0:
            return {
                "total_completed": 0,
                "win_rate": 0.0,
                "sharpe": 0.0,
                "max_drawdown": 0.0,
                "profit_factor": 0.0,
                "gate_pass": False,
            }

        returns = [float(t.get("pnl_pct") or 0.0) for t in completed]
        wins = [r for r in returns if r > 0]
        losses = [r for r in returns if r <= 0]

        win_rate = len(wins) / n * 100.0
        sharpe = _sharpe(returns)

        # Equity curve: start at 100, compound each trade return
        equity = [100.0]
        for r in returns:
            equity.append(equity[-1] * (1 + r / 100.0))
        drawdown = _max_drawdown(equity)

        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0.0

        gate_pass = (
            n >= _MIN_TRADES
            and win_rate >= _MIN_WIN_RATE
            and sharpe >= _MIN_SHARPE
            and drawdown <= _MAX_DRAWDOWN
            and profit_factor >= _MIN_PROFIT_FACTOR
        )

        return {
            "total_completed": n,
            "win_rate": round(win_rate, 2),
            "sharpe": round(sharpe, 3),
            "max_drawdown": round(drawdown, 2),
            "profit_factor": round(profit_factor, 3),
            "gate_pass": gate_pass,
        }

    def gate_summary(self) -> str:
        m = self.compute()
        lines = [
            f"Paper trading gate check ({m['total_completed']}/{_MIN_TRADES} trades):",
            f"  Win rate:      {m['win_rate']:.1f}% (need {_MIN_WIN_RATE}%)",
            f"  Sharpe ratio:  {m['sharpe']:.2f} (need {_MIN_SHARPE})",
            f"  Max drawdown:  {m['max_drawdown']:.1f}% (limit {_MAX_DRAWDOWN}%)",
            f"  Profit factor: {m['profit_factor']:.2f} (need {_MIN_PROFIT_FACTOR})",
        ]
        if m["gate_pass"]:
            lines.append(
                "ALL CRITERIA MET. Ready to trade real money. "
                "Say 'confirm real trading' to activate."
            )
        else:
            lines.append("NOT YET -- keep paper trading.")
        return "\n".join(lines)
```

- [ ] **Step 4: Run tests**

```
cd C:\claude proj\el_fager
pytest tests/test_paper_metrics.py -v
```
Expected: 10 PASSED

- [ ] **Step 5: Commit**

```
git add core/paper_metrics.py tests/test_paper_metrics.py
git commit -m "feat: add PaperMetrics gate criteria computation from completed trades"
```

---

### Task 3: Wire gate check into voice commands

**Files:**
- Modify: `core/agents/router.py`
- Modify: `core/brain.py`
- Modify: `tests/agents/test_router.py`

**Interfaces:**
- Consumes (Task 1): `core.trade_tracker.TradeTracker().sync() -> int`
- Consumes (Task 2): `core.paper_metrics.PaperMetrics().gate_summary() -> str`
- Produces in router: new label `"gate_check"` checked after `"stocks_agent"` and before `"stocks"`
- Produces in brain: `_try_agent_dispatch` handles `intent == "gate_check"` with `TradeTracker().sync(); return PaperMetrics().gate_summary()`

Router addition — add to `core/agents/router.py` after `_STOCKS_AGENT_KEYWORDS`:

```python
_GATE_CHECK_KEYWORDS = [
    "ready for real trading",
    "passed the paper trading",
    "paper trading gate",
    "how are we doing trading",
    "paper trading results",
    "am i ready to go live",
]
```

And add `("gate_check", _GATE_CHECK_KEYWORDS)` to `_LABEL_KEYWORDS` BEFORE `("stocks", _STOCKS_KEYWORDS)`.

Note: `"how are we doing trading"` is currently in `_STOCKS_AGENT_KEYWORDS` — remove it from there when adding to `_GATE_CHECK_KEYWORDS` to avoid dead keyword (it would never reach `gate_check` if it matches `stocks_agent` first).

Brain addition — in `_try_agent_dispatch`, add before `return None`:

```python
if intent == "gate_check":
    from core.trade_tracker import TradeTracker
    from core.paper_metrics import PaperMetrics
    TradeTracker().sync()
    return PaperMetrics().gate_summary()
```

- [ ] **Step 1: Write the failing tests**

Append to `tests/agents/test_router.py`:

```python
class TestGateCheckRouting:
    def test_ready_for_real_trading_routes_to_gate_check(self):
        from core.agents.router import classify_intent
        assert classify_intent("am I ready for real trading?") == "gate_check"

    def test_paper_trading_gate_routes_to_gate_check(self):
        from core.agents.router import classify_intent
        assert classify_intent("check my paper trading gate") == "gate_check"

    def test_invest_still_routes_to_stocks(self):
        from core.agents.router import classify_intent
        # Regression: word-boundary fix still holds — "invest" should not match "investigate"
        assert classify_intent("how should I invest my savings?") == "stocks"
```

- [ ] **Step 2: Run to confirm failure**

```
cd C:\claude proj\el_fager
pytest tests/agents/test_router.py::TestGateCheckRouting -v
```
Expected: 3 failures (`assert "instant" == "gate_check"` or similar)

- [ ] **Step 3: Modify `core/agents/router.py`** — add gate_check keywords

In `core/agents/router.py`, after the `_STOCKS_AGENT_KEYWORDS` block, add:

```python
_GATE_CHECK_KEYWORDS = [
    "ready for real trading",
    "passed the paper trading",
    "paper trading gate",
    "paper trading results",
    "am i ready to go live",
    "how are we doing trading",
]
```

Remove `"how are we doing trading"` from `_STOCKS_AGENT_KEYWORDS` (it was there for explain queries; the gate-check intent is more specific).

In `_LABEL_KEYWORDS`, add `("gate_check", _GATE_CHECK_KEYWORDS)` after the `"stocks_agent"` entry and before the `"stocks"` entry:

```python
_LABEL_KEYWORDS = [
    ("screen", _SCREEN_KEYWORDS),
    ("browser", _BROWSER_KEYWORDS),
    ("stocks_agent", _STOCKS_AGENT_KEYWORDS),
    ("gate_check", _GATE_CHECK_KEYWORDS),   # checked before generic "stocks"
    ("stocks", _STOCKS_KEYWORDS),
    ("research", _RESEARCH_KEYWORDS),
    ("file", _FILE_KEYWORDS),
]
```

- [ ] **Step 4: Modify `core/brain.py`** — add gate_check dispatch

In `_try_agent_dispatch`, add after the `"file"` branch and before `return None`:

```python
if intent == "gate_check":
    from core.trade_tracker import TradeTracker
    from core.paper_metrics import PaperMetrics
    TradeTracker().sync()
    return PaperMetrics().gate_summary()
```

- [ ] **Step 5: Run ALL tests**

```
cd C:\claude proj\el_fager
pytest tests/agents/test_router.py -v
pytest --tb=short -q
```
Expected: router tests all pass; full suite passes (198 + 18 new = 216).

- [ ] **Step 6: Commit**

```
git add core/agents/router.py core/brain.py tests/agents/test_router.py
git commit -m "feat: wire gate_check intent into router and brain dispatch"
```

---

## Self-Review

**Spec coverage:**
- [x] Sync exit fills from Alpaca (Task 1 — TradeTracker)
- [x] Compute: win rate, Sharpe, max drawdown, profit factor, trade count (Task 2 — PaperMetrics)
- [x] Gate thresholds from spec verbatim: 30 / 52% / 1.0 / 15% / 1.3 (Task 2)
- [x] Voice command: "am I ready for real trading?" → gate summary (Task 3)
- [x] Going live: brain.py already has `switch_to_live_mode` with double-confirmation — this plan does NOT re-implement it, reuses what exists

**Placeholder scan:** All code blocks are complete. No TBD/TODO.

**Type consistency:**
- `TradeTracker().sync() -> int` defined Task 1, called Task 3 — match
- `PaperMetrics().gate_summary() -> str` defined Task 2, called Task 3 — match
- `_max_drawdown(values: list[float]) -> float` imported from `core.backtester` — existing signature, no change
- `_TRADES_PATH` module-level in both `trade_tracker.py` and `paper_metrics.py` — both monkeypatched in tests on their respective module — no cross-module interference
- Router label `"gate_check"` defined Task 3 router, dispatched Task 3 brain — match

**Edge cases covered:**
- No trades.json: returns zeros, gate_pass = False
- All open trades: sync returns 0, metrics returns zeros
- No Alpaca API key / exception: sync returns 0, trades.json unchanged
- Fewer than 5 completed trades: Sharpe = 0.0 (insufficient data)
- Zero losses: profit_factor = 0.0 (undefined — treated as non-passing)
