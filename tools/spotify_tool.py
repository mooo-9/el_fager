"""
Spotify tool — Phase 3D.

Requires SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET in .env.
Get credentials at developer.spotify.com/dashboard → Create App.
Set redirect URI to: http://127.0.0.1:8888/callback

Playback control requires Spotify Premium. what_playing() works on Free.
Token is cached to data/.spotify_cache — auto-refreshed on expiry.
"""

import logging
import os
import re
import subprocess
import threading
import time

from dotenv import load_dotenv
load_dotenv()

# Suppress spotipy's HTTP error logging — we handle errors ourselves
logging.getLogger("spotipy").setLevel(logging.CRITICAL)

_cid  = os.getenv("SPOTIFY_CLIENT_ID", "")
_csec = os.getenv("SPOTIFY_CLIENT_SECRET", "")
SPOTIFY_AVAILABLE = bool(
    _cid and _csec
    and not _cid.startswith("your_")
    and not _csec.startswith("your_")
)

SCOPE = (
    "user-read-playback-state "
    "user-modify-playback-state "
    "user-read-currently-playing "
    "user-read-private"
)

MOODS: dict = {
    "chill":   "chill vibes playlist",
    "relax":   "relaxing music playlist",
    "happy":   "happy feel good playlist",
    "sad":     "sad songs playlist",
    "focus":   "deep focus study music",
    "study":   "lofi study music playlist",
    "hype":    "hype energy playlist",
    "workout": "workout motivation gym playlist",
    "arabic":  "arabic music hits playlist",
    "sleep":   "sleep ambient music playlist",
}

_NOT_SET_UP = (
    "[Spotify not set up — add SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET "
    "to .env (get them from developer.spotify.com/dashboard)]"
)

# ── Cached client — created once, reused across calls ────────────────────────
_sp_client = None

# Last device that accepted playback. Saves a /me/player/devices round trip on
# every play; cleared and re-probed when the device turns out to be gone.
_device_id: str | None = None

def get_spotify():
    global _sp_client
    if _sp_client is not None:
        return _sp_client
    if not SPOTIFY_AVAILABLE:
        return None
    try:
        import spotipy
        from spotipy.oauth2 import SpotifyOAuth
        _sp_client = spotipy.Spotify(auth_manager=SpotifyOAuth(
            client_id=os.getenv("SPOTIFY_CLIENT_ID"),
            client_secret=os.getenv("SPOTIFY_CLIENT_SECRET"),
            redirect_uri=os.getenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback"),
            scope=SCOPE,
            cache_path="data/.spotify_cache",
            open_browser=True,
        ))
        return _sp_client
    except Exception as e:
        print(f"[El Fager] Spotify auth failed: {e}")
        return None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt_track(t: dict) -> str:
    artists = ", ".join(a["name"] for a in t.get("artists", []))
    return f"{t['name']} by {artists}"

def _ms_to_mss(ms: int) -> str:
    s = ms // 1000
    return f"{s // 60}:{s % 60:02d}"

def _spotify_error(e) -> str:
    try:
        from spotipy.exceptions import SpotifyException
        if isinstance(e, SpotifyException):
            if e.http_status == 403:
                return "[Spotify Premium required for playback control]" if "premium" in str(e).lower() else f"[Spotify access denied: {e.reason}]"
            if e.http_status == 404:
                return "[No active Spotify device — open Spotify on your PC first]"
    except Exception:
        pass
    return f"[Spotify error: {e}]"

def _detect_mood(query: str) -> tuple[str, str] | tuple[None, None]:
    q = query.lower()
    for keyword, search_q in MOODS.items():
        if keyword in q:
            return keyword, search_q
    return None, None

def _best_device_id(devices: list) -> str | None:
    """Pick desktop app over Web Player; prefer active over inactive."""
    if not devices:
        return None
    non_web = [d for d in devices if "web player" not in d["name"].lower()]
    pool = non_web if non_web else devices
    active = [d for d in pool if d["is_active"]]
    return (active or pool)[0]["id"]

def _launch_spotify_app() -> bool:
    """Open the Spotify desktop app via Windows shell protocol."""
    try:
        os.startfile("spotify:")
        return True
    except Exception:
        pass
    for exe in [
        os.path.join(os.environ.get("APPDATA", ""), "Spotify", "Spotify.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WindowsApps", "Spotify.exe"),
    ]:
        if os.path.exists(exe):
            subprocess.Popen([exe])
            return True
    return False

def _get_device(sp, use_cache: bool = True) -> str | None:
    """
    Return best available device_id.
    Prefers desktop app over Web Player.
    If no devices found, launches the app and polls for up to 5s.
    Passing device_id to start_playback activates the device in one shot —
    no separate transfer_playback call needed.
    """
    global _device_id
    if use_cache and _device_id:
        return _device_id

    try:
        devices = sp.devices().get("devices", [])
    except Exception:
        return None

    dev = _best_device_id(devices)
    if dev:
        _device_id = dev
        return dev

    print("[El Fager] No Spotify device — launching desktop app...")
    if not _launch_spotify_app():
        return None

    for _ in range(20):          # poll every 0.25s, up to 5s total
        time.sleep(0.25)
        try:
            devices = sp.devices().get("devices", [])
        except Exception:
            continue
        dev = _best_device_id(devices)
        if dev:
            _device_id = dev
            return dev

    return None


def _is_device_gone(e) -> bool:
    """404 from the player endpoints means the cached device disappeared."""
    try:
        from spotipy.exceptions import SpotifyException
        return isinstance(e, SpotifyException) and e.http_status == 404
    except Exception:
        return False


def _start_playback(sp, dev: str, **kwargs) -> None:
    """start_playback, re-probing once if the cached device has gone away."""
    global _device_id
    try:
        sp.start_playback(device_id=dev, **kwargs)
        return
    except Exception as e:
        if not _is_device_gone(e):
            raise
    _device_id = None
    dev = _get_device(sp, use_cache=False)
    if dev is None:
        raise RuntimeError("no Spotify device available")
    sp.start_playback(device_id=dev, **kwargs)


def warm_up() -> None:
    """Pre-authenticate and pre-resolve a device in the background so the first
    'play X' of a session doesn't pay for the token refresh and device lookup.

    Only runs when a token is already cached — otherwise SpotifyOAuth would pop
    a browser consent window at every launch.
    """
    if not SPOTIFY_AVAILABLE or not os.path.exists("data/.spotify_cache"):
        return

    def _warm():
        try:
            sp = get_spotify()
            if sp is not None:
                _get_device(sp, use_cache=False)
        except Exception:
            pass

    threading.Thread(target=_warm, daemon=True, name="SpotifyWarmUp").start()


# ── "play X" command matching ─────────────────────────────────────────────────
# Recognising the command here lets El Fager act on it without a round trip to
# Claude — see Brain.chat(). Anything these don't match falls through to the
# normal tool loop, which still works, just slower.

_PLAY_EN = re.compile(
    r"""^\s*
        (?:hey\s+)?(?:el\s*fager\s*[,:]?\s*)?
        (?:can\s+you\s+|could\s+you\s+|please\s+|pls\s+)?
        (?:play|put\s+on)\s+
        (?:me\s+)?(?:the\s+song\s+|the\s+track\s+|a\s+song\s+|some\s+|a\s+)?
        (?P<q>.+?)
        (?:\s+(?:on|in|from)\s+spotify)?
        [\s.!?]*$""",
    re.IGNORECASE | re.VERBOSE,
)

_PLAY_AR = re.compile(
    r"^\s*(?:يا\s+الفجر[،,]?\s*)?"
    r"(?:شغللي|شغّللي|شغلي|شغّلي|شغل|شغّل)\s+"
    r"(?:لي\s+)?(?:أغنية\s+|اغنية\s+)?"
    r"(?P<q>.+?)[\s.!?،]*$"
)

# Common Arabizi spellings of "شغل".
_PLAY_ARABIZI = re.compile(
    r"^\s*(?:sha8+al|sha3+al|shagh+al|shag+al)(?:ly|li)?\s+(?P<q>.+?)[\s.!?]*$",
    re.IGNORECASE,
)

# Queries too vague to search for — let Claude work out what Mo meant.
_VAGUE = frozenset({
    "it", "this", "that", "one", "again", "it again", "that again",
    "music", "song", "songs", "track", "tune", "something", "anything",
    "more", "next", "next one", "next song", "next track", "previous",
    "back", "again please",
})

# "play" that isn't about Spotify.
_NOT_SPOTIFY = ("youtube", "video", "movie", "film", "netflix", "trailer", "episode")


def match_play_command(message: str) -> "tuple[str, bool] | None":
    """Return (search_query, is_arabic) for a plain 'play X' request, else None.

    None means 'not confidently a play command' — the caller should fall back to
    the normal tool loop rather than guess.
    """
    for pattern, arabic in ((_PLAY_EN, False), (_PLAY_AR, True), (_PLAY_ARABIZI, False)):
        m = pattern.match(message)
        if not m:
            continue
        query = " ".join(m.group("q").split())
        # "the next track" is a skip, not a search for a song called that.
        probe = re.sub(r"^(?:the|a|an)\s+", "", query.lower())
        if not query or probe in _VAGUE:
            return None
        if any(w in query.lower() for w in _NOT_SPOTIFY):
            return None
        return query, arabic
    return None


# ── Public Spotify functions ──────────────────────────────────────────────────

def play_music(query: str, arabic: bool = False) -> str:
    if not SPOTIFY_AVAILABLE:
        return _NOT_SET_UP
    sp = get_spotify()
    if sp is None:
        return "[Spotify auth failed — check credentials in .env]"
    try:
        dev = _get_device(sp)
        if dev is None:
            return ("افتح سبوتيفاي على الجهاز الأول وبعدين قولي شغل."
                    if arabic else
                    "Open Spotify on your PC first, then ask me to play.")

        mood_name, mood_search = _detect_mood(query)
        if mood_search:
            results = sp.search(q=mood_search, type="playlist", limit=5)
            playlists = [p for p in results.get("playlists", {}).get("items", []) if p]
            if playlists:
                pl = playlists[0]
                _start_playback(sp, dev, context_uri=pl["uri"])
                return (f"بشغّل {mood_name} — {pl['name']}" if arabic
                        else f"Playing {mood_name} vibes — {pl['name']}")
            return f"[No playlist found for '{mood_name}' mood]"

        results = sp.search(q=query, type="track,playlist,album", limit=3)

        tracks = results.get("tracks", {}).get("items", [])
        if tracks:
            _start_playback(sp, dev, uris=[tracks[0]["uri"]])
            return (f"بشغّل: {_fmt_track(tracks[0])}" if arabic
                    else f"Playing: {_fmt_track(tracks[0])}")

        playlists = results.get("playlists", {}).get("items", [])
        if playlists:
            pl = playlists[0]
            _start_playback(sp, dev, context_uri=pl["uri"])
            return (f"بشغّل بلاي ليست: {pl['name']}" if arabic
                    else f"Playing playlist: {pl['name']}")

        albums = results.get("albums", {}).get("items", [])
        if albums:
            al = albums[0]
            _start_playback(sp, dev, context_uri=al["uri"])
            artists = ", ".join(a["name"] for a in al.get("artists", []))
            return (f"بشغّل ألبوم: {al['name']} لـ {artists}" if arabic
                    else f"Playing album: {al['name']} by {artists}")

        return (f"ملقتش حاجة باسم '{query}'" if arabic
                else f"Nothing found for '{query}'")
    except Exception as e:
        return _spotify_error(e)


def pause_music() -> str:
    if not SPOTIFY_AVAILABLE:
        return _NOT_SET_UP
    sp = get_spotify()
    if sp is None:
        return "[Spotify auth failed]"
    try:
        pb = sp.current_playback()
        if pb and pb.get("is_playing"):
            # MS Store Spotify refuses explicit device_id on pause — always omit it.
            # Retry once: the desktop app rejects pause immediately after playback starts.
            try:
                sp.pause_playback()
            except Exception:
                time.sleep(0.4)
                sp.pause_playback()
            return "Paused"
        # Resume: device_id from playback state works for start_playback
        dev = (pb or {}).get("device", {}).get("id") or _get_device(sp)
        if not dev:
            return "Open Spotify on your PC first."
        sp.start_playback(device_id=dev)
        return "Resumed"
    except Exception as e:
        return _spotify_error(e)


def next_track() -> str:
    if not SPOTIFY_AVAILABLE:
        return _NOT_SET_UP
    sp = get_spotify()
    if sp is None:
        return "[Spotify auth failed]"
    try:
        dev = _get_device(sp)
        if dev is None:
            return "Open Spotify on your PC first."
        try:
            sp.next_track(device_id=dev)
        except Exception:
            time.sleep(0.4)
            sp.next_track(device_id=dev)
        time.sleep(0.4)
        pb = sp.current_playback()
        if pb and pb.get("item"):
            return f"Skipped — Now: {_fmt_track(pb['item'])}"
        return "Skipped"
    except Exception as e:
        return _spotify_error(e)


def what_playing() -> str:
    if not SPOTIFY_AVAILABLE:
        return _NOT_SET_UP
    sp = get_spotify()
    if sp is None:
        return "[Spotify auth failed]"
    try:
        pb = sp.current_playback()
        if not pb or not pb.get("is_playing") or not pb.get("item"):
            return "Nothing is currently playing"
        t = pb["item"]
        progress  = _ms_to_mss(pb.get("progress_ms", 0))
        duration  = _ms_to_mss(t.get("duration_ms", 0))
        return f"Now playing: {_fmt_track(t)} [{progress} / {duration}]"
    except Exception as e:
        return f"[Spotify error: {e}]"


def set_volume(level: int) -> str:
    if not SPOTIFY_AVAILABLE:
        return _NOT_SET_UP
    sp = get_spotify()
    if sp is None:
        return "[Spotify auth failed]"
    try:
        dev = _get_device(sp)
        vol = max(0, min(100, int(level)))
        sp.volume(vol, device_id=dev)
        return f"Volume set to {vol}%"
    except Exception as e:
        return _spotify_error(e)


def spotify_status() -> str:
    if not SPOTIFY_AVAILABLE:
        return _NOT_SET_UP
    sp = get_spotify()
    if sp is None:
        return "[Spotify auth failed]"
    lines = []
    try:
        user = sp.current_user()
        lines.append(f"Account: {user.get('display_name')} ({user.get('product', 'unknown')})")
    except Exception as e:
        lines.append(f"Account check failed: {e}")
    try:
        devices = sp.devices().get("devices", [])
        if devices:
            for d in devices:
                lines.append(f"Device: {d['name']} ({d['type']}){' [ACTIVE]' if d['is_active'] else ''}")
        else:
            lines.append("No Spotify devices found — open Spotify on any device")
    except Exception as e:
        lines.append(f"Device check failed: {e}")
    try:
        pb = sp.current_playback()
        if pb and pb.get("item"):
            state = "Playing" if pb.get("is_playing") else "Paused"
            lines.append(f"{state}: {_fmt_track(pb['item'])}")
        else:
            lines.append("Playback: nothing playing")
    except Exception as e:
        lines.append(f"Playback check failed: {e}")
    return "\n".join(lines)
