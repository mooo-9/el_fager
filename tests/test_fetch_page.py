"""fetch_page read nothing from Wikipedia, and nothing from pages that don't
wrap their text in <p> — both reported as "[No readable content found]"."""
import httpx
import pytest

from tools import web_tool


class FakeResponse:
    def __init__(self, status: int, html: str):
        self.status_code = status
        self.text = html


@pytest.fixture
def served(monkeypatch):
    sent = {}

    def serve(status=200, html=""):
        def get(url, headers=None, timeout=None, follow_redirects=None):
            sent["url"], sent["headers"] = url, headers or {}
            return FakeResponse(status, html)
        monkeypatch.setattr(httpx, "get", get)
        return sent

    return serve


def test_wikipedia_gets_the_identifying_user_agent_it_requires(served):
    # Wikipedia answers 403 to an anonymous or browser-pretending client.
    sent = served(html="<p>Cairo is the capital of Egypt.</p>")
    assert "Cairo" in web_tool.fetch_page("https://en.wikipedia.org/wiki/Cairo")
    assert sent["headers"]["User-Agent"].startswith("ElFager/")


def test_other_sites_get_a_plain_browser_user_agent(served):
    # Mo's contact details go only where they're required.
    sent = served(html="<p>News.</p>")
    web_tool.fetch_page("https://www.bbc.com/news")
    assert sent["headers"]["User-Agent"].startswith("Mozilla/")
    assert "@" not in sent["headers"]["User-Agent"]


def test_a_blocked_page_says_it_was_blocked(served):
    served(status=403, html="Forbidden")
    out = web_tool.fetch_page("https://trustpadel.com/x")
    assert out.startswith("[fetch failed") and "403" in out


def test_a_page_without_paragraphs_falls_back_to_its_visible_text(served):
    served(html="""<html><head><style>.x{}</style><script>var a=1;</script></head>
        <body><nav>Menu</nav><div><span>Egypt inflation</span> <b>14.9%</b> in July 2026</div>
        <footer>Footer</footer></body></html>""")
    out = web_tool.fetch_page("https://tradingeconomics.com/egypt/inflation-cpi")
    assert "Egypt inflation" in out and "14.9%" in out
    assert "var a" not in out and ".x{}" not in out


def test_words_stay_apart_across_inline_tags(served):
    served(html='<p>Cairo is the <a href="/c">capital</a> and <b>largest city</b> of '
                '<a href="/e">Egypt</a> and the Cairo Governorate, home to millions.</p>' * 5)
    out = web_tool.fetch_page("https://en.wikipedia.org/wiki/Cairo")
    assert "the capital and largest city of Egypt" in out
