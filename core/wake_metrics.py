"""
El Fager — wake-word reliability.

If voice is the primary way in, the wake word is the front door, and nobody
knows whether it works. "It seems fine" is not a number. This records the two
failures that matter and lets them be counted:

  * a **false accept** — it woke and nothing was said. Visible from here: a
    detection with no speech behind it.
  * a **miss** — you called it and it stayed asleep. Not visible from here by
    construction: nothing fires, so nothing can be logged. Misses have to be
    reported by hand (`note_miss()`), which is why the summary says how many
    were reported rather than pretending to a rate.

The pipeline resolves each detection: it opens the mic straight after a wake,
so whether that recording produced a transcript is the verdict. A turn that
began at the keyboard has no detection waiting and is ignored.

Qt-free and dependency-free — the wake listener is a bare daemon thread.
"""

import json
import threading
from datetime import datetime, timedelta
from pathlib import Path

_LOG = Path("data/wake_log.jsonl")

# How long after a detection a recording still counts as its outcome. The
# pipeline starts recording within a frame or two; anything later is a
# different turn.
_RESOLVE_WINDOW_SEC = 30.0

_lock = threading.RLock()
_pending: "dict | None" = None


def _append(entry: dict) -> None:
    try:
        _LOG.parent.mkdir(parents=True, exist_ok=True)
        with _LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass          # measurement must never break the thing it measures


def note_detection(model: str, score: float) -> None:
    """The listener heard the wake word. Outcome unknown until speech is."""
    global _pending
    with _lock:
        _pending = {
            "at": datetime.now().isoformat(timespec="seconds"),
            "model": model,
            "score": round(float(score), 3),
            "t": datetime.now(),
        }


def note_speech(heard: bool) -> None:
    """The recording that followed a wake either had words in it or didn't.

    Called by the pipeline for every turn; turns with no detection waiting
    (hotkey, typed, scheduled) resolve nothing.
    """
    global _pending
    with _lock:
        entry = _pending
        _pending = None
    if entry is None:
        return
    if (datetime.now() - entry.pop("t")).total_seconds() > _RESOLVE_WINDOW_SEC:
        return
    entry["outcome"] = "heard" if heard else "silent"
    _append(entry)


def note_miss(note: str = "") -> None:
    """You called it and it didn't wake. Only you can report this one."""
    _append({
        "at": datetime.now().isoformat(timespec="seconds"),
        "outcome": "missed",
        "note": note[:120],
    })


def _entries(days: int):
    if not _LOG.exists():
        return
    cutoff = datetime.now() - timedelta(days=days)
    try:
        lines = _LOG.read_text(encoding="utf-8").splitlines()
    except Exception:
        return
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            if datetime.fromisoformat(entry["at"]) >= cutoff:
                yield entry
        except Exception:
            continue


def summary(days: int = 7) -> dict:
    """Counts over the window, plus the false-accept rate they imply."""
    heard = silent = missed = 0
    scores: list[float] = []
    for entry in _entries(days):
        outcome = entry.get("outcome")
        if outcome == "heard":
            heard += 1
            scores.append(entry.get("score", 0.0))
        elif outcome == "silent":
            silent += 1
            scores.append(entry.get("score", 0.0))
        elif outcome == "missed":
            missed += 1
    woke = heard + silent
    return {
        "days": days,
        "detections": woke,
        "heard": heard,
        "false_accepts": silent,
        "false_accept_rate": (silent / woke) if woke else 0.0,
        "reported_misses": missed,
        "mean_score": (sum(scores) / len(scores)) if scores else 0.0,
    }


def caption(days: int = 7) -> str:
    """One mono line for Settings → Voice, in the surface's own register."""
    s = summary(days)
    if not s["detections"] and not s["reported_misses"]:
        return "NO WAKES RECORDED YET"
    parts = [f"WOKE {s['detections']}× IN {days} DAYS"]
    if s["detections"]:
        parts.append(
            f"{s['false_accepts']} TO SILENCE ({s['false_accept_rate'] * 100:.0f}%)")
    if s["reported_misses"]:
        misses = s["reported_misses"]
        parts.append(f"{misses} MISS{'ES' if misses != 1 else ''} REPORTED")
    return " · ".join(parts)


def reset() -> None:
    """Test hook."""
    global _pending
    with _lock:
        _pending = None
