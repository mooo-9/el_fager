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


def fetch_page(url: str, max_chars: int = 3000) -> str:
    try:
        import httpx
        from bs4 import BeautifulSoup
        resp = httpx.get(url, timeout=8, follow_redirects=True)
        soup = BeautifulSoup(resp.text, "html.parser")
        paragraphs = [p.get_text(strip=True) for p in soup.find_all("p") if p.get_text(strip=True)]
        text = "\n\n".join(paragraphs)
        if len(text) > max_chars:
            text = text[:max_chars] + "\n[... truncated]"
        return text if text else "[No readable content found]"
    except Exception as e:
        return f"[fetch failed: {e}]"
