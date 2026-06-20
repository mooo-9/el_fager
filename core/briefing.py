"""
Daily briefing — runs once per day at startup.

Stores the last-briefed date in data/last_briefing.json.
If already briefed today, the check exits silently without showing the overlay.
"""

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

CAIRO_TZ = ZoneInfo("Africa/Cairo")
_PATH = Path("data/last_briefing.json")


def already_briefed_today() -> bool:
    try:
        if not _PATH.exists():
            return False
        data = json.loads(_PATH.read_text(encoding="utf-8"))
        return data.get("date") == str(datetime.now(CAIRO_TZ).date())
    except Exception:
        return False


def mark_briefed_today():
    _PATH.write_text(
        json.dumps({"date": str(datetime.now(CAIRO_TZ).date())}),
        encoding="utf-8",
    )


def get_briefing_prompt() -> str:
    h = datetime.now(CAIRO_TZ).hour
    if h < 12:
        greeting = "Good morning"
    elif h < 17:
        greeting = "Good afternoon"
    else:
        greeting = "Good evening"
    return (
        f"{greeting} Mo! Give me my daily briefing: "
        "check Cairo weather, list my events for today, "
        "check for unread emails, and check my deadline facts from memory. "
        "Keep it short — 3-5 spoken sentences covering all four."
    )
