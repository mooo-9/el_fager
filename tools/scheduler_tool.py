"""
Scheduler tool — add, list, run, remove, pause, resume, reschedule scheduled jobs.

Natural language 'when' parsing supports:

  Recurring:
    "every day at 8am" / "daily at 8"
    "every Monday at 9" / "every Friday at 3pm"
    "every weekday at 9am" / "every weekend at 10am"
    "every hour" / "every minute"
    "every quarter hour" / "every half hour"
    "every 30 minutes" / "every 2 hours" / "every 3 days" / "every 2 weeks"
    "every other day"
    "twice a day" / "3 times a day"
    "every morning" (7am) / "every evening" (7pm) / "every night" (10pm) / "every noon"
    "on the 1st of every month" / "monthly on the 15th" / "every 1st"
    "every day except weekends" → mon-fri
    Raw 5-field cron: "0 8 * * *"

  One-shot:
    "in 30 seconds" / "in 30 minutes" / "in 2 hours" / "in 1 day"
    "tomorrow at 9am" / "tonight at 10pm"

  Arabizi shortcuts:
    "kol youm" / "kol yom" → daily
    "kol sa3a" → every hour
"""

import json
import re
from datetime import datetime, timedelta
from pathlib import Path

_WEEKDAYS = {
    "monday": "mon", "tuesday": "tue", "wednesday": "wed",
    "thursday": "thu", "friday": "fri", "saturday": "sat", "sunday": "sun",
}

_TIME_WORDS = {
    "midnight": (0, 0),
    "noon": (12, 0),
    "lunchtime": (12, 0),
    "morning": (7, 0),
    "evening": (19, 0),
    "night": (22, 0),
    "dusk": (19, 0),
    "dawn": (6, 0),
    "sunset": (18, 0),
    "sunrise": (6, 30),
}

# Ordinal string → int
_ORDINALS = {
    "1st": 1, "first": 1, "2nd": 2, "second": 2, "3rd": 3, "third": 3,
    "4th": 4, "fourth": 4, "5th": 5, "fifth": 5, "6th": 6, "seventh": 7,
    "8th": 8, "9th": 9, "10th": 10, "11th": 11, "12th": 12, "13th": 13,
    "14th": 14, "15th": 15, "16th": 16, "17th": 17, "18th": 18, "19th": 19,
    "20th": 20, "21st": 21, "22nd": 22, "23rd": 23, "24th": 24, "25th": 25,
    "26th": 26, "27th": 27, "28th": 28, "last": "last",
}

# Arabizi → English equivalent
_ARABIZI_MAP = {
    "kol youm": "every day at 8am",
    "kol yom": "every day at 8am",
    "kol sa3a": "every hour",
    "kol sa3eten": "every 2 hours",
    "kol nuss sa3a": "every 30 minutes",
    "kol yom el sob7": "every morning",
    "kol leila": "every night",
}


# ──────────────────────────────────────────────────────────────────────────────
# When-string parser
# ──────────────────────────────────────────────────────────────────────────────

def _parse_hm(hour_str: str, min_str: str | None, ampm: str | None) -> tuple[int, int]:
    h = int(hour_str)
    m = int(min_str) if min_str else 0
    if ampm:
        ampm = ampm.lower()
        if ampm == "pm" and h != 12:
            h += 12
        elif ampm == "am" and h == 12:
            h = 0
    return h, m


def _parse_when(when: str) -> dict | None:
    w = when.strip().lower()

    # ── Arabizi shortcuts ───────────────────────────────────────────────────
    for arabizi, english in _ARABIZI_MAP.items():
        if arabizi in w:
            w = w.replace(arabizi, english)
            break

    # ── Arabic Unicode basics ───────────────────────────────────────────────
    # كل يوم → every day at 8
    if "كل يوم" in w:
        m2 = re.search(r"الساعة\s+(\d{1,2})", w)
        h = int(m2.group(1)) if m2 else 8
        return {"type": "cron", "hour": h, "minute": 0}

    # ── Raw 5-field cron ────────────────────────────────────────────────────
    parts = w.split()
    if len(parts) == 5:
        if all(re.fullmatch(r"[\d,\-\*/]+", p) for p in parts):
            minute, hour, day, month, dow = parts
            return {"type": "cron", "minute": minute, "hour": hour,
                    "day": day, "month": month, "day_of_week": dow}

    # ── One-shot: "in N seconds/minutes/hours/days" ─────────────────────────
    m = re.search(r"\bin\s+(\d+)\s+(second|minute|hour|day)s?", w)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        delta = {"second": timedelta(seconds=n), "minute": timedelta(minutes=n),
                 "hour": timedelta(hours=n), "day": timedelta(days=n)}[unit]
        return {"type": "date", "run_date": (datetime.now() + delta).isoformat()}

    # ── One-shot: "tomorrow at Xam" ──────────────────────────────────────────
    m = re.search(r"tomorrow\s+at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", w)
    if m:
        h, mins = _parse_hm(m.group(1), m.group(2), m.group(3))
        run_at = (datetime.now().replace(hour=h, minute=mins, second=0, microsecond=0)
                  + timedelta(days=1)).isoformat()
        return {"type": "date", "run_date": run_at}

    # ── One-shot: "tonight at Xpm" ───────────────────────────────────────────
    m = re.search(r"tonight\s+at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", w)
    if m:
        h, mins = _parse_hm(m.group(1), m.group(2), m.group(3))
        return {"type": "date",
                "run_date": datetime.now().replace(hour=h, minute=mins, second=0, microsecond=0).isoformat()}

    # ── "twice a day" ────────────────────────────────────────────────────────
    if re.search(r"twice\s+a\s+day", w):
        return {"type": "interval", "hours": 12}

    # ── "N times a day" ──────────────────────────────────────────────────────
    m = re.search(r"(\d+)\s+times?\s+a\s+day", w)
    if m:
        n = int(m.group(1))
        return {"type": "interval", "hours": max(1, 24 // n)}

    # ── "every other day" ────────────────────────────────────────────────────
    if re.search(r"every\s+other\s+day", w):
        return {"type": "interval", "days": 2}

    # ── "every quarter hour" ─────────────────────────────────────────────────
    if re.search(r"every\s+quarter\s+(?:hour|hr)", w):
        return {"type": "interval", "minutes": 15}

    # ── "every half hour" ────────────────────────────────────────────────────
    if re.search(r"every\s+half\s+(?:hour|hr)", w):
        return {"type": "interval", "minutes": 30}

    # ── "every minute" ───────────────────────────────────────────────────────
    if re.search(r"every\s+minute\b", w):
        return {"type": "interval", "minutes": 1}

    # ── "every N minutes/hours/days/weeks" ───────────────────────────────────
    m = re.search(r"every\s+(\d+)\s+(second|minute|hour|day|week)s?", w)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        return {"type": "interval", **{f"{unit}s": n}}

    # ── "every hour" ─────────────────────────────────────────────────────────
    if re.search(r"every\s+hour\b", w):
        return {"type": "interval", "hours": 1}

    # ── "every day except weekends" ──────────────────────────────────────────
    if re.search(r"every\s+day\s+except\s+weekends?", w):
        m = re.search(r"at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", w)
        h, mins = _parse_hm(m.group(1), m.group(2), m.group(3)) if m else (9, 0)
        return {"type": "cron", "day_of_week": "mon-fri", "hour": h, "minute": mins}

    # ── Monthly: "on the Nth of every month" / "monthly on the Nth" / "every 1st" ─
    for ordinal_str, day_num in _ORDINALS.items():
        patterns = [
            rf"on\s+the\s+{re.escape(ordinal_str)}\s+(?:of\s+every|of\s+each)\s+month",
            rf"monthly\s+on\s+the\s+{re.escape(ordinal_str)}",
            rf"every\s+{re.escape(ordinal_str)}(?:\s+of\s+(?:the\s+)?month)?(?:\s+at\s+|$)",
        ]
        found = False
        for pat in patterns:
            if re.search(pat, w):
                found = True
                break
        if found:
            m2 = re.search(r"at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", w)
            h, mins = _parse_hm(m2.group(1), m2.group(2), m2.group(3)) if m2 else (9, 0)
            return {"type": "cron", "day": day_num, "hour": h, "minute": mins}

    # ── Named time-of-day shortcuts ──────────────────────────────────────────
    for word, (h, mins) in _TIME_WORDS.items():
        if re.search(rf"every\s+{word}\b", w):
            return {"type": "cron", "hour": h, "minute": mins}

    # ── "every day at X" / "daily at X" ─────────────────────────────────────
    m = re.search(r"(?:every\s+day|daily)\s+at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", w)
    if m:
        h, mins = _parse_hm(m.group(1), m.group(2), m.group(3))
        return {"type": "cron", "hour": h, "minute": mins}

    # ── "every <weekday> at X" ────────────────────────────────────────────────
    for day_name, day_abbr in _WEEKDAYS.items():
        m = re.search(rf"every\s+{day_name}\s+at\s+(\d{{1,2}})(?::(\d{{2}}))?\s*(am|pm)?", w)
        if m:
            h, mins = _parse_hm(m.group(1), m.group(2), m.group(3))
            return {"type": "cron", "day_of_week": day_abbr, "hour": h, "minute": mins}
        # "every Monday" without time → 9am default
        if re.search(rf"every\s+{day_name}\b", w):
            m2 = re.search(r"at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", w)
            h, mins = _parse_hm(m2.group(1), m2.group(2), m2.group(3)) if m2 else (9, 0)
            return {"type": "cron", "day_of_week": day_abbr, "hour": h, "minute": mins}

    # ── "every weekday at X" ─────────────────────────────────────────────────
    m = re.search(r"every\s+weekday\s+at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", w)
    if m:
        h, mins = _parse_hm(m.group(1), m.group(2), m.group(3))
        return {"type": "cron", "day_of_week": "mon-fri", "hour": h, "minute": mins}
    if re.search(r"every\s+weekday\b", w):
        return {"type": "cron", "day_of_week": "mon-fri", "hour": 9, "minute": 0}

    # ── "every weekend at X" ─────────────────────────────────────────────────
    m = re.search(r"every\s+weekend(?:\s+at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?)?", w)
    if m:
        h, mins = _parse_hm(m.group(1), m.group(2), m.group(3)) if m.group(1) else (10, 0)
        return {"type": "cron", "day_of_week": "sat,sun", "hour": h, "minute": mins}

    # ── "at X" alone → daily at that time ───────────────────────────────────
    m = re.search(r"^at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$", w)
    if m:
        h, mins = _parse_hm(m.group(1), m.group(2), m.group(3))
        return {"type": "cron", "hour": h, "minute": mins}

    return None


# ──────────────────────────────────────────────────────────────────────────────
# Human-readable trigger descriptions
# ──────────────────────────────────────────────────────────────────────────────

def _trigger_human(trigger: dict) -> str:
    t = trigger.get("type")

    if t == "interval":
        parts = []
        for unit in ("weeks", "days", "hours", "minutes", "seconds"):
            v = trigger.get(unit)
            if v:
                label = unit.rstrip("s") if v == 1 else unit
                parts.append(label if v == 1 else f"{v} {label}")
        return "every " + ", ".join(parts) if parts else "on an interval"

    if t == "cron":
        hour   = trigger.get("hour", 0)
        minute = trigger.get("minute", 0)
        dow    = trigger.get("day_of_week")
        day    = trigger.get("day")

        # Wildcard fields from raw cron string
        if str(hour) in ("*", "") or str(minute) in ("*",):
            return (f"cron({minute} {hour} {trigger.get('day', '*')} "
                    f"{trigger.get('month', '*')} {dow or '*'})")
        try:
            h = int(str(hour))
            m = int(str(minute))
        except (ValueError, TypeError):
            return f"cron({hour} {minute})"
        suffix = "am" if h < 12 else "pm"
        h12    = h % 12 or 12
        time_str = f"{h12}:{m:02d}{suffix}"

        if day is not None:
            day_label = "last" if str(day) == "last" else f"{day}"
            ordinal   = {"1": "1st", "2": "2nd", "3": "3rd"}.get(str(day), f"{day}th")
            return f"monthly on the {ordinal} at {time_str}"

        if dow in (None, "*", ""):
            return f"daily at {time_str}"
        if dow == "mon-fri":
            return f"every weekday at {time_str}"
        if dow in ("sat,sun", "sat-sun"):
            return f"every weekend at {time_str}"
        for full, abbr in _WEEKDAYS.items():
            if abbr == dow:
                return f"every {full.title()} at {time_str}"
        return f"every {dow} at {time_str}"

    if t == "date":
        run_at = trigger.get("run_date", "")
        try:
            dt = datetime.fromisoformat(run_at)
            return f"once at {dt.strftime('%b %d %H:%M')}"
        except Exception:
            return f"once at {run_at}"

    return str(trigger)


def _countdown(seconds: int) -> str:
    if seconds < 0:
        return "overdue"
    if seconds < 60:
        return f"in {seconds}s"
    if seconds < 3600:
        return f"in {seconds // 60}m"
    if seconds < 86400:
        h = seconds // 3600
        m = (seconds % 3600) // 60
        return f"in {h}h {m}m" if m else f"in {h}h"
    d = seconds // 86400
    h = (seconds % 86400) // 3600
    return f"in {d}d {h}h" if h else f"in {d}d"


# ──────────────────────────────────────────────────────────────────────────────
# ID / lookup helpers
# ──────────────────────────────────────────────────────────────────────────────

def _to_id(name: str) -> str:
    return re.sub(r"[^a-z0-9_-]", "-", name.lower().strip())


def _find_schedule(name: str) -> dict | None:
    from core.scheduler import _load_schedules
    job_id = _to_id(name)
    schedules = _load_schedules()
    return next(
        (s for s in schedules if s["id"] == job_id or s["name"].lower() == name.lower()),
        None,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Public tool functions
# ──────────────────────────────────────────────────────────────────────────────

def add_schedule(
    name: str,
    when: str,
    tool_name: str | None = None,
    args: dict | None = None,
    macro_name: str | None = None,
    description: str | None = None,
    run_on_add: bool = False,
) -> str:
    """
    Schedule a recurring or one-shot task.

    Args:
        name:        Human-readable name (e.g. "Morning Briefing")
        when:        Natural language time spec (see module docstring)
        tool_name:   Tool to call on each fire (mutually exclusive with macro_name)
        args:        Arguments dict for the tool
        macro_name:  Macro to run on each fire (mutually exclusive with tool_name)
        description: Optional note about what this schedule does
        run_on_add:  If True, also runs the task immediately when created
    """
    trigger = _parse_when(when)
    if trigger is None:
        return (
            f"Couldn't parse '{when}'.\n"
            "Try: 'every day at 8am', 'every Monday at 9pm', 'every 30 minutes',\n"
            "'every quarter hour', 'every other day', 'on the 1st of every month',\n"
            "'in 2 hours', 'tomorrow at 9am', 'every morning', or a cron string '0 8 * * *'."
        )

    if not tool_name and not macro_name:
        return "Specify either tool_name (e.g. 'get_weather') or macro_name (e.g. 'morning_routine')."

    action = (
        {"type": "macro", "name": macro_name}
        if macro_name
        else {"type": "tool", "tool": tool_name, "args": args or {}}
    )

    job_id   = _to_id(name)
    existing = _find_schedule(name)

    job_dict: dict = {
        "id":         job_id,
        "name":       name,
        "trigger":    trigger,
        "action":     action,
        "enabled":    True,
        "created_at": datetime.now().isoformat(),
    }
    if description:
        job_dict["description"] = description

    from core.scheduler import get_instance, _save_schedules, _load_schedules
    sched = get_instance()

    if sched:
        sched.add_job(job_dict)
    else:
        schedules = _load_schedules()
        schedules = [s for s in schedules if s.get("id") != job_id]
        schedules.append(job_dict)
        _save_schedules(schedules)

    trigger_str = _trigger_human(trigger)
    action_str  = f"run macro '{macro_name}'" if macro_name else f"call {tool_name}"
    replaced    = "Updated existing" if existing else "Scheduled"
    result      = f"{replaced} '{name}' — {trigger_str} — {action_str}."

    if run_on_add:
        run_result = run_now(name)
        result += f"\n(Ran immediately: {run_result})"

    return result


def list_schedules(filter: str = "all") -> str:
    """
    List schedules.

    Args:
        filter: "all" (default), "active", or "paused"
    """
    from core.scheduler import get_instance
    sched = get_instance()
    jobs  = sched.list_job_info() if sched else []

    if not jobs:
        from core.scheduler import _load_schedules
        jobs = [dict(s) for s in _load_schedules()]

    if filter == "active":
        jobs = [j for j in jobs if j.get("enabled", True)]
    elif filter == "paused":
        jobs = [j for j in jobs if not j.get("enabled", True)]

    if not jobs:
        label = f" {filter}" if filter != "all" else ""
        return f"No{label} schedules."

    active_count = sum(1 for j in jobs if j.get("enabled", True))
    paused_count = len(jobs) - active_count
    lines        = [f"Schedules ({active_count} active, {paused_count} paused):"]

    for j in jobs:
        enabled = j.get("enabled", True)
        status  = "active" if enabled else "paused"
        action  = j.get("action", {})
        what = (
            f"macro '{action.get('name')}'"
            if action.get("type") == "macro"
            else f"call {action.get('tool', '?')}"
        )
        trigger_str = _trigger_human(j.get("trigger", {}))
        next_secs   = j.get("next_run_in_seconds")
        next_str    = f" — {_countdown(next_secs)}" if (next_secs is not None and enabled) else ""
        desc        = f"  ({j['description']})" if j.get("description") else ""
        lines.append(f"  • {j['name']} — {trigger_str} — {what}{next_str} [{status}]{desc}")

    return "\n".join(lines)


def get_schedule(name: str) -> str:
    from core.scheduler import get_instance
    sched = get_instance()

    match = _find_schedule(name)
    if not match:
        return f"No schedule named '{name}'."

    action = match.get("action", {})
    what = (
        f"macro '{action.get('name')}'"
        if action.get("type") == "macro"
        else f"tool '{action.get('tool')}' with args {action.get('args', {})}"
    )

    lines = [
        f"Schedule: {match['name']}",
        f"  Trigger: {_trigger_human(match.get('trigger', {}))}",
        f"  Action: {what}",
        f"  Status: {'active' if match.get('enabled', True) else 'paused'}",
        f"  Created: {match.get('created_at', '?')[:16]}",
    ]
    if match.get("description"):
        lines.insert(1, f"  Note: {match['description']}")

    if sched:
        info = sched.get_job_info(match["id"])
        if info and "next_run_in_seconds" in info:
            lines.append(f"  Next run: {_countdown(info['next_run_in_seconds'])} ({info.get('next_run', '')[:16]})")

    return "\n".join(lines)


def remove_schedule(name: str) -> str:
    match = _find_schedule(name)
    if not match:
        return f"No schedule named '{name}'."

    from core.scheduler import get_instance
    sched = get_instance()
    if sched:
        sched.remove_job(match["id"])
    else:
        from core.scheduler import _load_schedules, _save_schedules
        _save_schedules([s for s in _load_schedules() if s["id"] != match["id"]])

    return f"Removed schedule '{match['name']}'."


def pause_schedule(name: str) -> str:
    match = _find_schedule(name)
    if not match:
        return f"No schedule named '{name}'."

    from core.scheduler import get_instance
    sched = get_instance()
    if sched:
        sched.pause_job(match["id"])
    else:
        from core.scheduler import _load_schedules, _save_schedules
        schedules = _load_schedules()
        for s in schedules:
            if s["id"] == match["id"]:
                s["enabled"] = False
        _save_schedules(schedules)

    return f"Paused '{match['name']}'. Use resume_schedule to re-enable."


def resume_schedule(name: str) -> str:
    match = _find_schedule(name)
    if not match:
        return f"No schedule named '{name}'."

    from core.scheduler import get_instance
    sched = get_instance()
    if sched:
        sched.resume_job(match["id"])
    else:
        from core.scheduler import _load_schedules, _save_schedules
        schedules = _load_schedules()
        for s in schedules:
            if s["id"] == match["id"]:
                s["enabled"] = True
        _save_schedules(schedules)

    return f"Resumed '{match['name']}'."


def run_now(name: str) -> str:
    """Trigger a scheduled job immediately and return its result."""
    match = _find_schedule(name)
    if not match:
        return f"No schedule named '{name}'."

    from core.scheduler import get_instance
    sched = get_instance()
    if sched:
        return sched.run_now(match["id"])

    # Fallback: dispatch directly without live scheduler
    action = match.get("action", {})
    if action.get("type") == "macro":
        from tools.macro_tool import run_macro
        result = run_macro(action["name"])
    else:
        from core.scheduler import _dispatch_scheduled_tool
        result = _dispatch_scheduled_tool(action.get("tool", ""), action.get("args", {}))
    return result or f"'{name}' ran with no output."


def reschedule(name: str, when: str) -> str:
    """Change the trigger for an existing schedule without recreating it."""
    match = _find_schedule(name)
    if not match:
        return f"No schedule named '{name}'."

    trigger = _parse_when(when)
    if trigger is None:
        return (
            f"Couldn't parse '{when}'.\n"
            "Try: 'every day at 9am', 'every 2 hours', 'on the 1st of every month', etc."
        )

    from core.scheduler import get_instance
    sched = get_instance()
    if sched:
        ok = sched.reschedule_job(match["id"], trigger)
        if not ok:
            return f"Failed to reschedule '{name}'."
    else:
        from core.scheduler import _load_schedules, _save_schedules
        schedules = _load_schedules()
        for s in schedules:
            if s["id"] == match["id"]:
                s["trigger"] = trigger
        _save_schedules(schedules)

    return f"Rescheduled '{name}' — now {_trigger_human(trigger)}."


def pause_all_schedules() -> str:
    """Pause every active schedule."""
    from core.scheduler import get_instance
    sched = get_instance()
    if sched:
        count = sched.pause_all()
        return f"Paused {count} schedule(s). Use resume_all_schedules to re-enable."
    # No live scheduler
    from core.scheduler import _load_schedules, _save_schedules
    schedules = _load_schedules()
    count = 0
    for s in schedules:
        if s.get("enabled", True):
            s["enabled"] = False
            count += 1
    _save_schedules(schedules)
    return f"Paused {count} schedule(s) in storage (scheduler not running)."


def resume_all_schedules() -> str:
    """Resume every paused schedule."""
    from core.scheduler import get_instance
    sched = get_instance()
    if sched:
        count = sched.resume_all()
        return f"Resumed {count} schedule(s)."
    from core.scheduler import _load_schedules, _save_schedules
    schedules = _load_schedules()
    count = 0
    for s in schedules:
        if not s.get("enabled", True):
            s["enabled"] = True
            count += 1
    _save_schedules(schedules)
    return f"Resumed {count} schedule(s) in storage (scheduler not running)."


def scheduler_status() -> str:
    """Return APScheduler health — running, job count, timezone."""
    from core.scheduler import get_instance, _TZ
    sched = get_instance()

    if sched is None:
        return "Scheduler not initialized (El Fager may still be starting up)."

    info = sched.status()
    if not info["available"]:
        return "APScheduler not installed. Run: pip install apscheduler>=3.10.0"
    if not info["running"]:
        return "Scheduler initialized but not started."

    lines = [
        f"Scheduler: running ({info['timezone']})",
        f"  Jobs registered (live): {info['jobs_registered']}",
        f"  Jobs on disk: {info['jobs_total']}",
    ]
    if info.get("start_time"):
        try:
            from datetime import datetime
            started = datetime.fromisoformat(info["start_time"])
            uptime  = int((datetime.now() - started).total_seconds() / 60)
            lines.append(f"  Uptime: {uptime}m")
        except Exception:
            pass
    return "\n".join(lines)


def job_history(name: str, n: int = 10) -> str:
    """Show history for one specific scheduled job."""
    match = _find_schedule(name)
    if not match:
        return f"No schedule named '{name}'."

    from core.scheduler import get_instance
    sched = get_instance()
    entries = sched.get_history(n, job_id=match["id"]) if sched else []

    if not entries:
        # Direct file read fallback
        from core.scheduler import _HISTORY_FILE
        if not _HISTORY_FILE.exists():
            return f"No history for '{name}' yet."
        entries_all = []
        for line in reversed(_HISTORY_FILE.read_text(encoding="utf-8").splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
                if e.get("job_id") == match["id"]:
                    entries_all.append(e)
                    if len(entries_all) >= n:
                        break
            except Exception:
                pass
        entries = entries_all

    if not entries:
        return f"No history for '{name}' yet."

    ok_count   = sum(1 for e in entries if e.get("status") == "ok")
    avg_ms     = int(sum(e.get("duration_ms", 0) for e in entries) / len(entries))
    success_pct = int(100 * ok_count / len(entries))

    lines = [
        f"History for '{name}' (last {len(entries)} runs — {success_pct}% success, avg {avg_ms}ms):"
    ]
    for e in entries:
        ts     = e.get("fired_at", "")[:16]
        status = "OK" if e.get("status") == "ok" else "FAIL"
        ms     = e.get("duration_ms", 0)
        preview = e.get("result_preview", "")
        preview_str = f" — {preview[:60]}…" if preview else ""
        lines.append(f"  [{status}] {ts}  {ms}ms{preview_str}")

    return "\n".join(lines)


def schedule_history(n: int = 10) -> str:
    """Show the last N firing events across all scheduled jobs."""
    from core.scheduler import get_instance
    sched   = get_instance()
    entries = sched.get_history(n) if sched else []

    if not entries:
        from core.scheduler import _HISTORY_FILE
        if not _HISTORY_FILE.exists():
            return "No schedule history yet."
        raw = []
        for line in reversed(_HISTORY_FILE.read_text(encoding="utf-8").splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                raw.append(json.loads(line))
                if len(raw) >= n:
                    break
            except Exception:
                pass
        entries = raw

    if not entries:
        return "No schedule history yet."

    lines = [f"Last {len(entries)} scheduled runs:"]
    for e in entries:
        ts     = e.get("fired_at", "")[:16]
        status = "OK" if e.get("status") == "ok" else "FAIL"
        ms     = e.get("duration_ms", 0)
        lines.append(f"  [{status}] {ts}  {e.get('job_name', '?')} — {ms}ms")
    return "\n".join(lines)


def schedule_stats() -> str:
    """Aggregate stats across all schedule history: total runs, success rate, top jobs."""
    from core.scheduler import get_instance
    sched = get_instance()
    if sched:
        stats = sched.history_stats()
    else:
        from core.scheduler import _HISTORY_FILE
        stats = {}
        if _HISTORY_FILE.exists():
            for line in _HISTORY_FILE.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    e   = json.loads(line)
                    jid = e.get("job_id", "?")
                    if jid not in stats:
                        stats[jid] = {"name": e.get("job_name", jid), "runs": 0, "errors": 0, "total_ms": 0}
                    stats[jid]["runs"]     += 1
                    stats[jid]["errors"]   += (0 if e.get("status") == "ok" else 1)
                    stats[jid]["total_ms"] += e.get("duration_ms", 0)
                except Exception:
                    pass

    if not stats:
        return "No schedule history yet."

    total_runs   = sum(v["runs"] for v in stats.values())
    total_errors = sum(v["errors"] for v in stats.values())
    success_pct  = int(100 * (total_runs - total_errors) / total_runs) if total_runs else 0

    lines = [
        f"Schedule stats: {total_runs} total runs, {success_pct}% success across {len(stats)} job(s).",
    ]
    sorted_jobs = sorted(stats.values(), key=lambda x: x["runs"], reverse=True)
    lines.append("  Top jobs by run count:")
    for j in sorted_jobs[:5]:
        avg_ms = int(j["total_ms"] / j["runs"]) if j["runs"] else 0
        err    = j["errors"]
        lines.append(f"    • {j['name']} — {j['runs']} runs, {err} errors, avg {avg_ms}ms")

    return "\n".join(lines)


def clear_history() -> str:
    """Wipe all schedule history (data/schedule_history.jsonl)."""
    from core.scheduler import _HISTORY_FILE
    if not _HISTORY_FILE.exists():
        return "Schedule history is already empty."
    _HISTORY_FILE.write_text("", encoding="utf-8")
    return "Schedule history cleared."
