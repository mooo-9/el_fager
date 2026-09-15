import urllib.parse

# Comet is a Perplexity browser, so its own search is the natural surface
# for an open-ended "look this up for me".
_SEARCH_URL = "https://www.perplexity.ai/search?q={}"


def web_search(query: str, max_results: int = 5) -> str:
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append(f"- {r['title']}\n  {r['href']}\n  {r['body'][:200]}")
        if not results:
            return "No results found."
        combined = "\n\n".join(results)
        if len(combined) > 3000:
            combined = combined[:3000] + "\n[... truncated]"
        return combined
    except Exception as e:
        return f"[web_search failed: {e}]"


# Wikipedia refuses anonymous and browser-pretending clients alike and wants
# contact details — the same identity tools/wikipedia_tool.py already sends.
# Every other site gets a plain browser User-Agent, so Mo's details go nowhere
# they aren't required.
_WIKI_UA = "ElFager/1.0 (mohabmohamed154@gmail.com)"
_BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36")


def fetch_page(url: str, max_chars: int = 3000) -> str:
    try:
        import httpx
        from bs4 import BeautifulSoup
        host = urllib.parse.urlparse(url).hostname or ""
        wiki = host.endswith(("wikipedia.org", "wikimedia.org"))
        headers = {"User-Agent": _WIKI_UA if wiki else _BROWSER_UA,
                   "Accept-Language": "en-US,en;q=0.9"}
        resp = httpx.get(url, headers=headers, timeout=8, follow_redirects=True)
        if resp.status_code >= 400:
            return (f"[fetch failed: HTTP {resp.status_code} — the site blocks automated "
                    f"reading; open it in Comet for Mo instead]")
        soup = BeautifulSoup(resp.text, "html.parser")
        # A separator keeps words apart across inline tags: "the<a>capital</a>"
        # read as "thecapital".
        paragraphs = [" ".join(p.get_text(" ", strip=True).split()) for p in soup.find_all("p")]
        paragraphs = [p for p in paragraphs if p]
        text = "\n\n".join(paragraphs)
        if len(text) < 200:
            # Plenty of pages (prices, stats, listings) keep their text out of
            # <p>; those read as empty. Take the page's visible text instead.
            for tag in soup(["script", "style", "noscript", "svg", "nav", "footer", "header"]):
                tag.decompose()
            visible = " ".join(soup.get_text(" ", strip=True).split())
            if len(visible) > len(text):
                text = visible
        if len(text) > max_chars:
            text = text[:max_chars] + "\n[... truncated]"
        return text if text else "[No readable content found]"
    except Exception as e:
        return f"[fetch failed: {e}]"


def open_web_search(task: str) -> str:
    """Open a web search for `task` in Comet so Mo can read it himself.

    web_search() is the other half of this: it reads the web and answers.
    This one hands Mo the browser.
    """
    from tools.comet_tool import open_url
    url = _SEARCH_URL.format(urllib.parse.quote_plus(task))
    used_comet = open_url(url)
    where = "Comet" if used_comet else "your default browser (Comet not found)"
    return f"Searching '{task}' in {where}."
