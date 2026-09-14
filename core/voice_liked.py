"""Names from Mo's Spotify Liked Songs, for Whisper's hint sentence.

Most of what Mo asks to play is in Liked Songs, so its names are the ones
Whisper most needs, even for songs El Fager has never played. Once a day this
reads up to MAX_TRACKS liked songs and keeps two things: the newest liked
songs (title and artists) and the most-liked artists (most songs; a tie goes
to the one liked more recently). They join the hint after the hand-written
vocabulary and the names learned from songs played (core/voice_in.py).

Reading uses the library login from scripts/spotify_library_login.py and
never prompts: without it nothing happens. A failed read keeps the last
summary. Names in non-Latin script are skipped, as the transcription is
forced to English.
"""
import json
import threading
import time
from collections import Counter
from pathlib import Path

_FILE = Path("data/voice_liked.json")
REFRESH_SECONDS = 24 * 3600
CHECK_EVERY_SECONDS = 3600
MAX_TRACKS = 1000
RECENT_SONGS = 8
TOP_ARTISTS = 12
_PAGE = 50

_lock = threading.Lock()


def _now() -> float:
    return time.time()


def _latin(name: str) -> bool:
    return all(ord(ch) < 0x0250 or not ch.isalpha() for ch in name)


def _client():
    from tools import spotify_tool
    return spotify_tool.get_library_client()


def summarise(items: list, recent: int = RECENT_SONGS, artists: int = TOP_ARTISTS) -> dict:
    """items: saved-track rows, newest first."""
    tracks = [row["track"] for row in items if row and row.get("track")]

    newest, seen = [], set()
    for t in tracks[:recent]:
        for name in [t.get("name", ""), *(a.get("name", "") for a in t.get("artists", []))]:
            name = str(name).strip().rstrip(",.;:").strip()
            if name and _latin(name) and name.lower() not in seen:
                seen.add(name.lower())
                newest.append(name)

    counts, first_seen = Counter(), {}
    for position, t in enumerate(tracks):
        for a in t.get("artists", []):
            name = str(a.get("name", "")).strip().rstrip(",.;:").strip()
            if name and _latin(name):
                counts[name] += 1
                first_seen.setdefault(name, position)
    ranked = sorted(counts, key=lambda n: (-counts[n], first_seen[n]))
    return {"recent": newest, "artists": ranked[:artists]}


def refresh_if_stale() -> bool:
    """Read Liked Songs if the saved summary is a day old. True if it did."""
    with _lock:
        try:
            saved = json.loads(_FILE.read_text(encoding="utf-8"))
            if _now() - float(saved.get("at", 0)) < REFRESH_SECONDS:
                return False
        except Exception:
            pass
        client = _client()
        if client is None:
            return False               # no library login yet: nothing to read
        items = []
        try:
            offset = 0
            while offset < MAX_TRACKS:
                page = client.current_user_saved_tracks(limit=_PAGE, offset=offset)
                items.extend(page.get("items", []))
                if not page.get("next"):
                    break
                offset += _PAGE
        except Exception:
            return False               # offline or refused: keep the last summary
        summary = summarise(items)
        summary["at"] = _now()
        try:
            _FILE.parent.mkdir(parents=True, exist_ok=True)
            _FILE.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        except OSError:
            return False
        return True


def names() -> "list[str]":
    """Newest liked songs first, then the most-liked artists."""
    try:
        saved = json.loads(_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []
    out, seen = [], set()
    for name in [*saved.get("recent", []), *saved.get("artists", [])]:
        if name.lower() not in seen:
            seen.add(name.lower())
            out.append(name)
    return out


def start() -> None:
    """Check once now and every hour after, in the background; it only reads
    the library when the saved summary is a day old."""
    def loop():
        while True:
            try:
                refresh_if_stale()
            except Exception:
                pass
            time.sleep(CHECK_EVERY_SECONDS)
    threading.Thread(target=loop, name="voice-liked", daemon=True).start()
