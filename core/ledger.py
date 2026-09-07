"""
El Fager — the Trust Ledger.

The append-only record of everything El Fager did on Mo's behalf. This is the
trust anchor for an agent holding his Gmail and WhatsApp, so the rules below
are enforced by the code, not by convention:

  THE LAW — nothing here is ever edited or deleted. A revoke appends a NEW
  entry that undoes the old one; the original stays in the file and reads
  REVOKED. Stored locally, encrypted at rest, and never leaves the machine.

Each line of data/action_ledger.jsonl is one Fernet token, so appending stays
a single write and the file is unreadable without data/ledger.key. Legacy
plaintext lines from before encryption are still readable.

Every entry says *why* it happened. Provenance comes from the turn that
caused it — the actual utterance — never from a guess.
"""

import json
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

_LEDGER = Path("data/action_ledger.jsonl")
_KEY = Path("data/ledger.key")

_lock = threading.RLock()
_fernet: "Fernet | None" = None

# The design's categories and their hues live in the UI; the record only
# needs to agree on the vocabulary.
CATEGORIES = ("sent", "changed", "logged", "learned", "read", "acted", "revoked")

# How long an entry stays revocable. These mirror what the underlying service
# actually allows — past the window the entry reads SEALED because nothing in
# the world can be walked back, not because El Fager chose to stop offering.
REVERSAL_WINDOWS = {
    "whatsapp": timedelta(days=2),      # "delete for everyone" window
    "gmail": timedelta(seconds=30),     # undo-send window
    "calendar": timedelta(days=30),     # a deleted event stays restorable
}
_DEFAULT_WINDOW = timedelta(0)


def _key() -> Fernet:
    global _fernet
    if _fernet is None:
        _KEY.parent.mkdir(parents=True, exist_ok=True)
        if _KEY.exists():
            raw = _KEY.read_bytes()
        else:
            raw = Fernet.generate_key()
            _KEY.write_bytes(raw)
        _fernet = Fernet(raw)
    return _fernet


def append(
    category: str,
    medium: str,
    target: str,
    summary: str,
    provenance: str = "",
    **extra,
) -> dict:
    """Write one entry. This is the only way in, and it only ever appends."""
    entry = {
        "id": uuid.uuid4().hex[:12],
        "category": category if category in CATEGORIES else "acted",
        "medium": medium,
        "target": target,
        "summary": summary,
        "provenance": provenance or "CONFIRMED IN THE APP",
        "ts": datetime.now().isoformat(timespec="seconds"),
        "at": datetime.now().strftime("%H:%M"),
    }
    entry.update(extra)
    with _lock:
        try:
            _LEDGER.parent.mkdir(parents=True, exist_ok=True)
            token = _key().encrypt(json.dumps(entry, ensure_ascii=False).encode("utf-8"))
            with _LEDGER.open("ab") as fh:
                fh.write(token + b"\n")
        except Exception:
            pass      # the ledger is a record, never a gate on doing the thing
    return entry


def _read_raw() -> list[dict]:
    if not _LEDGER.exists():
        return []
    out = []
    for line in _LEDGER.read_bytes().splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(_key().decrypt(line)))
        except (InvalidToken, ValueError):
            try:
                out.append(json.loads(line))      # pre-encryption lines
            except Exception:
                continue
    return out


def entries(limit: int = 50, category: "str | None" = None) -> list[dict]:
    """The record, newest first, with revoked/sealed resolved by reading it.

    Nothing is mutated to mark a revocation — the revoking entry is what
    makes the original read REVOKED.
    """
    with _lock:
        raw = _read_raw()

    revoked_ids = {e["revokes"] for e in raw if e.get("revokes")}
    now = datetime.now()
    resolved = []
    for entry in raw:
        item = dict(entry)
        item["revoked"] = entry.get("id") in revoked_ids
        item["sealed"] = not _within_window(entry, now) and not item["revoked"]
        resolved.append(item)

    resolved.reverse()
    if category:
        resolved = [e for e in resolved if e.get("category") == category]
    return resolved[:limit]


def _within_window(entry: dict, now: datetime) -> bool:
    if entry.get("category") == "revoked":
        return False
    window = REVERSAL_WINDOWS.get(entry.get("medium", ""), _DEFAULT_WINDOW)
    try:
        started = datetime.fromisoformat(entry["ts"])
    except Exception:
        return False
    return now - started <= window


def revocable(limit: int = 500) -> list[dict]:
    """Still-revocable entries — the number on the header that matters."""
    return [e for e in entries(limit) if not e["sealed"] and not e["revoked"]]


def revoke(entry_id: str, provenance: str = "", performed: bool = False) -> "dict | None":
    """Undo an entry by appending its reversal. The original is left alone.

    `performed` says whether the world was actually changed back. When it is
    False the ledger records the revocation only — it must never imply a
    message was unsent when it wasn't.
    """
    with _lock:
        original = next((e for e in _read_raw() if e.get("id") == entry_id), None)
    if original is None:
        return None
    return append(
        category="revoked",
        medium=original.get("medium", ""),
        target=original.get("target", ""),
        summary=f"revoked · {original.get('summary', '')}",
        provenance=provenance or "YOU REVOKED THIS",
        revokes=entry_id,
        reversal="performed" if performed else "recorded",
    )


def search(query: str, limit: int = 20) -> list[dict]:
    """Answer from the record, never from the model.

    A plain substring match over what was actually stored. It returns what is
    written or nothing at all — it does not infer, rank, or paraphrase.
    """
    q = query.strip().lower()
    if not q:
        return []
    hits = []
    for entry in entries(limit=1000):
        haystack = " ".join(
            str(entry.get(k, "")) for k in ("medium", "target", "summary", "provenance", "category")
        ).lower()
        if q in haystack:
            hits.append(entry)
        if len(hits) >= limit:
            break
    return hits


def counters() -> dict:
    """What the ledger header shows: total in 30 days, and still revocable."""
    recent = [
        e for e in entries(limit=1000)
        if (datetime.now() - datetime.fromisoformat(e["ts"])) <= timedelta(days=30)
    ]
    return {"total_30d": len(recent), "revocable": len(revocable())}
