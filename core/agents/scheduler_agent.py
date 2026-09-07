"""
Chronos -- El Fager's timekeeper.

Owns the calendar, reminders, recurring schedules, and focus blocks. Wraps
tools/calendar_tool.py, reminder_tool.py, scheduler_tool.py and focus_tool.py.

Safety: deleting an event, removing a schedule, and switching on focus mode
(which edits the hosts file to block sites) are in confirm_before, so an
unattended Chronos can plan and report but not tear anything down.
"""
from core.agents.base_agent import BaseAgent
from core.agents.tool_loop import run_tool_loop, tool

DESTRUCTIVE_TOOLS = (
    "confirm_delete_event",
    "remove_schedule",
    "enable_focus_mode",
)

_SYSTEM = """\
You are Chronos, El Fager's scheduling agent, working for Mo.

Check what is already on the calendar before adding to it. Dates accept natural
language: 'today', 'tomorrow', 'Monday', '3 days ago', or YYYY-MM-DD.

delete_event only STAGES a deletion; confirm_delete_event is what removes it.
Never confirm a deletion Mo did not ask for.

If a tool you need is unavailable, you are working unattended: say exactly what
you would have changed and leave it for Mo. Do not claim you changed it.

Report what you actually did in two or three sentences. Plain English, no
markdown, no emoji."""


class SchedulerAgent(BaseAgent):
    def __init__(self, allow_side_effects: bool = True):
        self._allow_side_effects = allow_side_effects

    @property
    def name(self) -> str:
        return "scheduler"

    @property
    def description(self) -> str:
        return "Calendar, reminders, recurring schedules, and focus blocks."

    def run(self, task: str) -> str:
        tools, dispatch = self._toolset()
        return run_tool_loop("scheduler_agent", _SYSTEM, tools, dispatch, task)

    def _toolset(self) -> tuple[list[dict], dict]:
        from tools import calendar_tool as cal
        from tools import focus_tool as fo
        from tools import reminder_tool as rem
        from tools import scheduler_tool as sch

        schemas = [
            tool("list_events", "List calendar events for a time range.",
                 {"time_range": ("string", "'today', 'tomorrow', 'this week', a weekday, or YYYY-MM-DD."),
                  "max_results": ("integer", "Max events, default 10.")}),
            tool("create_event", "Create a calendar event.",
                 {"title": ("string", "Event title."),
                  "date": ("string", "Date in natural language or YYYY-MM-DD."),
                  "start_time": ("string", "Start time, e.g. '3pm' or '15:00'."),
                  "duration_minutes": ("integer", "Length in minutes, default 60."),
                  "description": ("string", "Optional description."),
                  "location": ("string", "Optional location.")},
                 ["title", "date", "start_time"]),
            tool("update_event", "Change an existing event found by title keyword.",
                 {"search_term": ("string", "Keyword matching the event title."),
                  "new_title": ("string", "New title."),
                  "new_time": ("string", "New start time."),
                  "new_date": ("string", "New date."),
                  "new_duration_minutes": ("integer", "New length in minutes.")},
                 ["search_term"]),
            tool("delete_event", "STAGE deletion of an event found by title keyword. Does not delete until confirm_delete_event.",
                 {"search_term": ("string", "Keyword matching the event title.")}, ["search_term"]),
            tool("confirm_delete_event", "Actually delete the staged event."),
            tool("set_reminder", "Set a one-off reminder N minutes from now.",
                 {"message": ("string", "What to remind Mo about."),
                  "minutes": ("integer", "Minutes from now.")}, ["message", "minutes"]),
            tool("list_reminders", "List pending reminders."),
            tool("cancel_reminder", "Cancel a reminder by its 1-based index.",
                 {"index": ("integer", "Index from list_reminders.")}, ["index"]),
            tool("list_schedules", "List recurring schedules.",
                 {"filter": ("string", "'all', 'active', or 'paused'.")}),
            tool("get_schedule", "Details of one schedule.",
                 {"name": ("string", "Schedule name.")}, ["name"]),
            tool("pause_schedule", "Pause a recurring schedule.",
                 {"name": ("string", "Schedule name.")}, ["name"]),
            tool("resume_schedule", "Resume a paused schedule.",
                 {"name": ("string", "Schedule name.")}, ["name"]),
            tool("reschedule", "Change when a schedule fires.",
                 {"name": ("string", "Schedule name."),
                  "when": ("string", "Natural language time spec, e.g. 'every day at 7am'.")},
                 ["name", "when"]),
            tool("remove_schedule", "Delete a recurring schedule permanently.",
                 {"name": ("string", "Schedule name.")}, ["name"]),
            tool("enable_focus_mode", "Block distracting sites for N hours.",
                 {"hours": ("number", "How many hours, default 2.")}),
            tool("disable_focus_mode", "Lift the site block."),
        ]
        dispatch = {
            "list_events": cal.list_events,
            "create_event": cal.create_event,
            "update_event": cal.update_event,
            "delete_event": cal.delete_event,
            "confirm_delete_event": cal.confirm_delete_event,
            "set_reminder": rem.set_reminder,
            "list_reminders": rem.list_reminders,
            "cancel_reminder": rem.cancel_reminder,
            "list_schedules": sch.list_schedules,
            "get_schedule": sch.get_schedule,
            "pause_schedule": sch.pause_schedule,
            "resume_schedule": sch.resume_schedule,
            "reschedule": sch.reschedule,
            "remove_schedule": sch.remove_schedule,
            "enable_focus_mode": fo.enable_focus_mode,
            "disable_focus_mode": fo.disable_focus_mode,
        }
        if not self._allow_side_effects:
            for name in DESTRUCTIVE_TOOLS:
                dispatch.pop(name, None)
            schemas = [s for s in schemas if s["name"] not in DESTRUCTIVE_TOOLS]
        return schemas, dispatch
