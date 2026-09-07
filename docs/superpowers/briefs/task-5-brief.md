# Task 5 Brief: Router refinement + brain.py wiring

## Context
El Fager project at `C:\claude proj\el_fager`. Tasks 1-4 complete — 127 tests passing. You are implementing Task 5: adding a `stocks_agent` intent to the router and wiring StocksAgent into brain.py's `_try_agent_dispatch()`.

## Global Constraints
- Python 3.14 compatible
- No new pip installs
- `python -m pytest` from `C:\claude proj\el_fager`; existing 127 tests must stay green
- Do NOT restructure or rewrite brain.py — make the minimum targeted change

## Files to modify
- `core/agents/router.py` — add `_STOCKS_AGENT_KEYWORDS` and "stocks_agent" label
- `core/brain.py` — add `if intent == "stocks_agent"` branch in `_try_agent_dispatch()`
- `tests/agents/test_router.py` — add tests for "stocks_agent" intent

## Current state of router.py
The file currently has: `_SCREEN_KEYWORDS`, `_BROWSER_KEYWORDS`, `_STOCKS_KEYWORDS`, `_RESEARCH_KEYWORDS`, `_FILE_KEYWORDS`, and `_LABEL_KEYWORDS` list. The `classify_intent()` function does keyword matching, first match wins.

## Current state of brain.py `_try_agent_dispatch()` (around line 5953)
```python
def _try_agent_dispatch(self, task: str) -> str | None:
    """Route complex tasks to a specialist agent. Returns None for instant-lane tasks."""
    from core.agents.router import classify_intent
    intent = classify_intent(task)
    if intent == "screen":
        from core.agents.screen_agent import ScreenAgent
        return ScreenAgent().run(task)
    if intent == "browser":
        from core.agents.browser_agent import BrowserAgent
        return BrowserAgent().run(task)
    return None  # stocks / research / file not yet implemented -- fall through
```

## What the new router.py must look like (replace entire file)

```python
# Keywords that map to each agent.
# Priority: first match wins -- order of checks in classify_intent matters.
_SCREEN_KEYWORDS = [
    "click", "double click", "right click", "scroll up", "scroll down",
    "type in", "press enter", "press tab", "press escape", "drag",
    "hotkey", "what's on my screen", "look at my screen",
    "open and then", "control the app", "automate the", "desktop app",
    "take a screenshot", "what do you see", "describe the screen",
    "what error is showing", "what's open",
]

_BROWSER_KEYWORDS = [
    "website", "webpage", "navigate to", "go to http", "go to www",
    "book a table", "book me a", "book a flight", "search flights",
    "log into", "login to", "log in to", "sign in to",
    "fill out", "fill in", "submit the form",
    "university portal", "online portal", "bank account", "check my bank",
    "open browser", "browse to", ".com", ".org", ".net", ".eg",
    "search on google", "search on amazon",
]

# StocksAgent handles ANALYTICAL and AGENTIC stock tasks.
# Checked BEFORE _STOCKS_KEYWORDS so these take priority.
_STOCKS_AGENT_KEYWORDS = [
    "analyze", "thesis on", "your thesis",
    "should i buy", "should i sell", "should we buy",
    "your view on", "your opinion on",
    "what do you think about", "what's your take on",
    "conviction on", "outlook for", "stock outlook",
    "deep analysis", "deep dive",
    "why did you buy", "why did we buy",
    "why did you sell", "why did we sell",
    "how are we doing trading", "my trading stats", "trading performance",
    "scan my watchlist", "scan portfolio", "scan watchlist",
    "pause trading", "resume trading", "unpause trading",
    "stop auto-trade", "start auto-trade",
    "set auto-trade threshold", "set threshold",
    "auto-trade threshold", "auto trade threshold",
    "explain my portfolio", "explain my trades",
]

# Instant-lane stock tools: price lookups, watchlist, alerts, market overview.
_STOCKS_KEYWORDS = [
    "stock", "stocks", "trade", "trading", "portfolio", "ticker",
    "buy shares", "sell shares", "invest", "investing", "investment",
    "trading engine", "trading agent", "open positions", "trade history",
    "bull", "bear", "bullish", "bearish", "earnings", "dividend",
    "p/e ratio", "rsi", "macd", "moving average",
    "nvda", "aapl", "msft", "amzn", "googl", "meta", "tsla",
    "spy", "qqq", "btc", "eth", "crypto",
]

_RESEARCH_KEYWORDS = [
    "research everything", "deep dive into", "find out everything about",
    "investigate", "comprehensive analysis of", "tell me everything about",
    "summarize the news about", "latest news about",
    "everything happening with", "what do we know about",
    "research the best", "compare and contrast",
]

_FILE_KEYWORDS = [
    ".pdf", ".docx", ".xlsx", ".doc", ".pptx",
    "this pdf", "this document", "this file", "this contract",
    "read this pdf", "summarize this pdf", "summarize this document",
    "what does this file say", "extract from this",
    "this invoice", "this thesis", "this report", "this spreadsheet",
    "payment terms", "what did this contract",
]

_LABEL_KEYWORDS = [
    ("screen", _SCREEN_KEYWORDS),
    ("browser", _BROWSER_KEYWORDS),
    ("stocks_agent", _STOCKS_AGENT_KEYWORDS),  # checked before "stocks"
    ("stocks", _STOCKS_KEYWORDS),
    ("research", _RESEARCH_KEYWORDS),
    ("file", _FILE_KEYWORDS),
]


def classify_intent(message: str) -> str:
    """Return the agent label that should handle this message.

    Returns one of: 'screen', 'browser', 'stocks_agent', 'stocks',
    'research', 'file', 'instant'.
    Uses keyword matching. First match wins.
    """
    import re
    msg = message.lower()
    for label, keywords in _LABEL_KEYWORDS:
        for kw in keywords:
            if len(kw) <= 3:
                pattern = r"\b" + re.escape(kw) + r"\b"
                if re.search(pattern, msg):
                    return label
            elif kw in msg:
                return label
    return "instant"
```

## brain.py change — find and replace only `_try_agent_dispatch` body

Find this exact block in `core/brain.py`:
```python
    def _try_agent_dispatch(self, task: str) -> str | None:
        """Route complex tasks to a specialist agent. Returns None for instant-lane tasks."""
        from core.agents.router import classify_intent
        intent = classify_intent(task)
        if intent == "screen":
            from core.agents.screen_agent import ScreenAgent
            return ScreenAgent().run(task)
        if intent == "browser":
            from core.agents.browser_agent import BrowserAgent
            return BrowserAgent().run(task)
        return None  # stocks / research / file not yet implemented -- fall through
```

Replace with:
```python
    def _try_agent_dispatch(self, task: str) -> str | None:
        """Route complex tasks to a specialist agent. Returns None for instant-lane tasks."""
        from core.agents.router import classify_intent
        intent = classify_intent(task)
        if intent == "screen":
            from core.agents.screen_agent import ScreenAgent
            return ScreenAgent().run(task)
        if intent == "browser":
            from core.agents.browser_agent import BrowserAgent
            return BrowserAgent().run(task)
        if intent == "stocks_agent":
            from core.agents.stocks_agent import StocksAgent
            return StocksAgent().run(task)
        return None  # research / file not yet implemented -- fall through
```

## Tests to add to `tests/agents/test_router.py`

Open the existing file and APPEND these new test classes at the bottom (do not remove existing tests):

```python


class TestStocksAgentRouting:
    def test_analyze_keyword_routes_to_stocks_agent(self):
        from core.agents.router import classify_intent
        assert classify_intent("analyze NVDA for me") == "stocks_agent"

    def test_thesis_keyword_routes_to_stocks_agent(self):
        from core.agents.router import classify_intent
        assert classify_intent("what's your thesis on AAPL?") == "stocks_agent"

    def test_should_i_buy_routes_to_stocks_agent(self):
        from core.agents.router import classify_intent
        assert classify_intent("should I buy MSFT right now?") == "stocks_agent"

    def test_why_did_you_buy_routes_to_stocks_agent(self):
        from core.agents.router import classify_intent
        assert classify_intent("why did you buy NVDA?") == "stocks_agent"

    def test_pause_trading_routes_to_stocks_agent(self):
        from core.agents.router import classify_intent
        assert classify_intent("pause trading please") == "stocks_agent"

    def test_set_threshold_routes_to_stocks_agent(self):
        from core.agents.router import classify_intent
        assert classify_intent("set auto-trade threshold to 90%") == "stocks_agent"

    def test_price_query_stays_instant_stocks(self):
        from core.agents.router import classify_intent
        result = classify_intent("what's the price of AAPL?")
        assert result == "stocks"

    def test_scan_watchlist_routes_to_stocks_agent(self):
        from core.agents.router import classify_intent
        assert classify_intent("scan my watchlist") == "stocks_agent"

    def test_scan_my_watchlist_routes_to_stocks_agent(self):
        from core.agents.router import classify_intent
        assert classify_intent("scan my watchlist for opportunities") == "stocks_agent"
```

## Steps
1. Run existing router tests first to confirm baseline: `python -m pytest tests/agents/test_router.py -v`
2. Append the new test class to `tests/agents/test_router.py`
3. Run `python -m pytest tests/agents/test_router.py -v` — new tests should FAIL (stocks_agent not in router yet)
4. Replace `core/agents/router.py` with the new content above
5. Run `python -m pytest tests/agents/test_router.py -v` — all pass
6. Edit `core/brain.py` — find and replace `_try_agent_dispatch` body as shown above
7. Run `python -m pytest --tb=short -q` — full suite green (127 + 9 = 136 expected)
8. Commit all three files: `git add core/agents/router.py core/brain.py tests/agents/test_router.py && git commit -m "feat: wire StocksAgent into agent router and brain dispatch"`

## Report
Write to: `C:\claude proj\el_fager\docs\superpowers\briefs\task-5-report.md`
Include: Status, commit hash, test count, concerns.
