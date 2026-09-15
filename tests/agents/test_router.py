from core.agents.router import classify_intent

def test_screen_click():
    assert classify_intent("click the submit button") == "screen"

def test_screen_drag():
    assert classify_intent("drag the file to the folder") == "screen"

def test_browser_book():
    assert classify_intent("book me a table at Cairo Kitchen") == "browser"

def test_browser_login():
    assert classify_intent("log into my university portal and check my grades") == "browser"

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

    def test_invest_does_not_match_investigate(self):
        from core.agents.router import classify_intent
        # Regression: word-boundary fix -- "investigate" must reach research,
        # not partially match another keyword.
        assert classify_intent("investigate the outage last night") == "research"
