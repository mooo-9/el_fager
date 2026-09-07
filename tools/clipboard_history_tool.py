"""
Clipboard history — Phase 6G.
Runs a background monitor thread that logs clipboard changes to data/clipboard_history.jsonl.
'What did I copy earlier?' → get_clipboard_history()
"""

import json
import threading
import time
from datetime import datetime
from pathlib import Path
from core import atomic

HISTORY_PATH = Path("data/clipboard_history.jsonl")
MAX_ENTRIES = 200
_POLL_INTERVAL = 2  # seconds


class _ClipboardMonitor(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True, name="ClipboardMonitor")
        self._last = ""
        self._running = True

    def run(self):
        import pyperclip
        while self._running:
            try:
                current = pyperclip.paste()
                if current and current != self._last and len(current.strip()) > 0:
                    self._last = current
                    _append_entry(current)
            except Exception:
                pass
            time.sleep(_POLL_INTERVAL)

    def stop(self):
        self._running = False


_monitor: _ClipboardMonitor | None = None


def start_clipboard_monitor():
    """Start background clipboard monitoring (called once at startup)."""
    global _monitor
    if _monitor is None or not _monitor.is_alive():
        _monitor = _ClipboardMonitor()
        _monitor.start()


def _append_entry(text: str):
    """Append a clipboard entry to the history file."""
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Trim file if it's grown too large
    if HISTORY_PATH.exists():
        lines = HISTORY_PATH.read_text(encoding="utf-8").splitlines()
        if len(lines) >= MAX_ENTRIES:
            keep = lines[-(MAX_ENTRIES - 1):]
            atomic.write(HISTORY_PATH, "\n".join(keep) + "\n", encoding="utf-8")

    entry = {
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "text": text[:2000],  # cap individual entries at 2000 chars
    }
    with open(HISTORY_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def get_clipboard_history(n: int = 10) -> str:
    """Return the last n clipboard entries with timestamps."""
    if not HISTORY_PATH.exists():
        return "No clipboard history yet."

    lines = [l for l in HISTORY_PATH.read_text(encoding="utf-8").splitlines() if l.strip()]
    if not lines:
        return "Clipboard history is empty."

    recent = lines[-n:][::-1]
    parts = [f"Last {len(recent)} clipboard entries:\n"]
    for i, line in enumerate(recent, 1):
        try:
            e = json.loads(line)
            preview = e["text"].replace("\n", " ")[:120]
            if len(e["text"]) > 120:
                preview += "..."
            parts.append(f"  {i}. [{e['ts']}] {preview}")
        except Exception:
            parts.append(f"  {i}. (malformed entry)")
    return "\n".join(parts)
