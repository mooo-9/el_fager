# El Fager v2 — Design Spec
**Date:** 2026-06-22  
**Status:** Approved

---

## Mission

El Fager is an autonomous personal JARVIS for Windows. It sees and controls the entire computer, automates any website, researches any topic, understands documents, and grows capital through intelligent stock market trading. Always present. Always learning. One voice command away.

---

## Architecture Overview

### Two-Lane Orchestrator

Brain.py routes every request into one of two lanes:

**Instant lane (<1s):** Direct tool dispatch for everyday commands — weather, Spotify, clipboard, calendar, system stats, WhatsApp, Telegram, files, etc. The existing 355 tools handle this lane unchanged.

**Agent lane (2–30s):** Complex multi-step tasks routed to a specialist agent. The orchestrator classifies intent and picks the right agent. Voice UX stays fast for simple commands; power goes to agents for complex ones.

```
Voice/Text Input
      │
      ▼
  Intent Classifier (brain.py)
      │
  ┌───┴──────────────────────────────────────────┐
  │ INSTANT (<1s)                                │ AGENT DISPATCH (2-30s)
  │ weather, Spotify, clipboard, calendar,       │ ScreenAgent
  │ system, files, Telegram, WhatsApp, etc.      │ BrowserAgent
  │ → direct tool call                           │ StocksAgent
  └──────────────────────────────────────────────┘ ResearchAgent
                                                    FileAgent
```

---

## The Five Specialist Agents

### 1. ScreenAgent
**Path:** `core/agents/screen_agent.py`  
**Purpose:** Sees the screen and controls any application autonomously.

**Capabilities:**
- Takes screenshots and sends to Claude Vision to understand what is on screen
- Clicks, types, scrolls, and drags on any application via pyautogui
- Reads content from any window including non-web apps
- Executes multi-step GUI tasks end-to-end without human direction

**Tech stack:** `mss` (fast screenshots), `pyautogui` (mouse/keyboard control), `win32gui` (window management), Claude Vision API (screen understanding)

**Example tasks:**
- "Open my email, find the latest invoice, download it"
- "In Excel, sort column B and save the file"
- "Take a screenshot of this chart and describe it"

---

### 2. BrowserAgent
**Path:** `core/agents/browser_agent.py`  
**Purpose:** Automates any website end-to-end.

**Capabilities:**
- Navigates any URL, clicks buttons, fills forms, extracts data
- Handles authentication using credentials stored in the local encrypted vault
- Works with JavaScript-heavy SPAs and dynamic pages
- Downloads files, handles popups and dialogs

**Tech stack:** `playwright` (Chromium), encrypted local credentials vault (`cryptography` library, Fernet symmetric encryption, stored at `data/vault.enc`)

**Example tasks:**
- "Book a table at X restaurant"
- "Check my bank balance"
- "Search flights from Cairo to Dubai next month and find the cheapest"
- "Log into my university portal and check my grades"

---

### 3. StocksAgent
**Path:** `core/agents/stocks_agent.py`  
**Purpose:** Dedicated market expert — analyses, decides, trades, and explains.

#### Sub-components:

**MarketAnalyst**
- Technical signals: RSI, MACD, EMA20/50, Bollinger Bands, Volume
- Fundamental data: P/E ratio, earnings growth, revenue trend (yfinance)
- Sentiment: news headlines scored bullish/bearish (NewsAPI)
- Outputs a conviction score (0–100%) per stock with full reasoning text

**StrategyEngine**
- Three strategies running in parallel:
  - Momentum swing — rides trending stocks
  - Mean reversion — catches oversold bounces
  - Earnings momentum — trades post-earnings drift
- Market regime detection (bull / bear / sideways) — weights which strategy gets priority
- Outputs: BUY / SELL / HOLD with conviction level and reasoning

**RiskManager (calibrated for $10–20 account)**
- Fractional shares required on all trades
- Maximum 3 open positions simultaneously
- Maximum 33% of total capital per position (~$3–6 per trade)
- Stop loss: 5% per trade
- Take profit: 12% per trade
- Swing trading only (hold 1–7 days) — avoids Pattern Day Trader rule
- Daily loss limit: if down >10% in one day, auto-pauses all trading and notifies user

**ExplainEngine**
- Answers natural language questions about every decision:
  - "Why did you buy NVDA?" → full signal reasoning
  - "How are we doing?" → P&L, win rate, open positions, best/worst trade
  - "What's your thesis on AAPL right now?" → current signal analysis
- Every auto-executed trade generates a plain-language notification

#### Autonomous Trading Tiers

| Conviction Level | Condition | Action |
|---|---|---|
| **High (≥ 85%)** | All 3 signal types agree + risk/reward ≥ 2.5 | Auto-executes, notifies after |
| **Medium (60–85%)** | 2 of 3 signals agree | Notifies user, auto-executes in 60s unless cancelled |
| **Low (<60%)** | Weak or conflicting signals | Asks for confirmation |

**What constitutes 85%+ conviction:**
- RSI, MACD, EMA all aligned in same direction
- Fundamental trend supports the move
- News sentiment confirms direction
- Risk/reward ratio ≥ 2.5
- Volume above average confirming the move

**Safety guardrails (always active, never override-able):**
- Daily loss limit: >10% down in one day → auto-pause + notify
- Per-trade max always enforced (33% capital, fractional)
- "pause trading" voice command → immediately freezes all autonomous action
- Every autonomous trade → push notification to user after execution
- Confidence threshold is user-adjustable: "set auto-trade threshold to 90%"
- Starting threshold: **85%**

**Stock universe:** S&P 500 components + SPY/QQQ ETFs. Filtered for: >10M daily volume, fractional-eligible on Alpaca, and price trend.

#### Paper → Real Money Gate

The agent earns real money access by meeting **all** of the following over a 3-month paper trading window:

| Metric | Required |
|---|---|
| Completed trades | ≥ 30 |
| Win rate | ≥ 52% |
| Sharpe ratio | ≥ 1.0 |
| Max drawdown | ≤ 15% |
| Profit factor | ≥ 1.3 |

When all criteria are met, El Fager announces: *"StocksAgent has passed all validation criteria. Ready to trade real money. Say 'confirm real trading' to activate."*

User says it. El Fager asks once more. On second confirmation, switches to live Alpaca account.

---

### 4. ResearchAgent
**Path:** `core/agents/research_agent.py`  
**Purpose:** Deep research across the web — synthesizes answers, not just links.

**Capabilities:**
- Searches multiple sources (web, news, Wikipedia, arXiv for academic topics)
- Reads and extracts key content from multiple pages
- Synthesizes into a single coherent answer with sources cited
- Separate from BrowserAgent: BrowserAgent *executes tasks*, ResearchAgent *synthesizes knowledge*

**Tech stack:** DuckDuckGo search API (free, no key required; SerpAPI optional paid upgrade), Playwright (deep page reading), NewsAPI, Wikipedia API

**Example tasks:**
- "What's causing NVDA's recent price drop?"
- "Research the best Python libraries for data visualization"
- "Summarize everything happening with the Egypt economy this week"

---

### 5. FileAgent
**Path:** `core/agents/file_agent.py`  
**Purpose:** Document intelligence — understands the content inside files, not just their names.

**Capabilities:**
- Summarizes PDFs, Word documents, text files
- Extracts specific data from documents (prices, names, dates)
- OCR on images and scanned documents
- Semantic search across a folder of documents
- Organizes and renames files intelligently

**Tech stack:** `pdfplumber` (PDFs), `python-docx` (Word), `pytesseract` (OCR), semantic search via ChromaDB (already in stack)

**Example tasks:**
- "Summarize my thesis PDF"
- "Find all files where I mentioned project X"
- "Extract all the invoice amounts from my Documents folder"
- "What did this contract say about payment terms?"

---

## UI Layer (Already Designed)

Two full-screen modes, one toggle button:

**Mode 1 — JARVIS Voice HUD:** Pure black (#04080f), large central pulsing reactor orb, live audio waveform arc, floating fading response text, Iron Man HUD corner brackets, minimal top bar (EL FAGER + time + trading status pill), slim bottom data strip (watchlist + P&L). Voice-only interface.

**Mode 2 — Trading Terminal:** Bloomberg/Reuters aesthetic (#0c0c0c), green on black, monospaced font, P&L curve chart, signal matrix table, open positions, trade history log. START / STOP / BACKTEST controls.

**Implementation:** PyQt6, consistent with existing overlay.py structure.

---

## Memory System

- **ChromaDB:** Episodic memory (conversations), semantic memory (facts about Mo), document index for FileAgent
- **SQLite:** Trade history, performance metrics, backtest results
- **Encrypted local vault:** Service credentials for BrowserAgent (`data/vault.enc`, Fernet encryption via `cryptography` library, never sent to API)

---

## Voice Pipeline (Unchanged)

- STT: Whisper medium (CPU)
- TTS: Edge TTS
- Languages: Arabic, English, French, Arabizi — multilingual mixing supported
- Hotkey: Ctrl+Space
- Tray: always running, hidden window

---

## Development Phases

| Phase | What Gets Built | Outcome |
|---|---|---|
| **1** | ScreenAgent + BrowserAgent | Full computer + web control |
| **2** | StocksAgent upgrade | Multi-strategy + fundamental + sentiment + autonomous trading |
| **3** | ResearchAgent + FileAgent | Intelligence and document layer |
| **4** | JARVIS HUD + Trading Terminal UI | Full Iron Man aesthetic |
| **5** | Paper trading validation → Real money | Profit |

Phases 1 and 2 are the highest priority — they deliver the core JARVIS experience and the money goal.

---

## Key Technical Constraints

- **Python 3.14:** Use `pygame-ce` not `pygame`. No wheels exist for pygame on 3.14.
- **cp1252 safety:** No Unicode arrows, emojis, or Arabic in tool return strings — em-dash is safe.
- **Alpaca free plan:** Always use `feed=DataFeed.IEX` on all bar requests or get 403.
- **Alpaca fractional shares:** Required for $10–20 account. Verify fractional eligibility before placing orders.
- **PDT rule:** Maximum 3 intraday round-trips per rolling 5-day window. Swing trading (1–7 day holds) avoids this.
- **Startup time:** El Fager takes ~20s to load Whisper + Silero VAD. Normal — do not optimize.
- **OneDrive redirect:** Desktop = `C:\Users\Mohab1\OneDrive\Desktop`, Documents = `C:\Users\Mohab1\OneDrive\Documents`.

---

## Success Criteria

El Fager v2 is complete when:
1. You can say "open Excel, add a new row to column A, save it" and it executes without touching the keyboard
2. You can say "book a table at X" and it navigates the website and confirms the booking
3. StocksAgent passes all paper trading gate criteria and executes its first real trade autonomously
4. ResearchAgent answers "what's happening with NVDA?" with a synthesized, sourced answer
5. FileAgent summarizes any PDF you drop on it in under 30 seconds
6. Both UI modes are live and the toggle works
