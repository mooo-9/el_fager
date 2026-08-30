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
    "my trading stats", "trading performance",
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

_GATE_CHECK_KEYWORDS = [
    "ready for real trading",
    "passed the paper trading",
    "paper trading gate",
    "paper trading results",
    "am i ready to go live",
    "how are we doing trading",
]

_CONFIRM_LIVE_KEYWORDS = [
    "confirm real trading",
    "confirm live trading",
    "activate real trading",
    "activate live trading",
    "go live with trading",
    "switch to real trading",
    "switch to live trading",
]

_CANCEL_LIVE_KEYWORDS = [
    "cancel live trading",
    "cancel real trading",
    "abort live trading",
    "stop live trading activation",
]

_HEALTH_FOOD_KEYWORDS = [
    "i just ate", "i ate", "i just had", "log meal", "log food",
    "nutrition", "calories today", "how many calories", "macro", "macros",
    "protein today", "what did i eat", "log what i ate",
    "recipe", "give me a recipe", "how do i make", "how to make",
    "what can i make", "what can i cook", "suggest a meal", "chef",
    "cook", "cooking", "ingredient", "ingredients",
    "my stats", "daily target", "set my daily",
    "calorie target",
    "breakfast", "lunch", "dinner", "snack", "meal",
]

_HEALTH_GYM_KEYWORDS = [
    "gym", "workout", "training", "exercise",
    "chest day", "back day", "leg day", "push day", "pull day",
    "shoulder day", "arm day", "upper body", "lower body",
    "bench press", "squat", "deadlift", "sets", "reps",
    "progressive overload", "my split", "training split",
    "just finished", "finished chest", "finished back", "finished leg",
    "rest day", "how's my bench", "bench progress",
    "what should i do today", "today's workout", "today's session",
    "generate a program", "create a program", "training plan",
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
    ("confirm_live", _CONFIRM_LIVE_KEYWORDS),  # checked before gate_check and stocks
    ("cancel_live", _CANCEL_LIVE_KEYWORDS),    # checked before gate_check and stocks
    ("gate_check", _GATE_CHECK_KEYWORDS),      # checked before generic "stocks"
    ("stocks", _STOCKS_KEYWORDS),
    ("health", _HEALTH_FOOD_KEYWORDS + _HEALTH_GYM_KEYWORDS),
    ("research", _RESEARCH_KEYWORDS),
    ("file", _FILE_KEYWORDS),
]


def classify_intent(message: str) -> str:
    """Return the agent label that should handle this message.

    Returns one of: 'screen', 'browser', 'stocks_agent', 'confirm_live',
    'cancel_live', 'gate_check', 'stocks', 'research', 'file', 'instant'.
    Uses keyword matching. First match wins.
    """
    import re
    msg = message.lower()
    for label, keywords in _LABEL_KEYWORDS:
        for kw in keywords:
            pattern = r"\b" + re.escape(kw) + r"\b"
            if re.search(pattern, msg):
                return label
    return "instant"


def parse_callsign(message: str) -> tuple[str, str] | None:
    """Detect Mo addressing one agent by name: 'Sage, research X'.

    Returns (tool_name, task) or None. Both 'Sage, do X' and 'Sage do X' match --
    Whisper drops commas often enough that requiring one would miss most spoken
    invocations.
    """
    import re
    from core.agents.registry import ROSTER

    if not message:
        return None
    text = message.strip().lstrip("-*").strip()
    for spec in ROSTER.values():
        pattern = rf"^{re.escape(spec.callsign)}\b[\s,:]+(.+)$"
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            task = match.group(1).strip()
            if len(task) >= 3:
                return spec.tool_name, task
    return None
