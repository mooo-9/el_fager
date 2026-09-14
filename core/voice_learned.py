"""Names Whisper should know, learned from the songs El Fager plays.

Spotify returns a track's real title and artists — "Estanna by Tawsen and
Fares Sokar" — exactly the names Whisper otherwise spells as English words.
Kept here, they join the hint sentence (core/voice_in.py) after the list Mo
keeps by hand in Settings → voice_vocabulary.

Only a song that keeps playing is learned. El Fager sometimes plays the wrong
song first and is corrected within a minute; learning those would teach
Whisper the mistakes. So a played song waits here as pending, and becomes a
learned name only once KEEP_SECONDS pass without another song replacing it.

Names in non-Latin script are skipped: the transcription is forced to
English, and an Arabic spelling in the hint cannot help it.
"""
import json
import threading
import time
from pathlib import Path

_FILE = Path("data/voice_learned.json")
KEEP_SECONDS = 60
MAX_NAMES = 20

_lock = threading.Lock()


def _now() -> float:
    return time.time()


def _latin(name: str) -> bool:
    return all(ord(ch) < 0x0250 or not ch.isalpha() for ch in name)


def _load() -> dict:
    try:
        data = json.loads(_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save(data: dict) -> None:
    _FILE.parent.mkdir(parents=True, exist_ok=True)
    _FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _promote(data: dict) -> bool:
    """Move a pending song that has kept playing into the learned names."""
    pending = data.get("pending")
    if not pending or _now() - float(pending.get("at", 0)) < KEEP_SECONDS:
        return False
    fresh = [n for n in pending.get("names", []) if n]
    rest = [n for n in data.get("names", []) if n.lower() not in {f.lower() for f in fresh}]
    data["names"] = (fresh + rest)[:MAX_NAMES]
    data.pop("pending", None)
    return True


def played(title: str, artists: "list[str]") -> None:
    """A song just started. It is learned if nothing replaces it for a minute;
    whatever was pending before it — replaced already — is dropped."""
    names, seen = [], set()
    for name in [title, *artists]:
        name = str(name or "").strip()
        if name and _latin(name) and name.lower() not in seen:
            seen.add(name.lower())
            names.append(name)
    with _lock:
        data = _load()
        _promote(data)                 # a song that already kept playing stays learned
        data["pending"] = {"names": names, "at": _now()}
        _save(data)


def names() -> "list[str]":
    """The learned names, newest first."""
    with _lock:
        data = _load()
        if _promote(data):
            try:
                _save(data)
            except OSError:
                pass
        return list(data.get("names", []))
