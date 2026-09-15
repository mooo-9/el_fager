"""
El Fager — the staging registry.

Every outbound action goes stage → preview → confirm. The staging tools each
kept that state privately, so nothing could *show* Mo what was armed. This is
the one place that knows: tools announce what they staged, announce when it
resolves, and any surface (overlay, Command Center, phone) can read the same
record and drive the same confirm.

Deliberately Qt-free and dependency-free so it stays importable from tools,
the pipeline thread, and the dashboard's HTTP handler alike. Surfaces bridge
to their own thread by emitting a signal from `subscribe()`.

A confirmed send hands a receipt to core.ledger — a short summary and why it
happened, never the message body.
"""

import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

_MAX_RECEIPTS = 3

_lock = threading.RLock()
_staged: "StagedAction | None" = None
_receipts: list[dict] = []
_subscribers: list[Callable[[], None]] = []


@dataclass
class StagedAction:
    """An action armed and waiting for a yes. `body` is shown in the target
    medium's own shape, so it stays exactly as the tool composed it."""

    medium: str                  # whatsapp | gmail | calendar
    target: str                  # who or what it lands on
    body: str
    subject: "str | None" = None
    expires_at: "datetime | None" = None
    # PNG of the recipient's profile photo, shown beside the draft so Mo can
    # see who it's going to. In memory only — never written to disk.
    photo: "bytes | None" = field(default=None, repr=False)
    confirm: "Callable[[], str] | None" = field(default=None, repr=False)
    cancel: "Callable[[], None] | None" = field(default=None, repr=False)
    staged_at: datetime = field(default_factory=datetime.now)

    @property
    def expired(self) -> bool:
        if self.expires_at is None:
            return False
        now = datetime.now(self.expires_at.tzinfo) if self.expires_at.tzinfo else datetime.now()
        return now > self.expires_at


def _notify() -> None:
    for cb in list(_subscribers):
        try:
            cb()
        except Exception:
            pass          # a broken surface must never break a send


def subscribe(callback: Callable[[], None]) -> None:
    """Called (on whatever thread staged) whenever the staged action changes."""
    with _lock:
        if callback not in _subscribers:
            _subscribers.append(callback)


def unsubscribe(callback: Callable[[], None]) -> None:
    with _lock:
        if callback in _subscribers:
            _subscribers.remove(callback)


def stage(medium: str, target: str, body: str, **kwargs) -> StagedAction:
    """Announce that an action is armed. Staging a new one replaces the old."""
    global _staged
    with _lock:
        _staged = StagedAction(medium=medium, target=target, body=body, **kwargs)
        action = _staged
    _notify()
    return action


def current() -> "StagedAction | None":
    """The armed action, or None once it has expired or resolved."""
    global _staged
    with _lock:
        if _staged is not None and _staged.expired:
            _staged = None
        return _staged


def confirm() -> str:
    """Run the staged action's own confirm. The tool calls resolve() itself,
    so voice ('yes send it'), a click, and the phone all end up in one place."""
    with _lock:
        action = _staged
    if action is None:
        return "Nothing is staged."
    if action.expired:
        resolve("expired")
        return "That expired — say it again to retry."
    if action.confirm is None:
        return "Nothing to confirm."
    return action.confirm()


def cancel() -> None:
    """Drop the armed action without sending it."""
    with _lock:
        action = _staged
    if action is not None and action.cancel is not None:
        try:
            action.cancel()
        except Exception:
            pass
    resolve("cancelled")


def resolve(status: str, summary: "str | None" = None) -> None:
    """Called by a tool when a staged action finishes — sent, cancelled, or
    expired. A send writes a receipt; the rest just clear the stage."""
    global _staged
    with _lock:
        action = _staged
        _staged = None
        if status == "sent" and action is not None:
            receipt = {
                "medium": action.medium,
                "target": action.target,
                "summary": summary or f"{action.medium} → {action.target} · sent",
                "at": datetime.now().strftime("%H:%M"),
                "ts": datetime.now().isoformat(timespec="seconds"),
            }
            _receipts.insert(0, receipt)
            del _receipts[_MAX_RECEIPTS:]
            _append_ledger(receipt, action)
    _notify()


def receipts() -> list[dict]:
    with _lock:
        return list(_receipts)


def _append_ledger(receipt: dict, action: "StagedAction") -> None:
    """Hand the send to the Trust Ledger, with why it happened."""
    try:
        from core import ledger, progress

        said = progress.utterance()
        provenance = (
            f"YOU SAID “{said}” · CONFIRMED BY VOICE" if said
            else "CONFIRMED IN THE APP"
        )
        ledger.append(
            category="changed" if action.medium == "calendar" else "sent",
            medium=action.medium,
            target=action.target,
            summary=receipt["summary"],
            provenance=provenance,
        )
    except Exception:
        pass          # the ledger is a record, not a gate on sending


def reset() -> None:
    """Test hook — clears the stage, the receipts and the subscribers."""
    global _staged
    with _lock:
        _staged = None
        _receipts.clear()
        _subscribers.clear()
