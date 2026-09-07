"""
El Fager self-check — run this to see what is actually working.

    python scripts/selfcheck.py            # check everything, touch nothing
    python scripts/selfcheck.py --live     # also open a browser tab / play a song

Without --live nothing is launched: this reports on configuration, wiring and
reachability only. With --live it exercises the real paths end to end, so a
browser tab opens and Spotify starts playing.

Exit code is 0 when nothing is broken, 1 when something is.
"""

import argparse
import os
import sys
from pathlib import Path

# Everything is resolved against the project, not the shell's working
# directory, so this reports the same thing wherever it is run from.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

OK, WARN, FAIL = "OK  ", "WARN", "FAIL"
_results: list[tuple[str, str, str]] = []


def record(status: str, name: str, detail: str = "") -> None:
    _results.append((status, name, detail))
    line = f"  [{status}] {name}"
    if detail:
        line += f" — {detail}"
    print(line, flush=True)


def section(title: str) -> None:
    print(f"\n{title}", flush=True)


def check(name: str, fn, warn_only: bool = False):
    """Run fn(); it returns (ok, detail) or raises."""
    try:
        ok, detail = fn()
    except Exception as e:
        record(WARN if warn_only else FAIL, name, f"{type(e).__name__}: {e}")
        return False
    record(OK if ok else (WARN if warn_only else FAIL), name, detail)
    return ok


# ── Process ───────────────────────────────────────────────────────────────────

def el_fager_running() -> "bool | None":
    """Is El Fager up? Read through the single-instance mutex main.py creates,
    so this agrees with what main.py itself sees. None off Windows.

    Name must match _acquire_instance_lock() in main.py.
    """
    if os.name != "nt":
        return None
    import ctypes
    SYNCHRONIZE = 0x00100000
    handle = ctypes.windll.kernel32.OpenMutexW(
        SYNCHRONIZE, False, "ElFagerSingleInstance")
    if handle:
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    return False


def check_process():
    section("Process")

    def running():
        state = el_fager_running()
        if state is None:
            return True, "not detectable on this platform"
        if state:
            return True, "El Fager is running"
        return False, ("El Fager is NOT running — start it with: python main.py "
                       "(nothing below reflects a live assistant)")

    check("El Fager running", running, warn_only=True)


# ── Configuration ─────────────────────────────────────────────────────────────

def check_config():
    section("Configuration")

    def anthropic_key():
        key = os.getenv("ANTHROPIC_API_KEY", "")
        if not key or key.startswith("sk-ant-your"):
            return False, "ANTHROPIC_API_KEY missing — El Fager cannot think"
        return True, f"ANTHROPIC_API_KEY set ({key[:11]}…)"

    def spotify_creds():
        from tools.spotify_tool import SPOTIFY_AVAILABLE
        if not SPOTIFY_AVAILABLE:
            return False, "SPOTIFY_CLIENT_ID/SECRET missing from .env"
        return True, "client credentials present"

    def spotify_token():
        if Path("data/.spotify_cache").exists():
            return True, "authorised (data/.spotify_cache present)"
        return False, "not authorised yet — first 'play X' opens a browser consent page"

    check("Anthropic API key", anthropic_key)
    check("Spotify credentials", spotify_creds, warn_only=True)
    check("Spotify authorisation", spotify_token, warn_only=True)


# ── Browser ───────────────────────────────────────────────────────────────────

def check_browser():
    section("Browser (Comet)")
    from tools import comet_tool

    def installed():
        path = comet_tool.comet_path()
        if path:
            return True, path
        return False, "not found — pages will open in your default browser. Set COMET_PATH in .env"

    def debugging():
        if not comet_tool._REMOTE_DEBUG:
            return False, "COMET_REMOTE_DEBUG=0 — automation will run logged out"
        return True, f"port {comet_tool._DEBUG_PORT} requested at launch"

    def autostart():
        if not comet_tool._AUTOSTART:
            return False, "COMET_AUTOSTART=0 — automation only gets your logins if El Fager opens Comet before you do"
        return True, "El Fager starts Comet minimised at launch, so it stays attachable"

    def attachable():
        if comet_tool.cdp_alive():
            return True, "a debuggable Comet is running — automation gets your logins"
        if el_fager_running() is False:
            return False, "start El Fager — it opens an attachable Comet at launch"
        return False, ("Comet is open without a debugging port, so automation would run "
                       "logged out. Windows can't add the port to a live browser: quit "
                       "Comet AND El Fager, then start El Fager first")

    check("Comet installed", installed, warn_only=True)
    check("Remote debugging enabled", debugging, warn_only=True)
    check("Comet autostart", autostart, warn_only=True)
    check("Comet attachable now", attachable, warn_only=True)


# ── Wiring ────────────────────────────────────────────────────────────────────

def check_wiring():
    section("Wiring")

    def tools_registered():
        from core.brain import TOOLS
        names = {t["name"] for t in TOOLS}
        expected = {"youtube_search", "youtube_latest", "open_web_search",
                    "open_comet", "play_music", "web_search"}
        missing = expected - names
        if missing:
            return False, f"missing from TOOLS: {sorted(missing)}"
        return True, f"{len(TOOLS)} tools registered"

    def dispatch_reachable():
        """Every tool Claude can call must have a dispatch branch."""
        import re
        from core.brain import TOOLS
        source = Path("core/brain.py").read_text(encoding="utf-8")
        dispatched = set(re.findall(r'name == "([A-Za-z_0-9]+)"', source))
        undispatched = sorted({t["name"] for t in TOOLS} - dispatched)
        if undispatched:
            return False, f"{len(undispatched)} tools have no dispatch: {undispatched[:5]}"
        return True, "every registered tool has a dispatch branch"

    def prompt_caching():
        from core.brain import _build_system
        blocks = _build_system("")
        if not isinstance(blocks, list) or "cache_control" not in blocks[0]:
            return False, "system prompt is not cacheable — responses will be slower"
        return True, "system prompt carries a cache breakpoint"

    def play_fast_path():
        from tools.spotify_tool import match_play_command
        if match_play_command("play blinding lights") is None:
            return False, "'play X' is not being recognised"
        if match_play_command("what's playing") is not None:
            return False, "'what's playing' is wrongly matching the fast path"
        return True, "'play X' answers without an API round trip"

    def automation_uses_profile():
        source = Path("tools/browser_tool.py").read_text(encoding="utf-8")
        if "automation_context" not in source:
            return False, "browser automation is not routed through Comet"
        return True, "browser automation attaches to your Comet profile"

    check("Tools registered", tools_registered)
    check("Tool dispatch complete", dispatch_reachable)
    check("Prompt caching active", prompt_caching)
    check("'play X' fast path", play_fast_path)
    check("Automation uses your profile", automation_uses_profile)


# ── Reachability ──────────────────────────────────────────────────────────────

def check_reachability():
    section("Reachability")
    import httpx

    def reach(url: str):
        def _fn():
            # Any HTTP answer means the host is reachable — an API root
            # replying 404 is still a working network path.
            r = httpx.get(url, timeout=8, follow_redirects=True)
            return True, f"reachable (HTTP {r.status_code})"
        return _fn

    check("YouTube", reach("https://www.youtube.com/"), warn_only=True)
    check("Spotify API", reach("https://api.spotify.com/"), warn_only=True)
    check("Anthropic API", reach("https://api.anthropic.com/"), warn_only=True)


# ── Live ──────────────────────────────────────────────────────────────────────

def check_live():
    section("Live (these actually do something)")

    def open_page():
        from tools.comet_tool import open_comet
        return True, open_comet("https://www.youtube.com")

    def youtube():
        from tools.youtube_tool import youtube_search
        result = youtube_search("linkin park numb", open_it=False)
        return not result.startswith("["), result

    def latest():
        from tools.youtube_tool import youtube_latest
        result = youtube_latest("@LinkinPark", open_it=False)
        return not result.startswith("["), result

    def play():
        from tools.spotify_tool import play_music
        result = play_music("blinding lights")
        return not result.startswith("["), result

    check("Open a page in Comet", open_page, warn_only=True)
    check("YouTube search resolves a video", youtube, warn_only=True)
    check("YouTube latest-from-channel", latest, warn_only=True)
    check("Spotify plays a song", play, warn_only=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check that El Fager is working.")
    parser.add_argument("--live", action="store_true",
                        help="also open a browser tab and start playing music")
    args = parser.parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        print("python-dotenv not installed — reading the ambient environment only")

    print("El Fager self-check")
    check_process()
    check_config()
    check_browser()
    check_wiring()
    check_reachability()
    if args.live:
        check_live()
    else:
        print("\n(skipping live checks — pass --live to open a tab and play a song)")

    fails = [r for r in _results if r[0] == FAIL]
    warns = [r for r in _results if r[0] == WARN]
    print(f"\n{len(_results) - len(fails) - len(warns)} ok, {len(warns)} warnings, "
          f"{len(fails)} failures")
    for _, name, detail in fails:
        print(f"  BROKEN: {name} — {detail}")
    for _, name, detail in warns:
        print(f"  CHECK:  {name} — {detail}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
