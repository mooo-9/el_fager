# Backtesting Engine — Design Spec
**Date:** 2026-06-20
**Phase:** Trading Engine Phase 2 — Strategy Validation
**Status:** Approved, ready for implementation

---

## Overview

Add a backtesting engine to El Fager's trading system. The engine replays 2 years of Alpaca hourly bar data chronologically, applies the exact same signal logic (`core/signals.py`) and risk rules (`core/risk_manager.py`) already used by the live trading engine, simulates order fills realistically, and produces a performance report with five key metrics compared against a SPY buy-and-hold benchmark.

The goal is to validate the current strategy on historical data before risking real money, and to provide a repeatable tool for measuring the impact of future strategy changes.

---

## Architecture

Four new files are added. Nothing existing is removed or broken — purely additive.

```
el_fager/
├── core/
│   └── backtester.py          ← simulation engine (new)
├── tools/
│   └── backtest_tool.py       ← 4 Jarvis voice commands (new)
├── data/
│   └── backtest_results.json  ← last run output (gitignored, created at runtime)
└── core/brain.py              ← register 4 tools (modified)
```

### Data flow

1. Fetch 2 years of hourly OHLCV bars from Alpaca historical data API (same client as `trading_engine.py`)
2. Walk bars chronologically — at each bar, compute RSI(14) + MACD(12,26,9) + EMA(20/50) on the preceding 100 bars using existing `signals.py`
3. On `STRONG_BUY`: simulate a buy at the **next bar's open price** (avoids look-ahead bias)
4. Apply `risk_manager.py` position sizing (10% of portfolio per trade)
5. On each subsequent bar: check if the bar's low crossed the stop-loss price or high crossed the take-profit price — exit at that price
6. Track all fills, exits, and portfolio value over time
7. Compute metrics and save to `data/backtest_results.json`

---

## Simulation Rules

| Rule | Value | Rationale |
|---|---|---|
| Fill price | Next bar's open | No look-ahead bias |
| Starting capital | $10,000 | Matches medium-risk target range |
| Position sizing | 10% of portfolio per trade | Identical to live engine |
| Stop-loss | -8% from entry | Identical to live engine |
| Take-profit | +15% from entry | Identical to live engine |
| Max open positions | 5 | Identical to live engine |
| Claude consultation | Skipped | Cost-prohibitive at scale (730 bars x 5 symbols) |
| Commissions | $0 | Alpaca charges no commissions |
| Benchmark | SPY buy-and-hold over same period | Standard comparison |
| Historical range | 730 days (2 years) | Covers bull and correction cycles |

---

## Metrics

All five metrics are computed per symbol and aggregated across the full watchlist:

| Metric | Description | Target |
|---|---|---|
| Total return % | Strategy return vs. SPY buy-and-hold benchmark | > benchmark |
| Win rate | % of trades that hit take-profit before stop-loss | > 50% |
| Avg gain / avg loss | Mean % gain per winning trade / mean % loss per losing trade | Gain > 2x loss |
| Max drawdown | Worst peak-to-trough portfolio drop during the period | < 20% |
| Sharpe ratio | Annualized return / annualized volatility | > 1.0 acceptable, > 2.0 strong |

---

## Tools (4 new, registered in brain.py)

| Function | Description |
|---|---|
| `run_backtest(symbol, days=730)` | Backtest one symbol over N days |
| `run_full_backtest()` | Backtest all 5 active symbols, produce combined report |
| `get_backtest_results()` | Return last saved results as readable text |
| `compare_to_buyhold(symbol)` | Compare strategy return vs. buy-and-hold for one symbol |

### Sample TTS output

**`run_backtest("SPY")`**
> "Backtest complete for SPY over 2 years. Strategy returned 34% vs SPY buy-and-hold 28%. Win rate 61%, average gain 12%, average loss 6%. Max drawdown 14%. Sharpe ratio 1.4. Results saved."

**`run_full_backtest()`**
> "Full backtest across 5 symbols complete. Best performer: NVDA at 87% return. Worst: QQQ at 11%. Overall portfolio Sharpe 1.6. Full breakdown saved."

**`compare_to_buyhold("AAPL")`**
> "Strategy returned 22% on AAPL vs buy-and-hold 31%. Strategy underperforms on this symbol — consider removing it from the watchlist."

---

## brain.py additions

- 4 tool schemas appended to TOOLS list
- `"backtest"` frozenset added to `_TOOL_GROUP_NAMES`
- Triggers added to `_GROUP_TRIGGERS["backtest"]`: `"backtest"`, `"test strategy"`, `"how is the strategy"`, `"strategy performance"`, `"did the strategy work"`, `"historical performance"`, `"اختبار الاستراتيجية"`
- 4 elif dispatch cases added to `_dispatch_tool`

---

## Data File: `data/backtest_results.json`

```json
{
  "run_at": "2026-06-20T14:00:00",
  "days": 730,
  "symbols": {
    "SPY": {
      "total_return_pct": 34.2,
      "benchmark_return_pct": 28.1,
      "win_rate_pct": 61.0,
      "avg_gain_pct": 12.3,
      "avg_loss_pct": 6.1,
      "max_drawdown_pct": 14.2,
      "sharpe_ratio": 1.4,
      "total_trades": 23,
      "winning_trades": 14,
      "losing_trades": 9
    }
  },
  "combined": {
    "total_return_pct": 45.1,
    "benchmark_return_pct": 28.1,
    "win_rate_pct": 58.0,
    "max_drawdown_pct": 17.3,
    "sharpe_ratio": 1.6
  }
}
```

---

## Constraints

- Python 3.14 type hints: `list[float]`, `X | None` — no `Optional`, no `List`
- cp1252 safety: no arrow characters (U+2192), `⚠`, emojis, or Arabic in tool return strings. Em-dash `—` is safe.
- `zoneinfo` for any timezone logic (no pytz)
- All Alpaca imports deferred inside functions (same pattern as `trading_engine.py`)
- `data/backtest_results.json` is gitignored (already covered by `data/` in `.gitignore`)
- No new pip dependencies — uses only `alpaca-py` (already installed) and stdlib

---

## Out of Scope

- Backtesting with Claude consultation (too expensive at scale)
- Intraday (sub-hourly) bar resolution
- Options, crypto, or non-Alpaca instruments
- Portfolio optimization / parameter tuning (future phase)
- Web dashboard or charting UI
- Walk-forward or cross-validation testing
