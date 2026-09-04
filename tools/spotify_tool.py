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
import subprocess
import time
from urllib.parse import quote

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

def _launch_spotify_app(uri: str = "spotify:") -> bool:
    """
    Open the Spotify desktop app via Windows shell protocol.
    Handing it a track/album/playlist URI opens the app AND starts playing it —
    that works on Free accounts, unlike the Web API playback endpoints.
    """
    try:
        os.startfile(uri)
        return True
    except Exception:
        pass
    for exe in [
        os.path.join(os.environ.get("APPDATA", ""), "Spotify", "Spotify.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WindowsApps", "Spotify.exe"),
    ]:
        if os.path.exists(exe):
            subprocess.Popen([exe, uri])
            return True
    return False

def _open_search_in_app(query: str) -> str:
    """No API credentials — open the app on the search results and let Mo pick."""
    if _launch_spotify_app("spotify:search:" + quote(query)):
        return f"Opened Spotify and searched for '{query}' — hit play on the one you want."
    return _NOT_SET_UP

def _active_device(sp) -> str | None:
    """Device id if Spotify is already running somewhere. No launching, no polling."""
    try:
        return _best_device_id(sp.devices().get("devices", []))
    except Exception:
        return None

def _search_uri(sp, query: str, playlist_only: bool = False) -> tuple[str, str] | None:
    """Resolve a query to (spotify uri, spoken label). Track first, then playlist, then album."""
    if playlist_only:
        results = sp.search(q=query, type="playlist", limit=5)
        for pl in results.get("playlists", {}).get("items", []):
            if pl:
                return pl["uri"], pl["name"]
        return None

    results = sp.search(q=query, type="track,playlist,album", limit=3)

    tracks = results.get("tracks", {}).get("items", [])
    if tracks:
        return tracks[0]["uri"], _fmt_track(tracks[0])

    for pl in results.get("playlists", {}).get("items", []):
        if pl:
            return pl["uri"], f"playlist {pl['name']}"

    albums = results.get("albums", {}).get("items", [])
    if albums:
        al = albums[0]
        artists = ", ".join(a["name"] for a in al.get("artists", []))
        return al["uri"], f"album {al['name']} by {artists}"

    return None

def _get_device(sp) -> str | None:
    """
    Return best available device_id.
    Prefers desktop app over Web Player.
    If no devices found, launches the app and polls for up to 5s.
    Passing device_id to start_playback activates the device in one shot —
    no separate transfer_playback call needed.
    """
    try:
        devices = sp.devices().get("devices", [])
    except Exception:
        return None

    dev = _best_device_id(devices)
    if dev:
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
            return dev

    return None


# ── Public Spotify functions ──────────────────────────────────────────────────

def play_music(query: str) -> str:
    """
    Search Spotify for the query and start playing the best match.

    Playback goes through the Web API when Spotify is already running and the
    account can drive it. Otherwise the resolved URI is handed to the desktop
    app, which opens and plays it — so "play <song>" works on Free accounts and
    when Spotify isn't open yet.
    """
    sp = get_spotify() if SPOTIFY_AVAILABLE else None
    if sp is None:
        # No credentials (or auth failed): open the app on the search results.
        return _open_search_in_app(query)

    mood_name, mood_search = _detect_mood(query)
    try:
        found = _search_uri(sp, mood_search or query, playlist_only=bool(mood_search))
    except Exception as e:
        return _spotify_error(e)

    if found is None:
        if mood_name:
            return f"[No playlist found for '{mood_name}' mood]"
        return f"Nothing found for '{query}'"

    uri, label = found
    if mood_name:
        label = f"{mood_name} vibes — {label}"

    dev = _active_device(sp)
    if dev:
        try:
            if uri.startswith("spotify:track:"):
                sp.start_playback(device_id=dev, uris=[uri])
            else:
                sp.start_playback(device_id=dev, context_uri=uri)
            return f"Playing: {label}"
        except Exception:
            pass  # Free account or the device refused — fall through to the app.

    if _launch_spotify_app(uri):
        return f"Playing: {label}"
    return "[Couldn't open Spotify — is the desktop app installed?]"


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
