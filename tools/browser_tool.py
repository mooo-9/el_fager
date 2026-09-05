"""
Browser automation for El Fager using Playwright.

Persistent browser context — session/cookies survive between calls so Mo
stays logged in within the same El Fager activation.

Thread safety: Playwright sync API requires all calls from the same OS thread.
El Fager creates a new QThread per activation, so we track the thread ID and
auto-reset the browser if the thread changes (session resets but no crash).

Opens visible (headless=False) by default so Mo can watch what's happening.
"""

import os
import threading

_lock = threading.Lock()
_playwright = None
_browser = None
_context = None
_page = None
_owner_thread: int = None  # OS thread ID that created the browser


def _reset_browser_state():
    """Teardown browser objects without raising (used when thread changes)."""
    global _playwright, _browser, _context, _page, _owner_thread
    for obj, method in [(_page, "close"), (_context, "close"), (_browser, "close")]:
        if obj is not None:
            try:
                getattr(obj, method)()
            except Exception:
                pass
    if _playwright is not None:
        try:
            _playwright.stop()
        except Exception:
            pass
    _playwright = _browser = _context = _page = _owner_thread = None


def _ensure_browser(headless: bool = False):
    """Initialize browser if not already open. Auto-resets if thread changed."""
    global _playwright, _browser, _context, _page, _owner_thread
    current_thread = threading.current_thread().ident

    # If browser exists but was created in a different thread, reset it
    if _page is not None and _owner_thread != current_thread:
        _reset_browser_state()

    if _page is None:
        from playwright.sync_api import sync_playwright
        _playwright = sync_playwright().start()
        _browser = _playwright.chromium.launch(headless=headless)
        _context = _browser.new_context()
        _page = _context.new_page()
        _owner_thread = current_thread


def browser_is_open() -> str:
    """Check whether the browser is currently open."""
    with _lock:
        if _page is not None and _owner_thread == threading.current_thread().ident:
            try:
                url = _page.url
                return f"Browser is open. Current URL: {url}"
            except Exception:
                pass
        return "Browser is not open. Call browser_open first."


def browser_open(url: str = "", headless: bool = False) -> str:
    """Launch the browser (visible by default). Navigate to url if provided."""
    with _lock:
        try:
            _ensure_browser(headless=headless)
            if url:
                _page.goto(url, timeout=30000)
                return f"Browser opened at: {url}"
            return "Browser opened."
        except Exception as e:
            return f"[browser_open failed: {e}]"


def browser_navigate(url: str) -> str:
    """Navigate to a URL in the current browser page."""
    with _lock:
        try:
            _ensure_browser()
            _page.goto(url, timeout=30000)
            return f"Navigated to: {url} — Title: {_page.title()}"
        except Exception as e:
            return f"[browser_navigate failed: {e}]"


def browser_click(selector_or_text: str) -> str:
    """Click an element — tries CSS selector, then visible text match."""
    with _lock:
        try:
            _ensure_browser()
            # Try CSS/XPath selector first
            try:
                _page.click(selector_or_text, timeout=5000)
                return f"Clicked: {selector_or_text}"
            except Exception:
                pass
            # Fall back to visible text match
            try:
                _page.get_by_text(selector_or_text, exact=False).first.click(timeout=5000)
                return f"Clicked element with text: '{selector_or_text}'"
            except Exception:
                pass
            return f"[Element not found: '{selector_or_text}']"
        except Exception as e:
            return f"[browser_click failed: {e}]"


def browser_type(selector: str, text: str, clear: bool = True) -> str:
    """Type text into an input field. Clears the field first if clear=True."""
    with _lock:
        try:
            _ensure_browser()
            if clear:
                _page.fill(selector, text, timeout=5000)
            else:
                _page.type(selector, text, timeout=5000)
            preview = text[:30] + "..." if len(text) > 30 else text
            return f"Typed '{preview}' into {selector}."
        except Exception as e:
            return f"[browser_type failed: {e}]"


def browser_get_text(selector: str = "body") -> str:
    """Get visible text content of an element (default: full page body)."""
    with _lock:
        try:
            _ensure_browser()
            text = _page.locator(selector).inner_text(timeout=5000)
            if len(text) > 3000:
                text = text[:3000] + "\n...[truncated]"
            return text or "[Element is empty]"
        except Exception as e:
            return f"[browser_get_text failed: {e}]"


def browser_get_title() -> str:
    """Return the current page title and URL."""
    with _lock:
        try:
            _ensure_browser()
            return f"Title: {_page.title()} | URL: {_page.url}"
        except Exception as e:
            return f"[browser_get_title failed: {e}]"


def browser_screenshot(path: str = None) -> str:
    """Take a screenshot of the current browser page."""
    with _lock:
        try:
            _ensure_browser()
            from datetime import datetime
            os.makedirs("data/browser_screenshots", exist_ok=True)
            if not path:
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                path = f"data/browser_screenshots/browser_{ts}.png"
            _page.screenshot(path=path, full_page=False)
            return f"Browser screenshot saved: {path}"
        except Exception as e:
            return f"[browser_screenshot failed: {e}]"


def browser_fill_form(fields: dict) -> str:
    """Fill multiple form fields at once. fields = {CSS_selector: value}."""
    with _lock:
        try:
            _ensure_browser()
            results = []
            for selector, value in fields.items():
                try:
                    _page.fill(selector, str(value), timeout=5000)
                    results.append(f"  {selector}: filled")
                except Exception as ex:
                    results.append(f"  {selector}: FAILED ({ex})")
            return "Form filled:\n" + "\n".join(results)
        except Exception as e:
            return f"[browser_fill_form failed: {e}]"


def browser_submit(selector: str) -> str:
    """Click a submit button or element to submit a form."""
    with _lock:
        try:
            _ensure_browser()
            _page.click(selector, timeout=5000)
            _page.wait_for_load_state("networkidle", timeout=10000)
            return f"Submitted via: {selector} — Now at: {_page.url}"
        except Exception as e:
            return f"[browser_submit failed: {e}]"


def browser_wait(seconds: float = 2) -> str:
    """Wait for a given number of seconds (for page load or animations)."""
    with _lock:
        try:
            _ensure_browser()
            _page.wait_for_timeout(int(seconds * 1000))
            return f"Waited {seconds}s."
        except Exception as e:
            return f"[browser_wait failed: {e}]"


def browser_scroll(direction: str = "down", amount: int = 3) -> str:
    """Scroll the browser page. direction: down, up, top, bottom."""
    with _lock:
        try:
            _ensure_browser()
            direction = direction.lower()
            if direction == "top":
                _page.evaluate("window.scrollTo(0, 0)")
                return "Scrolled to top."
            elif direction == "bottom":
                _page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                return "Scrolled to bottom."
            elif direction == "up":
                _page.evaluate(f"window.scrollBy(0, -{amount * 300})")
                return f"Scrolled up {amount} steps."
            else:
                _page.evaluate(f"window.scrollBy(0, {amount * 300})")
                return f"Scrolled down {amount} steps."
        except Exception as e:
            return f"[browser_scroll failed: {e}]"


def browser_close() -> str:
    """Close the browser and clean up all resources."""
    with _lock:
        try:
            _reset_browser_state()
            return "Browser closed."
        except Exception as e:
            _reset_browser_state()
            return f"Browser closed (with warning: {e})."


def browser_back() -> str:
    """Navigate back to the previous page."""
    with _lock:
        try:
            _ensure_browser()
            _page.go_back(timeout=10000)
            return f"Went back. Now at: {_page.url}"
        except Exception as e:
            return f"[browser_back failed: {e}]"


def browser_get_links(filter: str = "") -> str:
    """Get all links on the current page, optionally filtered by keyword."""
    with _lock:
        try:
            _ensure_browser()
            links = _page.evaluate("""
                () => Array.from(document.querySelectorAll('a[href]'))
                    .map(a => ({ text: a.innerText.trim(), href: a.href }))
                    .filter(l => l.text || l.href)
            """)
            if filter:
                f = filter.lower()
                links = [l for l in links if f in l["text"].lower() or f in l["href"].lower()]
            if not links:
                return "No links found." if not filter else f"No links matching '{filter}'."
            lines = [f"  {l['text'] or '(no text)'} -> {l['href']}" for l in links[:30]]
            result = "\n".join(lines)
            if len(links) > 30:
                result += f"\n  ... and {len(links) - 30} more"
            return result
        except Exception as e:
            return f"[browser_get_links failed: {e}]"


def browser_select(selector: str, value: str) -> str:
    """Select an option from a <select> dropdown by value or visible text."""
    with _lock:
        try:
            _ensure_browser()
            try:
                _page.select_option(selector, value=value, timeout=5000)
            except Exception:
                _page.select_option(selector, label=value, timeout=5000)
            return f"Selected '{value}' in {selector}."
        except Exception as e:
            return f"[browser_select failed: {e}]"
