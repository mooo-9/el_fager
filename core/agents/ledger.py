"""
Agent ledger — the accountability record for every assignment El Fager makes.

One JSON line per attempt in data/agent_runs.jsonl, mirroring core/telemetry.py:
this is observability, so like telemetry it NEVER raises. A broken ledger must
not stop an agent from working.

Answers: who did what, did it pass inspection, how long it took, and who is
running right now.
"""
import json
import threading
from datetime import datetime, timedelta
from pathlib import Path

_LEDGER_PATH = Path("data/agent_runs.jsonl")

# Assignments currently executing, keyed by a token the supervisor holds.
_active: dict[str, dict] = {}
_active_lock = threading.Lock()


def record(callsign: str, task: str, verdict: str, *, reason: str = "",
           attempt: int = 1, duration_s: float = 0.0, source: str = "voice",
           result: str = "", acceptance: str | None = None) -> None:
    """Append one attempt. Swallows every error by design."""
    try:
        entry = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "callsign": callsign,
            "task": (task or "")[:300],
            "acceptance": (acceptance or "")[:300] or None,
            "verdict": verdict,
            "reason": (reason or "")[:300],
            "attempt": attempt,
            "duration_s": round(float(duration_s), 1),
            "source": source,
            "result": (result or "")[:500],
        }
        _LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _LEDGER_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def start_run(callsign: str, task: str, source: str) -> str:
    """Mark an assignment as running. Returns a token for finish_run()."""
    token = f"{callsign}:{datetime.now().timestamp()}"
    try:
        with _active_lock:
            _active[token] = {
                "callsign": callsign,
                "task": (task or "")[:200],
                "source": source,
                "since": datetime.now().isoformat(timespec="seconds"),
            }
    except Exception:
        pass
    return token


def finish_run(token: str) -> None:
    try:
        with _active_lock:
            _active.pop(token, None)
    except Exception:
        pass


def active_runs() -> list[dict]:
    """Assignments executing right now -- 'what is Sage doing?'"""
    try:
        with _active_lock:
            return list(_active.values())
    except Exception:
        return []


def _entries(days: int = 1):
    try:
        if not _LEDGER_PATH.exists():
            return
        cutoff = datetime.now() - timedelta(days=days)
        for line in _LEDGER_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if datetime.fromisoformat(entry["ts"]) >= cutoff:
                    yield entry
            except Exception:
                continue
    except Exception:
        return


def recent(callsign: str | None = None, n: int = 20, days: int = 7) -> list[dict]:
    entries = [
        e for e in _entries(days)
        if callsign is None or e.get("callsign", "").lower() == callsign.lower()
    ]
    return entries[-n:]


def roster_status(days: int = 1) -> dict[str, dict]:
    """Per-agent run count, pass rate, and last verdict over the window."""
    stats: dict[str, dict] = {}
    for e in _entries(days):
        bucket = stats.setdefault(
            e.get("callsign", "unknown"),
            {"runs": 0, "passed": 0, "failed": 0, "last_verdict": None, "last_ts": None},
        )
        bucket["runs"] += 1
        verdict = e.get("verdict")
        if verdict == "pass":
            bucket["passed"] += 1
        elif verdict in ("fail", "blocked"):
            bucket["failed"] += 1
        bucket["last_verdict"] = verdict
        bucket["last_ts"] = e.get("ts")
    for bucket in stats.values():
        bucket["pass_rate"] = (
            round(100 * bucket["passed"] / bucket["runs"]) if bucket["runs"] else 0
        )
    return stats


def format_report(callsign: str | None = None, days: int = 1) -> str:
    """Spoken/printed summary for the agent_report tool. cp1252-safe."""
    stats = roster_status(days)
    if callsign:
        bucket = stats.get(callsign)
        if not bucket:
            return f"{callsign} has not run in the last {days} day(s)."
        runs = recent(callsign, n=3, days=days)
        lines = [
            f"{callsign}: {bucket['runs']} runs, {bucket['pass_rate']}% passed "
            f"inspection, last verdict {bucket['last_verdict']}."
        ]
        for e in runs:
            lines.append(f"  [{e['verdict']}] {e['task'][:60]}")
        return "\n".join(lines)
    if not stats:
        return f"No agent has run in the last {days} day(s)."
    lines = [f"Agent report, last {days} day(s):"]
    for name, bucket in sorted(stats.items()):
        lines.append(
            f"  {name}: {bucket['runs']} runs, {bucket['pass_rate']}% passed, "
            f"{bucket['failed']} failed."
        )
    return "\n".join(lines)
