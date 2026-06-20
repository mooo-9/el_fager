# Jarvis Investment Engine — Design Spec
**Date:** 2026-06-20
**Phase:** 1 (US Stocks via Alpaca) → Phase 2 (Crypto via Binance)
**Status:** Approved, ready for implementation

---

## Overview

Add an autonomous investment engine to El Fager (Jarvis). Jarvis receives a wallet (funded Alpaca account), monitors a watchlist of US stocks/ETFs every 15 minutes, generates trade signals using technical indicators, consults Claude for ambiguous signals, and executes trades automatically — all within hard risk guardrails. The user is notified via Jarvis TTS on every trade event.

Phase 1 covers US stocks via Alpaca in paper trading mode by default, with a single config flag to go live. Phase 2 adds Binance crypto after Phase 1 is proven stable.

---

## Architecture

Four new files are added to the existing structure. Nothing in the existing 28 tool groups is removed or changed — the trading system is purely additive.

```
el_fager/
├── core/
│   ├── trading_engine.py       ← autonomous background loop
│   ├── signals.py              ← RSI, MACD, EMA technical indicators
│   └── risk_manager.py         ← position sizing, stop-loss, circuit breaker
├── tools/
│   └── trading_tool.py         ← 11 Jarvis-facing tool functions
├── data/
│   ├── trades.json             ← full trade log (all executions)
│   ├── trading_config.json     ← mode, risk params, active watchlist
│   └── trading_portfolio.json  ← open positions + unrealized P&L
└── core/brain.py               ← register trading tools + triggers (modified)
```

### Background loop

`trading_engine.py` runs as a daemon thread using the same pattern as `core/proactive.py`. It wakes every 15 minutes, runs the signal cycle, and goes back to sleep. Starting and stopping is exposed via `trading_tool.py`. The engine holds a reference to the Jarvis TTS speak function so it can announce trade events.

### Alpaca integration

- SDK: `alpaca-py` (official Alpaca Python SDK)
- Paper endpoint: `https://paper-api.alpaca.markets`
- Live endpoint: `https://api.alpaca.markets`
- Credentials: `ALPACA_API_KEY`, `ALPACA_SECRET_KEY` in `.env`
- Mode flag: `ALPACA_MODE=paper` (default) or `ALPACA_MODE=live` in `.env`
- Switching modes updates `.env` and restarts the Alpaca client; no other code changes

---

## Strategy (Hybrid)

### Default watchlist
SPY, QQQ, AAPL, NVDA, MSFT — liquid instruments with tight spreads, strong news coverage, and fractional share support on Alpaca.

### 15-minute cycle (per symbol)

```
1. Fetch last 100 one-hour OHLCV bars from Alpaca historical data API
2. Compute RSI(14), MACD(12, 26, 9), EMA(20), EMA(50)
3. Classify signal:

   STRONG BUY  → RSI < 28  AND MACD bullish crossover  AND price > EMA20
   STRONG SELL → RSI > 72  AND MACD bearish crossover  AND price < EMA20
   AMBIGUOUS   → any mixed condition (e.g. RSI < 35 but no MACD confirmation)
   HOLD        → no condition met

4. STRONG BUY/SELL → pass to risk_manager → execute if approved
   AMBIGUOUS       → call Claude (see below)
   HOLD            → skip
```

### Claude consultation (ambiguous signals)

When a signal is ambiguous, `trading_engine.py` calls Claude (claude-sonnet-4-6) with a structured prompt containing:
- Symbol, current price, RSI value, MACD histogram
- Last 20 one-hour candles (OHLCV as a compact table)
- Top 3 news headlines from `get_stock_news(symbol)` (existing tool)
- Current open positions count and remaining capacity

Claude returns `BUY`, `SELL`, or `HOLD` plus a one-line reason. The reason is stored in the trade log entry. Claude is never called for STRONG signals (only ambiguous ones) to keep API costs low.

### Market hours guard

The cycle skips signal computation entirely outside 9:30am–4:00pm US Eastern time on weekdays. The engine still wakes up every 15 minutes but exits immediately after the time check during off-hours. No Alpaca data calls, no Claude calls.

---

## Risk Management

All rules enforced by `risk_manager.py` before any order is sent to Alpaca. Rules cannot be bypassed by Claude's output.

### Position sizing
- Max **10%** of total portfolio value per single position
- Fractional shares used automatically if needed (Alpaca supports this)
- Example: $1,000 wallet → max $100 per trade → ~0.22 shares of SPY at $450

### Per-position exits
- **Stop-loss: −8%** from entry price — immediate market sell, no Claude consultation
- **Take-profit: +15%** from entry price — immediate market sell, locked gain

Stop-loss and take-profit are implemented as Alpaca bracket orders, meaning they are submitted to the exchange at trade entry and execute server-side even if Jarvis is offline.

### Daily circuit breaker
- If total portfolio value drops **>5%** from the day's opening value, the engine stops trading for the remainder of that calendar day
- Jarvis speaks: *"Daily loss limit reached. Trading paused until tomorrow."*
- Engine resumes automatically at next market open

### Hard limits (non-configurable)
- Max **5 open positions** simultaneously
- **No leverage, no margin** — cash account only
- **No short selling** in Phase 1

### Configurable parameters (defaults shown)
All stored in `data/trading_config.json` and adjustable via voice:

| Parameter | Default | Voice command example |
|---|---|---|
| `max_position_pct` | 10% | "Jarvis, set max position to 8%" |
| `stop_loss_pct` | 8% | "Jarvis, set stop-loss to 6%" |
| `take_profit_pct` | 15% | "Jarvis, set take-profit to 20%" |
| `daily_loss_limit_pct` | 5% | "Jarvis, set daily loss limit to 3%" |
| `max_open_positions` | 5 | "Jarvis, set max positions to 3" |

---

## Tools (registered in brain.py)

Trigger keywords added to brain.py: `"trade"`, `"invest"`, `"portfolio"`, `"position"`, `"alpaca"`, `"holding"`, `"watchlist trading"`.

| Function | Description |
|---|---|
| `start_trading_engine()` | Start the 15-min background loop |
| `stop_trading_engine()` | Pause trading (positions remain open) |
| `get_trading_status()` | Running state, mode (paper/live), last trade timestamp |
| `get_trading_portfolio()` | Open positions with entry price, current price, unrealized P&L |
| `get_trade_history(n=20)` | Last N executed trades with signal reason |
| `get_trading_summary()` | Daily and weekly P&L, win rate, total trades |
| `set_risk_params(...)` | Update any configurable risk parameter |
| `switch_to_paper_mode()` | Route orders to Alpaca sandbox |
| `switch_to_live_mode()` | Route to real money — requires second explicit confirmation |
| `add_trading_symbol(symbol)` | Add ticker to active watchlist |
| `remove_trading_symbol(symbol)` | Remove ticker from active watchlist |

### Live mode confirmation flow
`switch_to_live_mode()` returns a challenge string: *"This will trade with real money. Say 'confirm live trading' to proceed."* The function does nothing until called a second time with `confirmed=True`. This prevents accidental activation via a misheard voice command.

---

## TTS Announcements

Jarvis speaks on every significant event using the existing TTS pipeline:

| Event | Announcement |
|---|---|
| Trade executed (buy) | "Bought 2 shares of SPY at $451.30 — RSI oversold, MACD confirmed." |
| Trade executed (sell — take profit) | "Sold NVDA — target reached at $892, up 15% from entry." |
| Trade executed (sell — stop loss) | "Sold AAPL — stop-loss triggered at $182.10, down 8% from entry." |
| Daily circuit breaker | "Daily loss limit reached. Trading paused until tomorrow." |
| Engine started | "Trading engine started in paper mode. Monitoring 5 symbols." |
| Engine stopped | "Trading engine stopped. 3 positions remain open." |

---

## Data Files

### `data/trading_config.json`
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

### `data/trades.json`
Array of trade entries:
```json
{
  "id": "uuid",
  "symbol": "SPY",
  "side": "buy",
  "qty": 0.22,
  "price": 451.30,
  "timestamp": "2026-06-20T14:32:00",
  "signal": "STRONG_BUY",
  "rsi": 27.4,
  "macd": 0.32,
  "claude_reason": null,
  "alpaca_order_id": "abc123"
}
```

### `data/trading_portfolio.json`
Open positions synced from Alpaca at each cycle, augmented with entry data from trades.json.

---

## Environment Variables Added

```
ALPACA_API_KEY=your_key_here
ALPACA_SECRET_KEY=your_secret_here
ALPACA_MODE=paper
```

---

## Phase 2 (Future — Binance Crypto)

After Phase 1 is stable:
- Add `core/binance_engine.py` mirroring `trading_engine.py` but using `python-binance` SDK
- Add `data/crypto_config.json`, `data/crypto_trades.json`
- Same signals.py and risk_manager.py reused (24/7 cycle, no market hours guard)
- Same TTS announcements pattern
- Tools: `start_crypto_trading()`, `stop_crypto_trading()`, etc.

EGX (Egyptian stocks) deferred indefinitely — no public broker trading API available.

---

## Out of Scope (Phase 1)

- Crypto (Phase 2)
- Forex trading
- EGX / Egyptian stocks
- Short selling
- Options or derivatives
- Margin or leverage
- Backtesting engine (future nice-to-have)
- Web dashboard / charting UI
