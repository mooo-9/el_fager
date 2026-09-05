"""
Comet — the browser El Fager opens things in.

Comet is Perplexity's Chromium-based browser. Everything that shows Mo a page
goes through open_url() so there is one place that decides which browser wins.

Default install (per-user):
    %LOCALAPPDATA%\\Perplexity\\Comet\\Application\\Comet.exe
Enterprise/machine-wide installs land under Program Files. Set COMET_PATH in
.env to point somewhere else.

If Comet isn't installed, open_url() falls back to the system default browser
and says so rather than failing silently.

Automation that needs Mo logged in (browser_tool, browser_agent) attaches to his
*running* Comet over the DevTools protocol, so it drives his real profile, his
real cookies and his real sessions. That is why open_url() starts Comet with a
debugging port. research_agent deliberately stays on Playwright's bundled
Chromium: it reads public pages headlessly in bulk, needs no login, and pointing
it at Comet would spray tabs across Mo's browser.

Set COMET_REMOTE_DEBUG=0 to turn the debugging port off; automation then falls
back to a fresh throwaway profile — working, but logged out. The port listens on
127.0.0.1 only, and while it is open any program running as Mo can drive his
logged-in browser.
"""

import os
import subprocess
import time
import webbrowser
from pathlib import Path

_EXE = "Comet.exe"
_APP_SUBPATH = Path("Perplexity") / "Comet" / "Application" / _EXE

# DevTools endpoint used to attach to Mo's running Comet.
_DEBUG_PORT = os.getenv("COMET_DEBUG_PORT", "9222").strip() or "9222"
_CDP_URL = f"http://127.0.0.1:{_DEBUG_PORT}"
_REMOTE_DEBUG = os.getenv("COMET_REMOTE_DEBUG", "1").strip().lower() not in ("0", "false", "no")

# Resolved once — the install location doesn't move mid-session.
_cached_path: "str | None" = None
_resolved = False


def _candidates() -> "list[Path]":
    paths = []
    override = os.getenv("COMET_PATH", "").strip().strip('"')
    if override:
        paths.append(Path(override))
    for env_var in ("LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432"):
        root = os.environ.get(env_var)
        if root:
            paths.append(Path(root) / _APP_SUBPATH)
    return paths


def _from_registry() -> "str | None":
    """Chromium browsers register themselves under App Paths."""
    try:
        import winreg
    except ImportError:
        return None
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            key = winreg.OpenKey(
                hive,
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\Comet.exe",
            )
            value, _ = winreg.QueryValueEx(key, "")
            winreg.CloseKey(key)
            if value and os.path.exists(value):
                return value
        except OSError:
            continue
    return None


def comet_path() -> "str | None":
    """Absolute path to Comet.exe, or None when it isn't installed."""
    global _cached_path, _resolved
    if _resolved:
        return _cached_path

    found = None
    for path in _candidates():
        if path.exists():
            found = str(path)
            break
    if found is None:
        found = _from_registry()

    _cached_path = found
    _resolved = True
    if found is None:
        print("[El Fager] Comet not found — falling back to the default browser. "
              "Set COMET_PATH in .env if it's installed somewhere unusual.")
    return found


def reset_cache() -> None:
    """Forget the resolved path (used by tests, and after installing Comet)."""
    global _cached_path, _resolved
    _cached_path = None
    _resolved = False


def is_available() -> bool:
    return comet_path() is not None


def _launch_args(exe: str, url: str = "") -> "list[str]":
    args = [exe]
    if _REMOTE_DEBUG:
        # Makes this instance attachable, so automation gets Mo's session.
        # Ignored when Comet is already running: Chromium hands the URL to the
        # existing process, which keeps whatever flags it started with.
        args.append(f"--remote-debugging-port={_DEBUG_PORT}")
    if url:
        args.append(url)
    return args


def open_url(url: str = "") -> bool:
    """Open url in Comet — or just the browser when url is empty. Returns True
    if Comet handled it, False if this fell back to the default browser."""
    exe = comet_path()
    if exe:
        try:
            subprocess.Popen(_launch_args(exe, url))
            return True
        except Exception as e:
            print(f"[El Fager] Comet launch failed ({e}) — using default browser.")
    try:
        webbrowser.open(url or "about:blank")
    except Exception as e:
        print(f"[El Fager] Could not open a browser: {e}")
    return False


def open_comet(url: str = "") -> str:
    """Tool entry point: open Comet, optionally at a URL."""
    target = url.strip()
    used_comet = open_url(target)
    where = "Comet" if used_comet else "your default browser (Comet not found)"
    return f"Opened {target or 'the browser'} in {where}."


# ── Automation against Mo's real profile ──────────────────────────────────────

def cdp_alive(timeout: float = 0.4) -> bool:
    """True when a debuggable Comet is listening."""
    try:
        import httpx
        return httpx.get(f"{_CDP_URL}/json/version", timeout=timeout).status_code == 200
    except Exception:
        return False


def _start_debuggable_comet(wait_seconds: float = 8.0) -> bool:
    """Start Comet with its debugging port and wait for it to answer.

    A Comet already running without the port can't be upgraded — Chromium hands
    off to the existing process — so this returns False and the caller falls
    back to a throwaway profile.
    """
    exe = comet_path()
    if not exe or not _REMOTE_DEBUG:
        return False
    try:
        subprocess.Popen(_launch_args(exe))
    except Exception as e:
        print(f"[El Fager] Couldn't start Comet for automation: {e}")
        return False

    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if cdp_alive():
            return True
        time.sleep(0.25)
    return False


def automation_context(playwright, headless: bool = False):
    """Return (browser, context, owned) for automation.

    Attaches to Mo's running Comet when it can, so his profile and logins carry.
    `owned` is False then, and the caller must close only the pages it opened —
    closing the browser or context would take his session down with it.
    Otherwise this launches Playwright's bundled Chromium on a fresh profile and
    `owned` is True.
    """
    if not headless and _REMOTE_DEBUG and comet_path():
        if cdp_alive() or _start_debuggable_comet():
            try:
                browser = playwright.chromium.connect_over_cdp(_CDP_URL)
                context = browser.contexts[0] if browser.contexts else browser.new_context()
                return browser, context, False
            except Exception as e:
                print(f"[El Fager] Couldn't attach to Comet ({e}) — "
                      "using a fresh browser profile.")
        else:
            print("[El Fager] Comet isn't attachable (already running without a "
                  "debugging port?) — using a fresh, logged-out profile.")

    browser = playwright.chromium.launch(headless=headless)
    return browser, browser.new_context(), True
