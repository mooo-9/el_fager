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

This covers pages Mo looks at. Playwright automation (browser_tool,
browser_agent, research_agent) deliberately keeps Playwright's own bundled
Chromium: Playwright pins its browser build, and its launch() opens a throwaway
profile anyway — so driving Comet would carry the version-mismatch risk and the
weight of an agentic browser without giving Mo his logged-in session.
"""

import os
import subprocess
import webbrowser
from pathlib import Path

_EXE = "Comet.exe"
_APP_SUBPATH = Path("Perplexity") / "Comet" / "Application" / _EXE

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


def open_url(url: str = "") -> bool:
    """Open url in Comet — or just the browser when url is empty. Returns True
    if Comet handled it, False if this fell back to the default browser."""
    exe = comet_path()
    if exe:
        try:
            subprocess.Popen([exe, url] if url else [exe])
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
