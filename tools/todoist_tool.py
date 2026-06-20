"""
Todoist tool — Phase 4C.

Requires TODOIST_TOKEN in .env.
Setup: todoist.com/app/settings/integrations → API token → copy to .env.

Filter syntax examples:
  "today"        — tasks due today
  "overdue"      — overdue tasks
  "p1"           — urgent priority tasks
  "#Project"     — tasks in a project named Project
  "no date"      — tasks with no due date
"""

import os

from dotenv import load_dotenv
load_dotenv()

TODOIST_AVAILABLE = bool(os.getenv("TODOIST_TOKEN"))
_NOT_SET_UP = (
    "[Todoist not set up — add TODOIST_TOKEN to .env. "
    "Get it from todoist.com/app/settings/integrations → API token.]"
)

_PRIORITY_LABELS = {4: "urgent", 3: "high", 2: "medium", 1: "normal"}


def _get_api():
    if not TODOIST_AVAILABLE:
        return None
    try:
        from todoist_api_python.api import TodoistAPI
        return TodoistAPI(os.getenv("TODOIST_TOKEN"))
    except Exception as e:
        print(f"[El Fager] Todoist auth failed: {e}")
        return None


def _fmt_task(task) -> str:
    priority = _PRIORITY_LABELS.get(task.priority, "normal")
    due = ""
    if task.due:
        due = f" (due: {task.due.string or task.due.date})"
    return f"[{priority}] {task.content}{due}"


def _find_task(api, search_term: str):
    """Find first task whose content contains search_term (case-insensitive)."""
    try:
        tasks = api.get_tasks()
        term = search_term.lower()
        return next((t for t in tasks if term in t.content.lower()), None)
    except Exception:
        return None


# ── Public functions ──────────────────────────────────────────────────────────

def list_tasks(filter: str = "today") -> str:
    """List tasks matching a Todoist filter."""
    if not TODOIST_AVAILABLE:
        return _NOT_SET_UP
    api = _get_api()
    if api is None:
        return "[Todoist auth failed — check TODOIST_TOKEN in .env]"
    try:
        tasks = api.get_tasks(filter=filter)
        if not tasks:
            return f"No tasks found for filter '{filter}'"
        lines = [f"{i+1}. {_fmt_task(t)}" for i, t in enumerate(tasks)]
        label = filter if filter else "all"
        return f"Tasks ({label}):\n" + "\n".join(lines)
    except Exception as e:
        return f"[Todoist error: {e}]"


def add_task(content: str, due_string: str = None, priority: int = 1) -> str:
    """
    Add a new Todoist task.
    priority: 1=normal, 2=medium, 3=high, 4=urgent
    due_string examples: "today", "tomorrow at 5pm", "next Monday"
    """
    if not TODOIST_AVAILABLE:
        return _NOT_SET_UP
    api = _get_api()
    if api is None:
        return "[Todoist auth failed — check TODOIST_TOKEN in .env]"
    try:
        kwargs = {"content": content, "priority": priority}
        if due_string:
            kwargs["due_string"] = due_string
        task = api.add_task(**kwargs)
        label = _PRIORITY_LABELS.get(priority, "normal")
        due_part = f" — due {due_string}" if due_string else ""
        return f"Added [{label}]: {content}{due_part}"
    except Exception as e:
        return f"[Todoist error: {e}]"


def complete_task(search_term: str) -> str:
    """Mark a task as done by searching its content."""
    if not TODOIST_AVAILABLE:
        return _NOT_SET_UP
    api = _get_api()
    if api is None:
        return "[Todoist auth failed — check TODOIST_TOKEN in .env]"
    try:
        task = _find_task(api, search_term)
        if task is None:
            return f"No task found matching '{search_term}'"
        api.close_task(task_id=task.id)
        return f"Done: {task.content}"
    except Exception as e:
        return f"[Todoist error: {e}]"


def delete_task(search_term: str) -> str:
    """Delete a task by searching its content."""
    if not TODOIST_AVAILABLE:
        return _NOT_SET_UP
    api = _get_api()
    if api is None:
        return "[Todoist auth failed — check TODOIST_TOKEN in .env]"
    try:
        task = _find_task(api, search_term)
        if task is None:
            return f"No task found matching '{search_term}'"
        api.delete_task(task_id=task.id)
        return f"Deleted: {task.content}"
    except Exception as e:
        return f"[Todoist error: {e}]"
