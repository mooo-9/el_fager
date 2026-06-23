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


class TestResearchAndFileRouting:
    def test_research_everything_about_routes_to_research(self):
        from core.agents.router import classify_intent
        assert classify_intent("research everything about tech industry trends") == "research"

    def test_latest_news_routes_to_research(self):
        from core.agents.router import classify_intent
        assert classify_intent("latest news about Tesla") == "research"

    def test_investigate_routes_to_research(self):
        from core.agents.router import classify_intent
        assert classify_intent("investigate what happened with SVB") == "research"

    def test_pdf_keyword_routes_to_file(self):
        from core.agents.router import classify_intent
        assert classify_intent("summarize this pdf") == "file"

    def test_pdf_extension_routes_to_file(self):
        from core.agents.router import classify_intent
        assert classify_intent("what does thesis.pdf say about methodology?") == "file"

    def test_docx_extension_routes_to_file(self):
        from core.agents.router import classify_intent
        assert classify_intent("read contract.docx and find payment terms") == "file"

    def test_this_document_routes_to_file(self):
        from core.agents.router import classify_intent
        assert classify_intent("summarize this document for me") == "file"

    def test_payment_terms_routes_to_file(self):
        from core.agents.router import classify_intent
        assert classify_intent("what did this contract say about payment terms") == "file"


class TestGateCheckRouting:
    def test_ready_for_real_trading_routes_to_gate_check(self):
        from core.agents.router import classify_intent
        assert classify_intent("am I ready for real trading?") == "gate_check"

    def test_paper_trading_gate_routes_to_gate_check(self):
        from core.agents.router import classify_intent
        assert classify_intent("check my paper trading gate") == "gate_check"

    def test_invest_still_routes_to_stocks(self):
        from core.agents.router import classify_intent
        # Regression: word-boundary fix -- "invest" must not match "investigate"
        assert classify_intent("how should I invest my savings?") == "stocks"
