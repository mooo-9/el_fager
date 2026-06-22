from core.agents.router import classify_intent

def test_screen_click():
    assert classify_intent("click the submit button") == "screen"

def test_screen_drag():
    assert classify_intent("drag the file to the folder") == "screen"

def test_browser_book():
    assert classify_intent("book me a table at Cairo Kitchen") == "browser"

def test_browser_login():
    assert classify_intent("log into my university portal and check my grades") == "browser"

def test_stocks_keyword():
    assert classify_intent("what's the stock price of NVDA?") == "stocks"

def test_research_keyword():
    assert classify_intent("research everything about Egypt's economy this week") == "research"

def test_file_pdf():
    assert classify_intent("summarize this pdf for me") == "file"

def test_instant_weather():
    assert classify_intent("what is the weather in Cairo?") == "instant"

def test_instant_music():
    assert classify_intent("play something on Spotify") == "instant"

def test_case_insensitive():
    assert classify_intent("CLICK the button") == "screen"

def test_stocks_ticker_only():
    assert classify_intent("How is BTC doing today?") == "stocks"
