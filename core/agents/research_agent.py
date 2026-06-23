"""
ResearchAgent -- synthesizes deep web research into a single coherent answer.
Searches DuckDuckGo, reads top pages via Playwright, synthesizes via Claude Haiku.
"""
from core.agents.base_agent import BaseAgent

_MAX_SEARCH_RESULTS = 5
_MAX_PAGES_TO_READ = 2
_MAX_PAGE_CHARS = 3000  # per page, keeps Haiku prompt under token budget

_STRIP_PREFIXES = [
    "research everything about",
    "research everything on",
    "find out everything about",
    "tell me everything about",
    "research the best",
    "summarize the news about",
    "latest news about",
    "everything happening with",
    "what do we know about",
    "comprehensive analysis of",
    "compare and contrast",
    "deep dive into",
    "investigate",
]


class ResearchAgent(BaseAgent):
    @property
    def name(self) -> str:
        return "research"

    @property
    def description(self) -> str:
        return "Deep web research -- searches multiple sources and synthesizes answers."

    def run(self, task: str) -> str:
        query = self._extract_query(task)
        results = self._search(query)
        if not results:
            return f"No search results found for: {query}"

        page_texts = []
        for r in results[:_MAX_PAGES_TO_READ]:
            text = self._read_page(r["href"])
            if text:
                page_texts.append({"url": r["href"], "title": r["title"], "text": text})

        if not page_texts:
            # Fall back to search snippets when page reading fails
            for r in results:
                page_texts.append({"url": r["href"], "title": r["title"], "text": r.get("body", "")})

        return self._synthesize(query, page_texts)

    def _extract_query(self, task: str) -> str:
        task_lower = task.lower()
        for prefix in _STRIP_PREFIXES:
            if task_lower.startswith(prefix):
                return task[len(prefix):].strip()
        return task.strip()

    def _search(self, query: str) -> list[dict]:
        try:
            from duckduckgo_search import DDGS
            with DDGS() as ddgs:
                return list(ddgs.text(query, max_results=_MAX_SEARCH_RESULTS))
        except Exception:
            return []

    def _read_page(self, url: str) -> str:
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(url, timeout=8000, wait_until="domcontentloaded")
                text = page.inner_text("body")
                browser.close()
                return text[:_MAX_PAGE_CHARS]
        except Exception:
            return ""

    def _synthesize(self, query: str, sources: list[dict]) -> str:
        context_parts = []
        for i, src in enumerate(sources, 1):
            context_parts.append(
                f"[{i}] {src['title']}\nURL: {src['url']}\n{src['text'][:1500]}"
            )
        context = "\n\n".join(context_parts)

        prompt = (
            "You are El Fager's research engine. Based on the sources below, "
            "answer the query in 3-5 sentences. Be specific and cite sources as [1], [2] etc. "
            "No emojis. Plain English only.\n\n"
            f"Query: {query}\n\n"
            f"Sources:\n{context}"
        )

        try:
            import anthropic
            client = anthropic.Anthropic()
            resp = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=400,
                messages=[{"role": "user", "content": prompt}],
            )
            answer = resp.content[0].text.strip()
            source_lines = [f"[{i}] {s['url']}" for i, s in enumerate(sources, 1)]
            return answer + "\n\nSources:\n" + "\n".join(source_lines)
        except Exception:
            snippets = [
                f"[{i}] {s['title']}: {s['text'][:200]}"
                for i, s in enumerate(sources, 1)
            ]
            return f"Research on '{query}':\n" + "\n".join(snippets)
