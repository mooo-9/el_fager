import json
from datetime import datetime, timedelta
from pathlib import Path
from core import atomic

_DATA_FILE = Path(__file__).parent.parent / "data" / "reminders.json"


def _load() -> list:
    try:
        if _DATA_FILE.exists():
            return json.loads(_DATA_FILE.read_text(encoding="utf-8"))
        return []
    except Exception:
        return []


def _save(reminders: list) -> None:
    _DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    atomic.write(_DATA_FILE,
        json.dumps(reminders, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def set_reminder(message: str, minutes: int) -> str:
    try:
        fire_at = (datetime.now() + timedelta(minutes=minutes)).isoformat()
        reminders = _load()
        reminders.append({"message": message, "fire_at": fire_at, "fired": False})
        _save(reminders)
        return f"Reminder set for {minutes} minute{'s' if minutes != 1 else ''}: {message}"
    except Exception as e:
        return f"[set_reminder failed: {e}]"


def list_reminders() -> str:
    try:
        reminders = _load()
        pending = [(i, r) for i, r in enumerate(reminders) if not r["fired"]]
        if not pending:
            return "No pending reminders."
        lines = []
        for i, r in pending:
            fire_at = datetime.fromisoformat(r["fire_at"])
            delta = fire_at - datetime.now()
            mins = int(delta.total_seconds() / 60)
            status = f"in {mins}m" if mins > 0 else "overdue"
            lines.append(f"[{i}] {r['message']} — {status}")
        return "\n".join(lines)
    except Exception as e:
        return f"[list_reminders failed: {e}]"


def cancel_reminder(index: int) -> str:
    try:
        reminders = _load()
        if index < 0 or index >= len(reminders):
            return f"No reminder at index {index}."
        msg = reminders[index]["message"]
        reminders[index]["fired"] = True
        _save(reminders)
        return f"Reminder cancelled: {msg}"
    except Exception as e:
        return f"[cancel_reminder failed: {e}]"


def fire_toast(message: str) -> None:
    try:
        from winotify import Notification
        toast = Notification(
            app_id="El Fager",
            title="El Fager Reminder",
            msg=message,
            duration="short",
        )
        toast.show()
    except Exception:
        try:
            from plyer import notification
            notification.notify(
                title="El Fager Reminder",
                message=message,
                app_name="El Fager",
                timeout=5,
            )
        except Exception as e:
            print(f"[El Fager] Toast notification failed: {e}")


def check_reminders() -> None:
    try:
        reminders = _load()
        changed = False
        now = datetime.now()
        for r in reminders:
            if not r["fired"] and datetime.fromisoformat(r["fire_at"]) <= now:
                fire_toast(r["message"])
                r["fired"] = True
                changed = True
        if changed:
            _save(reminders)
    except Exception as e:
        print(f"[El Fager] check_reminders error: {e}")
