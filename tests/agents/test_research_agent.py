from unittest.mock import patch, MagicMock
from core.agents.research_agent import ResearchAgent, _MAX_PAGE_CHARS


class TestExtractQuery:
    def test_strips_research_everything_about(self):
        assert ResearchAgent()._extract_query("research everything about NVDA") == "NVDA"

    def test_strips_summarize_the_news_about(self):
        assert ResearchAgent()._extract_query("summarize the news about Egypt economy") == "Egypt economy"

    def test_strips_latest_news_about(self):
        assert ResearchAgent()._extract_query("latest news about Tesla") == "Tesla"

    def test_plain_query_unchanged(self):
        assert ResearchAgent()._extract_query("Python data viz libraries") == "Python data viz libraries"


class TestSearch:
    def test_returns_list_on_success(self):
        mock_result = [{"title": "NVDA news", "href": "https://example.com", "body": "Strong momentum"}]
        with patch("duckduckgo_search.DDGS") as MockDDGS:
            inst = MockDDGS.return_value.__enter__.return_value
            inst.text.return_value = iter(mock_result)
            results = ResearchAgent()._search("NVDA")
        assert isinstance(results, list)
        assert results[0]["title"] == "NVDA news"

    def test_returns_empty_list_on_exception(self):
        with patch("duckduckgo_search.DDGS", side_effect=Exception("network error")):
            results = ResearchAgent()._search("anything")
        assert results == []


class TestReadPage:
    def test_returns_empty_string_on_playwright_failure(self):
        with patch("playwright.sync_api.sync_playwright", side_effect=Exception("no browser")):
            result = ResearchAgent()._read_page("https://example.com")
        assert result == ""

    def test_truncates_long_page_text(self):
        mock_pw = MagicMock()
        mock_pw.__enter__ = MagicMock(return_value=mock_pw)
        mock_pw.__exit__ = MagicMock(return_value=False)
        mock_browser = MagicMock()
        mock_page = MagicMock()
        mock_pw.chromium.launch.return_value = mock_browser
        mock_browser.new_page.return_value = mock_page
        mock_page.inner_text.return_value = "A" * 5000
        with patch("playwright.sync_api.sync_playwright", return_value=mock_pw):
            result = ResearchAgent()._read_page("https://example.com")
        assert len(result) <= _MAX_PAGE_CHARS
        mock_browser.close.assert_called_once()


class TestSynthesize:
    def test_returns_answer_with_sources(self):
        sources = [{"title": "NVDA drop", "url": "https://ex.com", "text": "Earnings missed"}]
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text="NVDA fell due to missed earnings [1].")]
        with patch("anthropic.Anthropic") as MockCl:
            MockCl.return_value.messages.create.return_value = mock_resp
            result = ResearchAgent()._synthesize("NVDA price drop", sources)
        assert "NVDA" in result
        assert "https://ex.com" in result

    def test_fallback_on_api_failure(self):
        sources = [{"title": "Test", "url": "https://ex.com", "text": "Some snippet here"}]
        with patch("anthropic.Anthropic", side_effect=Exception("API down")):
            result = ResearchAgent()._synthesize("test query", sources)
        assert isinstance(result, str)
        assert len(result) > 0


class TestRun:
    def test_returns_message_on_empty_search(self):
        with patch.object(ResearchAgent, "_search", return_value=[]):
            result = ResearchAgent().run("research everything about nothing")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_uses_snippets_when_page_read_fails(self):
        mock_results = [
            {"title": "T1", "href": "https://a.com", "body": "snippet A"},
            {"title": "T2", "href": "https://b.com", "body": "snippet B"},
        ]
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text="Summary from snippets.")]
        with patch.object(ResearchAgent, "_search", return_value=mock_results), \
             patch.object(ResearchAgent, "_read_page", return_value=""), \
             patch("anthropic.Anthropic") as MockCl:
            MockCl.return_value.messages.create.return_value = mock_resp
            result = ResearchAgent().run("latest news about test")
        assert isinstance(result, str)
        assert len(result) > 0
