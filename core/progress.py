"""
El Fager — the step ledger.

While a turn is working, the surfaces should show *what* it is doing, not a
spinner. The brain funnels every tool call through one dispatch, so that is
where steps are recorded: one entry per call, tinted by the skill it belongs
to, green when it lands and red when it doesn't.

Same shape as core/staging — Qt-free, thread-safe, observed by whichever
surface is open. A turn's steps replace the previous turn's entirely.
"""

import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

_MAX_STEPS = 12

_lock = threading.RLock()
_steps: list["Step"] = []
_subscribers: list[Callable[[], None]] = []

# Which skill a tool belongs to — drives the dot tint (ui/tokens.SKILL_TINT).
# Matched as substrings against the tool name, longest first.
_SKILLS = {
    "whatsapp": "whatsapp",
    "gmail": "gmail",
    "email": "gmail",
    "message": "gmail",
    "calendar": "calendar",
    "event": "calendar",
    "todoist": "todoist",
    "task": "todoist",
    "browser": "browser",
    "web": "browser",
    "search": "browser",
}


def skill_for(tool: str) -> "str | None":
    """The skill a tool belongs to, or None for the app's own utilities."""
    low = tool.lower()
    for needle, skill in sorted(_SKILLS.items(), key=lambda kv: -len(kv[0])):
        if needle in low:
            return skill
    return None


def label_for(tool: str) -> str:
    """The tool's own name, said plainly — never a guess at intent."""
    return tool.replace("_", " ").strip().lower()


@dataclass
class Step:
    tool: str
    label: str
    skill: "str | None"
    status: str = "active"          # active | done | failed
    started_at: datetime = field(default_factory=datetime.now)


def _notify() -> None:
    for cb in list(_subscribers):
        try:
            cb()
        except Exception:
            pass          # a broken surface must never break a turn


def subscribe(callback: Callable[[], None]) -> None:
    with _lock:
        if callback not in _subscribers:
            _subscribers.append(callback)


def unsubscribe(callback: Callable[[], None]) -> None:
    with _lock:
        if callback in _subscribers:
            _subscribers.remove(callback)


_utterance = ""


def begin_turn(utterance: str = "") -> None:
    """A new utterance: the previous turn's steps leave the stage.

    The utterance is kept so the Trust Ledger can say *why* something
    happened in Mo's own words rather than guessing at intent.
    """
    global _utterance
    with _lock:
        _steps.clear()
        _utterance = utterance or ""
    _notify()


def utterance() -> str:
    """What was said this turn, for provenance."""
    with _lock:
        return _utterance


def step_started(tool: str) -> int:
    """Record a tool going to work. Returns its index for step_finished()."""
    with _lock:
        _steps.append(Step(tool=tool, label=label_for(tool), skill=skill_for(tool)))
        del _steps[:-_MAX_STEPS]
        index = len(_steps) - 1
    _notify()
    return index


def step_finished(index: int, ok: bool = True) -> None:
    step = None
    with _lock:
        if 0 <= index < len(_steps):
            step = _steps[index]
            step.status = "done" if ok else "failed"
    if step is not None:
        # started_at was stamped and never read. A turn that feels slow is
        # usually one slow tool, and this is the only place that knows which.
        try:
            from core import turn_profile
            elapsed = (datetime.now() - step.started_at).total_seconds() * 1000
            turn_profile.tool(step.tool, elapsed)
        except Exception:
            pass
    _notify()


def steps() -> list[Step]:
    with _lock:
        return list(_steps)


def active_label() -> "str | None":
    """What the assistant is doing right now, for a one-line caption."""
    with _lock:
        for step in reversed(_steps):
            if step.status == "active":
                return step.label
    return None


def reset() -> None:
    """Test hook — clears the steps and the subscribers."""
    with _lock:
        _steps.clear()
        _subscribers.clear()
