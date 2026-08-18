"""
Turn profiling — where a voice turn actually spends its time.

Three stdout prints measured fragments of a turn and nothing measured the
whole; one of them had no duration at all. So there was no way to say whether
a change made El Fager faster, only whether it felt faster.

One JSON line per turn is appended to data/telemetry/turns-YYYY-MM-DD.jsonl,
alongside the per-API-call records core/telemetry.py already writes:

    {"timestamp": ..., "transcript_len": 34, "stages": {"stt": 812.4, ...},
     "tools": {"list_emails": 431.2}, "total_ms": 4210.8}

OFF unless EL_FAGER_PROFILE=1, and when off every call here is a couple of
attribute lookups — the recorder is never constructed. Profiling that costs
latency would defeat the point.

Like telemetry, this must NEVER raise: a measurement failure must not break a
turn. Every public entry point swallows.
"""
import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path

_DIR = Path("data/telemetry")

# Read once. Flipping it mid-session would give a half-profiled turn, which is
# worse than no profile at all.
ENABLED = os.getenv("EL_FAGER_PROFILE", "").strip() not in ("", "0", "false", "False")

# The pipeline runs one turn at a time on its own thread, but the wake word,
# the TTS worker and the tool dispatch all call in from elsewhere. One lock
# keeps a stage landing in the right turn.
_lock = threading.Lock()
_current: "TurnProfile | None" = None


class TurnProfile:
    """Stage timings for a single turn. Times are ms since the turn began."""

    def __init__(self, label: str = ""):
        self.label = label
        self.t0 = time.monotonic()
        self.stages: dict[str, float] = {}
        self.tools: dict[str, float] = {}
        self._open: dict[str, float] = {}

    # ── recording ──────────────────────────────────────────────────────────

    def start(self, stage: str) -> None:
        self._open[stage] = time.monotonic()

    def end(self, stage: str) -> None:
        started = self._open.pop(stage, None)
        if started is None:
            return
        self.stages[stage] = round((time.monotonic() - started) * 1000, 1)

    def mark(self, stage: str) -> None:
        """A moment rather than a span: ms from the start of the turn.

        first_token and first_audio are the numbers that matter to how fast it
        *feels*, and both are moments — the point at which something reaches
        Mo, not the duration of the thing that produced it.
        """
        self.stages[stage] = round((time.monotonic() - self.t0) * 1000, 1)

    def tool(self, name: str, ms: float) -> None:
        # Same tool twice in a turn accumulates rather than overwrites.
        self.tools[name] = round(self.tools.get(name, 0.0) + float(ms), 1)

    def as_entry(self) -> dict:
        return {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "label": self.label[:120],
            "stages": dict(self.stages),
            "tools": dict(self.tools),
            "total_ms": round((time.monotonic() - self.t0) * 1000, 1),
        }


# ── module API: no-ops when disabled ───────────────────────────────────────

def begin(label: str = "") -> None:
    if not ENABLED:
        return
    global _current
    with _lock:
        _current = TurnProfile(label)


def start(stage: str) -> None:
    if not ENABLED:
        return
    try:
        with _lock:
            if _current is not None:
                _current.start(stage)
    except Exception:
        pass


def end(stage: str) -> None:
    if not ENABLED:
        return
    try:
        with _lock:
            if _current is not None:
                _current.end(stage)
    except Exception:
        pass


def mark(stage: str) -> None:
    if not ENABLED:
        return
    try:
        with _lock:
            if _current is not None:
                _current.mark(stage)
    except Exception:
        pass


def tool(name: str, ms: float) -> None:
    if not ENABLED:
        return
    try:
        with _lock:
            if _current is not None:
                _current.tool(name, ms)
    except Exception:
        pass


def finish() -> "dict | None":
    """Close the turn and append it. Returns the entry, for tests."""
    if not ENABLED:
        return None
    global _current
    try:
        with _lock:
            if _current is None:
                return None
            entry = _current.as_entry()
            _current = None
        _DIR.mkdir(parents=True, exist_ok=True)
        day = datetime.now().strftime("%Y-%m-%d")
        with (_DIR / f"turns-{day}.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        stages = " ".join(f"{k}={v:.0f}" for k, v in entry["stages"].items())
        print(f"[El Fager] turn {entry['total_ms']:.0f}ms  {stages}")
        return entry
    except Exception:
        return None
