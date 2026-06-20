"""
Default schedules seeded on first run.

Called once from main.py when data/schedules.json is empty.
Mo can modify or delete any of these via El Fager's scheduler tools.
"""

_DEFAULT_SCHEDULES = [
    # Morning briefing — every day at 7:30am
    {
        "id": "default-morning-briefing",
        "name": "Morning Briefing",
        "trigger": {"type": "cron", "hour": 7, "minute": 30},
        "action": {"type": "macro", "name": "morning_routine"},
        "enabled": True,
        "description": "Daily morning briefing — weather, calendar, emails",
    },
    # Evening wind-down — every day at 9:30pm
    {
        "id": "default-evening-winddown",
        "name": "Evening Wind-Down",
        "trigger": {"type": "cron", "hour": 21, "minute": 30},
        "action": {"type": "macro", "name": "night_routine"},
        "enabled": True,
        "description": "Evening recap — journal stats, expenses, lights",
    },
    # Weekly report — every Friday at 6pm
    {
        "id": "default-weekly-report",
        "name": "Weekly Report",
        "trigger": {"type": "cron", "day_of_week": "fri", "hour": 18, "minute": 0},
        "action": {"type": "tool", "tool": "weekly_report", "args": {}},
        "enabled": True,
        "description": "Weekly spending + journal + productivity summary",
    },
]


def seed_default_schedules() -> None:
    """
    Write default schedules to disk if the schedules file is empty.
    Called once at startup before the scheduler starts.
    """
    from datetime import datetime
    from core.scheduler import _load_schedules, _save_schedules

    existing = _load_schedules()
    if existing:
        return          # Mo already has schedules — don't overwrite

    schedules = []
    now_iso = datetime.now().isoformat()
    for s in _DEFAULT_SCHEDULES:
        schedules.append({**s, "created_at": now_iso})

    _save_schedules(schedules)
    print(f"[Defaults] Seeded {len(schedules)} default schedule(s).")
