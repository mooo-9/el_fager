"""
Wikipedia quick lookup — Phase 6D.
Uses the MediaWiki action API (more reliable than the REST summary endpoint).
Auto-selects Arabic or English Wikipedia based on the query language.
"""

import re
import httpx

_AR_RE = re.compile(r"[؀-ۿ]")


def _is_arabic_query(text: str) -> bool:
    return len(_AR_RE.findall(text)) > len(text) * 0.2


def _mediawiki_extract(query: str, lang: str) -> str | None:
    """Fetch a plain-text intro extract via the MediaWiki action API."""
    try:
        resp = httpx.get(
            f"https://{lang}.wikipedia.org/w/api.php",
            params={
                "action":      "query",
                "titles":      query,
                "prop":        "extracts",
                "exintro":     True,
                "explaintext": True,
                "redirects":   True,
                "format":      "json",
            },
            timeout=8,
            headers={"User-Agent": "ElFager/1.0 (mohabmohamed154@gmail.com)"},
            follow_redirects=True,
        )
        data = resp.json()
        pages = data.get("query", {}).get("pages", {})
        for pid, page in pages.items():
            if pid == "-1":
                return None
            extract = page.get("extract", "").strip()
            title   = page.get("title", query)
            if extract:
                return title, extract
    except Exception:
        pass
    return None


def _search_title(query: str, lang: str) -> str | None:
    """Use opensearch to find the best matching Wikipedia title."""
    try:
        resp = httpx.get(
            f"https://{lang}.wikipedia.org/w/api.php",
            params={
                "action": "opensearch",
                "search": query,
                "limit":  1,
                "format": "json",
            },
            timeout=8,
            headers={"User-Agent": "ElFager/1.0 (mohabmohamed154@gmail.com)"},
        )
        data = resp.json()
        results = data[1] if len(data) > 1 else []
        return results[0] if results else None
    except Exception:
        return None


def wikipedia_lookup(query: str, language: str = "auto") -> str:
    """
    Return a concise Wikipedia summary for a topic.
    query    — person, place, or concept to look up
    language — 'auto' (default), 'en', or 'ar'
    """
    if language == "auto":
        lang = "ar" if _is_arabic_query(query) else "en"
    else:
        lang = language.lower()[:2]

    # Try direct title first
    result = _mediawiki_extract(query, lang)

    # If not found, search for the best title then try again
    if result is None:
        best_title = _search_title(query, lang)
        if best_title:
            result = _mediawiki_extract(best_title, lang)

    # Arabic fallback → English
    if result is None and lang == "ar":
        result = _mediawiki_extract(query, "en")
        if result is None:
            best_title = _search_title(query, "en")
            if best_title:
                result = _mediawiki_extract(best_title, "en")

    if result is None:
        return f"No Wikipedia article found for '{query}'."

    title, extract = result

    # Cap at ~600 chars for spoken output
    if len(extract) > 600:
        extract = extract[:597] + "..."

    url = f"https://{lang}.wikipedia.org/wiki/{title.replace(' ', '_')}"
    return f"Wikipedia — {title}:\n{extract}\n\n{url}"
