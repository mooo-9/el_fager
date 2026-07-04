# Phase 3: ResearchAgent + FileAgent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add ResearchAgent (deep web research + synthesis) and FileAgent (PDF/Word/image document intelligence) as the fourth and fifth specialist agents in El Fager's two-lane orchestrator.

**Architecture:** Each agent subclasses `BaseAgent`, lives in `core/agents/`, and is dispatched from `brain._try_agent_dispatch()` when `classify_intent()` returns `"research"` or `"file"`. Both use Claude Haiku for synthesis and fall back gracefully when external services are unavailable. The router already has keyword lists for both intents -- only brain.py wiring is missing.

**Tech Stack:** `duckduckgo_search` (web search, already installed), `playwright` (page reading, already installed + browsers installed for BrowserAgent), `pdfplumber` (PDFs, already installed), `python-docx` (Word docs, already installed), `pytesseract` + `Pillow` (OCR, already installed), `anthropic` (Haiku synthesis, already installed).

## Global Constraints

- Python 3.14 -- no walrus operator `:=`, no `match` statement
- cp1252 safety -- NO emojis, NO Arabic, NO U+2192 in any string returned from `run()`; prompt instructions ("No emojis.") are the primary guard, same as ExplainEngine
- No new pip installs -- all dependencies listed above are already in the environment
- `python -m pytest` from `C:\claude proj\el_fager`; existing 136 tests must stay green
- Use `claude-haiku-4-5-20251001` for all Anthropic calls (same as ExplainEngine)
- `max_tokens=400` for both agents (research answers are slightly longer than trade explanations)
- OneDrive redirect: Desktop = `C:\Users\Mohab1\OneDrive\Desktop`, Documents = `C:\Users\Mohab1\OneDrive\Documents`

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `core/agents/research_agent.py` | Create | DuckDuckGo search + Playwright page reading + Haiku synthesis |
| `core/agents/file_agent.py` | Create | Path resolution + PDF/DOCX/text/OCR extraction + Haiku Q&A |
| `tests/agents/test_research_agent.py` | Create | 12 tests for ResearchAgent |
| `tests/agents/test_file_agent.py` | Create | 14 tests for FileAgent |
| `core/brain.py` | Modify | Add `research` and `file` branches in `_try_agent_dispatch` |
| `tests/agents/test_router.py` | Modify | Append routing tests for `research` and `file` intents |

---

### Task 1: ResearchAgent -- web research + synthesis

**Files:**
- Create: `core/agents/research_agent.py`
- Test: `tests/agents/test_research_agent.py`

**Interfaces:**
- Consumes: `BaseAgent` ABC from `core/agents/base_agent.py`
- Produces: `ResearchAgent(BaseAgent)` with `run(task: str) -> str`, `_extract_query(task) -> str`, `_search(query) -> list[dict]`, `_read_page(url) -> str`, `_synthesize(query, sources) -> str`

- [ ] **Step 1: Write the tests file**

```python
# tests/agents/test_research_agent.py
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
```

- [ ] **Step 2: Run tests to confirm ModuleNotFoundError**

```
python -m pytest tests/agents/test_research_agent.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'core.agents.research_agent'`

- [ ] **Step 3: Write the implementation**

```python
# core/agents/research_agent.py
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
```

- [ ] **Step 4: Run tests -- all 12 should pass**

```
python -m pytest tests/agents/test_research_agent.py -v
```
Expected: 12 passed

- [ ] **Step 5: Run full suite to confirm no regressions**

```
python -m pytest --tb=short -q
```
Expected: 136 + 12 = 148 passed

- [ ] **Step 6: Commit**

```
git add core/agents/research_agent.py tests/agents/test_research_agent.py
git commit -m "feat: add ResearchAgent with DuckDuckGo search and Haiku synthesis"
```

---

### Task 2: FileAgent -- document intelligence

**Files:**
- Create: `core/agents/file_agent.py`
- Test: `tests/agents/test_file_agent.py`

**Interfaces:**
- Consumes: `BaseAgent` ABC from `core/agents/base_agent.py`
- Produces: `FileAgent(BaseAgent)` with `run(task: str) -> str`, `_resolve_path(task) -> Path | None`, `_extract_content(path) -> str`, `_read_pdf(path) -> str`, `_read_docx(path) -> str`, `_read_text(path) -> str`, `_ocr_image(path) -> str`, `_answer(task, path, content) -> str`
- Module-level: `_SEARCH_DIRS: list[Path]` -- tests monkeypatch this

- [ ] **Step 1: Write the tests file**

```python
# tests/agents/test_file_agent.py
from pathlib import Path
from unittest.mock import patch, MagicMock
from core.agents.file_agent import FileAgent


class TestResolvePath:
    def test_returns_none_when_no_file_mentioned(self):
        agent = FileAgent()
        assert agent._resolve_path("what is the weather today") is None

    def test_finds_pdf_by_name_in_search_dirs(self, tmp_path, monkeypatch):
        import core.agents.file_agent as fa
        test_file = tmp_path / "thesis.pdf"
        test_file.write_bytes(b"%PDF-1.4")
        monkeypatch.setattr(fa, "_SEARCH_DIRS", [tmp_path])
        result = FileAgent()._resolve_path("summarize thesis.pdf")
        assert result == test_file

    def test_finds_docx_by_name_in_search_dirs(self, tmp_path, monkeypatch):
        import core.agents.file_agent as fa
        test_file = tmp_path / "report.docx"
        test_file.write_bytes(b"PK")
        monkeypatch.setattr(fa, "_SEARCH_DIRS", [tmp_path])
        result = FileAgent()._resolve_path("summarize this document report.docx")
        assert result == test_file

    def test_finds_txt_by_name_in_search_dirs(self, tmp_path, monkeypatch):
        import core.agents.file_agent as fa
        test_file = tmp_path / "notes.txt"
        test_file.write_text("hello", encoding="utf-8")
        monkeypatch.setattr(fa, "_SEARCH_DIRS", [tmp_path])
        result = FileAgent()._resolve_path("read notes.txt")
        assert result == test_file


class TestReadPdf:
    def test_returns_extracted_text(self, tmp_path):
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "This is thesis content."
        mock_pdf = MagicMock()
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)
        mock_pdf.pages = [mock_page]
        with patch("pdfplumber.open", return_value=mock_pdf):
            result = FileAgent()._read_pdf(tmp_path / "test.pdf")
        assert "thesis content" in result

    def test_returns_empty_string_on_failure(self, tmp_path):
        with patch("pdfplumber.open", side_effect=Exception("corrupt")):
            result = FileAgent()._read_pdf(tmp_path / "bad.pdf")
        assert result == ""


class TestReadDocx:
    def test_returns_paragraph_text(self, tmp_path):
        mock_para = MagicMock()
        mock_para.text = "Contract clause 1."
        mock_doc = MagicMock()
        mock_doc.paragraphs = [mock_para]
        with patch("docx.Document", return_value=mock_doc):
            result = FileAgent()._read_docx(tmp_path / "contract.docx")
        assert "Contract clause 1." in result

    def test_returns_empty_string_on_failure(self, tmp_path):
        with patch("docx.Document", side_effect=Exception("bad file")):
            result = FileAgent()._read_docx(tmp_path / "bad.docx")
        assert result == ""


class TestReadText:
    def test_reads_plain_text_file(self, tmp_path):
        f = tmp_path / "notes.txt"
        f.write_text("Hello world", encoding="utf-8")
        result = FileAgent()._read_text(f)
        assert result == "Hello world"

    def test_returns_empty_string_on_missing_file(self, tmp_path):
        result = FileAgent()._read_text(tmp_path / "missing.txt")
        assert result == ""


class TestAnswer:
    def test_returns_haiku_answer(self, tmp_path):
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text="Payment terms are Net 30.")]
        with patch("anthropic.Anthropic") as MockCl:
            MockCl.return_value.messages.create.return_value = mock_resp
            result = FileAgent()._answer(
                "what are the payment terms?",
                tmp_path / "contract.pdf",
                "Pay within 30 days of invoice.",
            )
        assert isinstance(result, str)
        assert len(result) > 0

    def test_fallback_on_api_failure(self, tmp_path):
        with patch("anthropic.Anthropic", side_effect=Exception("API down")):
            result = FileAgent()._answer(
                "summarize", tmp_path / "doc.pdf", "Short content here."
            )
        assert "Short content here" in result or "doc.pdf" in result


class TestRun:
    def test_returns_helpful_message_when_no_file_found(self):
        result = FileAgent().run("what does this say about payments?")
        assert isinstance(result, str)
        assert "file" in result.lower() or "filename" in result.lower()

    def test_run_with_pdf_routes_through_read_pdf(self, tmp_path, monkeypatch):
        import core.agents.file_agent as fa
        test_file = tmp_path / "invoice.pdf"
        test_file.write_bytes(b"%PDF")
        monkeypatch.setattr(fa, "_SEARCH_DIRS", [tmp_path])
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text="Total amount is $500.")]
        with patch.object(FileAgent, "_read_pdf", return_value="Invoice total: $500"), \
             patch("anthropic.Anthropic") as MockCl:
            MockCl.return_value.messages.create.return_value = mock_resp
            result = FileAgent().run("what is the total in invoice.pdf?")
        assert isinstance(result, str)
        assert len(result) > 0
```

- [ ] **Step 2: Run tests to confirm ModuleNotFoundError**

```
python -m pytest tests/agents/test_file_agent.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'core.agents.file_agent'`

- [ ] **Step 3: Write the implementation**

```python
# core/agents/file_agent.py
"""
FileAgent -- reads and understands documents: PDFs, Word files, plain text, images.
Extracts content and answers questions about it using Claude Haiku.
"""
import re
from pathlib import Path

from core.agents.base_agent import BaseAgent

_SEARCH_DIRS = [
    Path("C:/Users/Mohab1/OneDrive/Desktop"),
    Path("C:/Users/Mohab1/OneDrive/Documents"),
    Path("C:/Users/Mohab1/Downloads"),
    Path("."),
]

_MAX_CONTENT_CHARS = 6000
_SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".doc", ".xlsx", ".txt", ".csv", ".md", ".png", ".jpg", ".jpeg"}


class FileAgent(BaseAgent):
    @property
    def name(self) -> str:
        return "file"

    @property
    def description(self) -> str:
        return "Document intelligence -- reads PDFs, Word docs, images and answers questions."

    def run(self, task: str) -> str:
        path = self._resolve_path(task)
        if path is None:
            return (
                "No file found. Mention the filename or path, e.g. "
                "'summarize thesis.pdf' or 'what does contract.docx say about payment terms?'"
            )

        content = self._extract_content(path)
        if not content:
            return (
                f"Could not read content from {path.name}. "
                "File may be empty, encrypted, or an unsupported format."
            )

        return self._answer(task, path, content)

    def _resolve_path(self, task: str) -> Path | None:
        # 1. Quoted path -- highest confidence
        quoted = re.search(
            r'["\']([^"\']+\.(?:pdf|docx|doc|xlsx|txt|csv|md|png|jpg|jpeg))["\']',
            task,
            re.IGNORECASE,
        )
        if quoted:
            p = Path(quoted.group(1))
            if p.exists():
                return p

        # 2. Unquoted filename with known extension
        ext_match = re.search(
            r'(\S+\.(?:pdf|docx|doc|xlsx|txt|csv|md|png|jpg|jpeg))',
            task,
            re.IGNORECASE,
        )
        if ext_match:
            candidate = ext_match.group(1)
            p = Path(candidate)
            if p.exists():
                return p
            # Search in common directories by filename only
            name = Path(candidate).name
            for d in _SEARCH_DIRS:
                found = d / name
                if found.exists():
                    return found

        return None

    def _extract_content(self, path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            return self._read_pdf(path)
        if suffix in {".docx", ".doc"}:
            return self._read_docx(path)
        if suffix in {".txt", ".csv", ".md"}:
            return self._read_text(path)
        if suffix in {".png", ".jpg", ".jpeg"}:
            return self._ocr_image(path)
        return ""

    def _read_pdf(self, path: Path) -> str:
        try:
            import pdfplumber
            texts = []
            with pdfplumber.open(path) as pdf:
                for page in pdf.pages[:10]:
                    t = page.extract_text()
                    if t:
                        texts.append(t)
            return "\n".join(texts)[:_MAX_CONTENT_CHARS]
        except Exception:
            return ""

    def _read_docx(self, path: Path) -> str:
        try:
            from docx import Document
            doc = Document(str(path))
            text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
            return text[:_MAX_CONTENT_CHARS]
        except Exception:
            return ""

    def _read_text(self, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8", errors="replace")[:_MAX_CONTENT_CHARS]
        except Exception:
            return ""

    def _ocr_image(self, path: Path) -> str:
        try:
            import pytesseract
            from PIL import Image
            img = Image.open(path)
            return pytesseract.image_to_string(img)[:_MAX_CONTENT_CHARS]
        except Exception:
            return ""

    def _answer(self, task: str, path: Path, content: str) -> str:
        prompt = (
            "You are El Fager's document assistant. Answer the user's question "
            "based strictly on the document content below. Be specific and concise. "
            "No emojis. Plain English only.\n\n"
            f"File: {path.name}\n\n"
            f"Content:\n{content}\n\n"
            f"Question: {task}"
        )
        try:
            import anthropic
            client = anthropic.Anthropic()
            resp = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=400,
                messages=[{"role": "user", "content": prompt}],
            )
            return resp.content[0].text.strip()
        except Exception:
            return f"{path.name}: {content[:500]}..."
```

- [ ] **Step 4: Run tests -- all 14 should pass**

```
python -m pytest tests/agents/test_file_agent.py -v
```
Expected: 14 passed

- [ ] **Step 5: Run full suite to confirm no regressions**

```
python -m pytest --tb=short -q
```
Expected: 148 + 14 = 162 passed

- [ ] **Step 6: Commit**

```
git add core/agents/file_agent.py tests/agents/test_file_agent.py
git commit -m "feat: add FileAgent for PDF/Word/text/image document intelligence"
```

---

### Task 3: Wire ResearchAgent + FileAgent into brain.py

**Files:**
- Modify: `core/brain.py` (targeted edit to `_try_agent_dispatch`, around line 5953)
- Modify: `tests/agents/test_router.py` (append new test class at bottom)

**Interfaces:**
- Consumes: `ResearchAgent` from Task 1, `FileAgent` from Task 2
- `classify_intent()` already returns `"research"` and `"file"` -- keywords are live in router.py

- [ ] **Step 1: Verify the router already classifies both intents**

Run this one-liner to confirm before touching brain.py:

```
python -c "from core.agents.router import classify_intent; print(classify_intent('research everything about NVDA')); print(classify_intent('summarize this pdf thesis.pdf')); print(classify_intent('what does this contract say?'))"
```

Expected output:
```
research
file
file
```

- [ ] **Step 2: Write router tests (append to existing file)**

Open `tests/agents/test_router.py` and append this class at the bottom (do NOT remove existing tests):

```python


class TestResearchAndFileRouting:
    def test_research_everything_about_routes_to_research(self):
        from core.agents.router import classify_intent
        assert classify_intent("research everything about NVDA earnings") == "research"

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
```

- [ ] **Step 3: Run router tests to confirm all 8 new tests pass**

```
python -m pytest tests/agents/test_router.py -v
```
Expected: all existing tests + 8 new = all pass (no brain.py change needed for router)

- [ ] **Step 4: Edit brain.py -- add research and file dispatch branches**

Find this exact block in `core/brain.py` (around line 5953):

```python
    def _try_agent_dispatch(self, task: str) -> str | None:
        """Route complex tasks to a specialist agent. Returns None for instant-lane tasks."""
        from core.agents.router import classify_intent
        intent = classify_intent(task)
        if intent == "screen":
            from core.agents.screen_agent import ScreenAgent
            return ScreenAgent().run(task)
        if intent == "browser":
            from core.agents.browser_agent import BrowserAgent
            return BrowserAgent().run(task)
        if intent == "stocks_agent":
            from core.agents.stocks_agent import StocksAgent
            return StocksAgent().run(task)
        return None  # research / file not yet implemented -- fall through
```

Replace with:

```python
    def _try_agent_dispatch(self, task: str) -> str | None:
        """Route complex tasks to a specialist agent. Returns None for instant-lane tasks."""
        from core.agents.router import classify_intent
        intent = classify_intent(task)
        if intent == "screen":
            from core.agents.screen_agent import ScreenAgent
            return ScreenAgent().run(task)
        if intent == "browser":
            from core.agents.browser_agent import BrowserAgent
            return BrowserAgent().run(task)
        if intent == "stocks_agent":
            from core.agents.stocks_agent import StocksAgent
            return StocksAgent().run(task)
        if intent == "research":
            from core.agents.research_agent import ResearchAgent
            return ResearchAgent().run(task)
        if intent == "file":
            from core.agents.file_agent import FileAgent
            return FileAgent().run(task)
        return None
```

- [ ] **Step 5: Run full suite -- all tests must pass**

```
python -m pytest --tb=short -q
```
Expected: 162 + 8 = 170 passed

- [ ] **Step 6: Commit**

```
git add core/brain.py tests/agents/test_router.py
git commit -m "feat: wire ResearchAgent and FileAgent into brain dispatch"
```
