"""
RoutineImporter — turns Mo's existing daily/weekly commitments into skills.

Sources (each best-effort; a missing/unauthenticated source contributes
nothing rather than failing the import):
  • Google Calendar: a titled event on >= min_occurrences distinct days in
    the next 14 days is a recurring commitment -> "prep: <title>" skill,
    scheduled 30 minutes before the event time.
  • Gym program (data/gym_program.json): training split -> a daily
    "gym day briefing" skill scheduled in the late afternoon.

Candidates are plain dicts; import_routines() in tools/skill_tool.py turns
them into stored skills + automations. Sources are injectable for tests.
"""
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

_GYM_PROGRAM_PATH = Path("data/gym_program.json")

LOOKAHEAD_DAYS = 14
MIN_OCCURRENCES = 2
PREP_LEAD_MINUTES = 30


def _default_calendar_events() -> list[dict]:
    """Next LOOKAHEAD_DAYS of events as [{title, date, time 'HH:MM'|None}]."""
    try:
        from tools.calendar_tool import get_calendar_service
        service = get_calendar_service()
        if service is None:
            return []
        now = datetime.now().astimezone()
        result = service.events().list(
            calendarId="primary",
            timeMin=now.isoformat(),
            timeMax=(now + timedelta(days=LOOKAHEAD_DAYS)).isoformat(),
            maxResults=100,
            singleEvents=True,
            orderBy="startTime",
        ).execute()
        events = []
        for ev in result.get("items", []):
            start = ev.get("start", {})
            if "dateTime" in start:
                dt = datetime.fromisoformat(start["dateTime"])
                events.append({"title": ev.get("summary", "").strip(),
                               "date": dt.date().isoformat(),
                               "time": dt.strftime("%H:%M")})
            elif "date" in start:
                events.append({"title": ev.get("summary", "").strip(),
                               "date": start["date"], "time": None})
        return events
    except Exception:
        return []


def _default_gym_program() -> dict:
    try:
        import json
        if _GYM_PROGRAM_PATH.exists():
            return json.loads(_GYM_PROGRAM_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _prep_time(event_time: str) -> str:
    """'14:00' -> '13:30' (PREP_LEAD_MINUTES earlier, floored at 06:00)."""
    h, m = map(int, event_time.split(":"))
    total = max(h * 60 + m - PREP_LEAD_MINUTES, 6 * 60)
    return f"{total // 60:02d}:{total % 60:02d}"


class RoutineImporter:
    def __init__(self,
                 calendar_fn: Callable[[], list[dict]] | None = None,
                 gym_program_fn: Callable[[], dict] | None = None):
        self._calendar_fn = calendar_fn or _default_calendar_events
        self._gym_program_fn = gym_program_fn or _default_gym_program

    def find_candidates(self) -> list[dict]:
        """Candidate routines: {name, instructions, trigger_phrases,
        every_hours, at_time, origin}."""
        return self._calendar_candidates() + self._gym_candidates()

    def _calendar_candidates(self) -> list[dict]:
        clusters: dict[str, dict] = defaultdict(lambda: {"days": set(), "times": []})
        for ev in self._calendar_fn():
            title = ev.get("title", "")
            if not title:
                continue
            c = clusters[title.lower()]
            c["title"] = title
            c["days"].add(ev.get("date"))
            if ev.get("time"):
                c["times"].append(ev["time"])

        candidates = []
        for c in clusters.values():
            if len(c["days"]) < MIN_OCCURRENCES or not c["times"]:
                continue
            title = c["title"]
            time_ = min(c["times"])  # earliest occurrence time
            # >= 4 distinct days in 2 weeks reads as daily; otherwise weekly
            every_hours = 24 if len(c["days"]) >= 4 else 168
            candidates.append({
                "name": f"prep: {title.lower()}",
                "instructions": (
                    f"1) Check today's calendar for '{title}' and confirm its time "
                    f"and location. 2) Gather anything Mo needs for it: related "
                    f"reminders, unread emails mentioning it, and travel/weather "
                    f"if it has a location. 3) Brief Mo in under 4 sentences."
                ),
                "trigger_phrases": [f"prep for {title.lower()}"],
                "every_hours": every_hours,
                "at_time": _prep_time(time_),
                "origin": f"calendar: '{title}' on {len(c['days'])} of the next "
                          f"{LOOKAHEAD_DAYS} days",
            })
        return candidates

    def _gym_candidates(self) -> list[dict]:
        program = self._gym_program_fn()
        split = program.get("split") or {}
        if not split:
            return []
        return [{
            "name": "gym day briefing",
            "instructions": (
                "1) Check data/gym_program.json for today's session; if today "
                "is a rest day, say so and stop. 2) Otherwise tell Mo today's "
                "session and the key lifts, and mention his last logged "
                "weights for them (workout log) so he knows what to beat. "
                "Keep it under 4 sentences."
            ),
            "trigger_phrases": ["gym briefing", "what's my workout"],
            "every_hours": 24,
            "at_time": "16:30",
            "origin": f"gym program: {len(split)} training days/week",
        }]
