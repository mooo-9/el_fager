# Keywords that map to each agent.
# Priority: first match wins — order of checks in classify_intent matters.
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

_STOCKS_KEYWORDS = [
    "stock", "stocks", "trade", "trading", "portfolio", "ticker",
    "buy shares", "sell shares", "invest", "investing", "investment",
    "trading engine", "trading agent", "open positions", "trade history",
    "bull", "bear", "bullish", "bearish", "earnings", "dividend",
    "p/e ratio", "rsi", "macd", "moving average",
    "NVDA", "AAPL", "MSFT", "AMZN", "GOOGL", "META", "TSLA",
    "SPY", "QQQ", "BTC", "ETH", "crypto",
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
    ("stocks", _STOCKS_KEYWORDS),
    ("research", _RESEARCH_KEYWORDS),
    ("file", _FILE_KEYWORDS),
]


def classify_intent(message: str) -> str:
    """Return the agent label that should handle this message.

    Returns one of: 'screen', 'browser', 'stocks', 'research', 'file', 'instant'.
    Uses keyword matching — same approach as _select_tools in brain.py.
    First match wins; falls back to 'instant' if nothing matches.
    """
    msg = message.lower()
    for label, keywords in _LABEL_KEYWORDS:
        if any(kw in msg for kw in keywords):
            return label
    return "instant"
