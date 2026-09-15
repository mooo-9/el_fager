"""
News & RSS feed reader — Phase 6B.

Uses feedparser to pull headlines from public RSS feeds.
No API key required. BeautifulSoup used for article text extraction.
"""

import re
import time

FEEDS: dict[str, str] = {
    "world":    "http://feeds.bbci.co.uk/news/world/rss.xml",
    "tech":     "https://techcrunch.com/feed/",
    "science":  "https://feeds.feedburner.com/sciencedailyheadlines",
    "egypt":    "https://english.ahram.org.eg/rss.aspx",
    "business": "http://feeds.bbci.co.uk/news/business/rss.xml",
    "sports":   "http://feeds.bbci.co.uk/sport/rss.xml",
}

_SOURCE_NAMES = {
    "world":    "BBC World",
    "tech":     "TechCrunch",
    "science":  "Science Daily",
    "egypt":    "Al-Ahram English",
    "business": "BBC Business",
    "sports":   "BBC Sport",
}

# Cache of articles from the last get_news / search_news call.
# Allows "read article 1" to work without passing a URL.
_article_cache: list[dict] = []


# ── Helpers ───────────────────────────────────────────────────────────────────

def _time_ago(entry) -> str:
    try:
        published = entry.get("published_parsed")
        if not published:
            return ""
        diff = int(time.time() - time.mktime(published))
        if diff < 3600:
            return f"{diff // 60}m ago"
        if diff < 86400:
            return f"{diff // 3600}h ago"
        return f"{diff // 86400}d ago"
    except Exception:
        return ""


def _summary_sentence(entry) -> str:
    summary = entry.get("summary", "")
    if not summary:
        return ""
    clean = re.sub(r"<[^>]+>", "", summary).strip()
    if len(clean) > 120:
        clean = clean[:117] + "..."
    return clean


def _entry_url(entry) -> str:
    return entry.get("link") or entry.get("id") or ""


# ── Public functions ──────────────────────────────────────────────────────────

def get_news(category: str = "world", n: int = 5) -> str:
    """
    Fetch top headlines for a category.
    category — world | tech | science | egypt | business | sports
    n        — number of headlines (default 5)
    Articles are cached by index so Mo can say 'read article 1'.
    """
    try:
        import feedparser
    except ImportError:
        return "[feedparser not installed — run: pip install feedparser]"

    cat = category.lower().strip()
    url = FEEDS.get(cat)
    if url is None:
        cats = ", ".join(FEEDS.keys())
        return f"Unknown category '{category}'. Available: {cats}"

    source = _SOURCE_NAMES.get(cat, cat)
    try:
        feed    = feedparser.parse(url)
        entries = feed.get("entries", [])
        if not entries:
            return f"No articles found from {source} (feed may be temporarily unavailable)."

        _article_cache.clear()
        lines = [f"Top {min(n, len(entries))} headlines from {source}:\n"]
        for i, entry in enumerate(entries[:n], 1):
            title   = entry.get("title", "(no title)").strip()
            ago     = _time_ago(entry)
            summary = _summary_sentence(entry)
            art_url = _entry_url(entry)

            _article_cache.append({"title": title, "url": art_url, "source": source})

            line = f"{i}. {title}"
            if ago:
                line += f" [{ago}]"
            lines.append(line)
            if summary:
                lines.append(f"   {summary}")

        return "\n".join(lines)
    except Exception as e:
        return f"[News error ({source}): {e}]"


def get_all_headlines(n: int = 2) -> str:
    """
    Fetch N headlines from every category — good for a morning briefing.
    n — headlines per category (default 2)
    """
    try:
        import feedparser
    except ImportError:
        return "[feedparser not installed — run: pip install feedparser]"

    sections = []
    for cat, url in FEEDS.items():
        source = _SOURCE_NAMES.get(cat, cat)
        try:
            feed    = feedparser.parse(url)
            entries = feed.get("entries", [])[:n]
            if not entries:
                continue
            items = []
            for entry in entries:
                title = entry.get("title", "").strip()
                ago   = _time_ago(entry)
                items.append(f"  • {title}" + (f" [{ago}]" if ago else ""))
            sections.append(f"[{source}]\n" + "\n".join(items))
        except Exception:
            continue

    if not sections:
        return "No headlines available right now — check your internet connection."
    return "Headlines:\n\n" + "\n\n".join(sections)


def search_news(query: str, n: int = 8) -> str:
    """
    Search across all news feeds for articles matching a keyword or phrase.
    Results are cached so Mo can say 'read article 1'.
    """
    try:
        import feedparser
    except ImportError:
        return "[feedparser not installed — run: pip install feedparser]"

    query_lower = query.lower().strip()
    # Word-boundary pattern so "AI" doesn't match inside "fragile", "rain", etc.
    pattern = re.compile(r"\b" + re.escape(query_lower) + r"\b", re.IGNORECASE)
    matches: list[dict] = []

    for cat, url in FEEDS.items():
        source = _SOURCE_NAMES.get(cat, cat)
        try:
            feed = feedparser.parse(url)
            for entry in feed.get("entries", []):
                title   = entry.get("title", "")
                summary = re.sub(r"<[^>]+>", "", entry.get("summary", ""))
                if pattern.search(title) or pattern.search(summary):
                    matches.append({
                        "title":   title.strip(),
                        "url":     _entry_url(entry),
                        "source":  source,
                        "ago":     _time_ago(entry),
                        "summary": summary.strip()[:100],
                    })
        except Exception:
            continue

    if not matches:
        return f"No news found about '{query}'."

    matches = matches[:n]
    _article_cache.clear()
    _article_cache.extend(matches)

    lines = [f"News about '{query}':\n"]
    for i, m in enumerate(matches, 1):
        ago_str = f" [{m['ago']}]" if m["ago"] else ""
        lines.append(f"{i}. {m['title']}{ago_str} — {m['source']}")
        if m["summary"]:
            lines.append(f"   {m['summary'][:100]}...")

    return "\n".join(lines)


def read_news_article(index_or_url: str) -> str:
    """
    Fetch and return clean text from a news article.
    Pass an index (1, 2, 3...) from the last get_news/search_news call, or a full URL.
    The brain model should summarise the returned text for Mo.
    """
    url = ""
    idx_str = str(index_or_url).strip()
    if idx_str.isdigit():
        idx = int(idx_str) - 1
        if 0 <= idx < len(_article_cache):
            url = _article_cache[idx].get("url", "")
            if not url:
                return f"No URL stored for article {idx_str}."
        else:
            count = len(_article_cache)
            if count == 0:
                return "No articles cached — say 'get news' or 'search news for [topic]' first."
            return f"Index {idx_str} out of range — last fetch had {count} article(s)."
    else:
        url = idx_str

    if not url.startswith("http"):
        return f"Invalid URL: {url}"

    try:
        import httpx
        from bs4 import BeautifulSoup

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }
        resp = httpx.get(url, headers=headers, timeout=15, follow_redirects=True)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        # Remove clutter
        for tag in soup(["script", "style", "nav", "header", "footer",
                         "aside", "noscript", "iframe", "form", "button", "figure"]):
            tag.decompose()

        # Try common article content selectors in priority order
        content = (
            soup.find("article") or
            soup.find(attrs={"role": "main"}) or
            soup.find("main") or
            soup.find(class_=re.compile(
                r"article.?(body|content|text)|story.?body|post.?content|entry.?content",
                re.I,
            )) or
            soup.find("body") or
            soup
        )

        raw = content.get_text(separator="\n", strip=True)

        # Keep only lines with enough content
        lines = [l.strip() for l in raw.splitlines() if len(l.strip()) > 35]
        text  = "\n".join(lines[:60])  # cap at ~60 paragraphs

        if not text.strip():
            return "[Article appears empty or is behind a paywall.]"

        return f"Article from {url}:\n\n{text}"

    except Exception as e:
        err = str(e)
        if "403" in err or "401" in err:
            return "[Article is behind a paywall or access is restricted.]"
        return f"[Article fetch error: {e}]"
