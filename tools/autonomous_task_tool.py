"""
Autonomous task tools — callable by the brain for natural-language task delegation.
"""
from core.autonomous_tasks import AutonomousTaskManager


def add_autonomous_task(
    description: str,
    delay_hours: float = 0.0,
    recurring_hours: float = 0.0,
) -> str:
    """
    Queue a task for El Fager to execute autonomously.
    delay_hours=0  -> run on the next check cycle (within 60s).
    recurring_hours > 0 -> repeat automatically every N hours after completion.
    """
    mgr = AutonomousTaskManager()
    task = mgr.add(description, delay_hours=delay_hours, recurring_hours=recurring_hours)
    if recurring_hours > 0:
        return (
            f"Recurring task added (id={task['id']}): {description[:60]} -- "
            f"runs every {recurring_hours:.0f}h starting now."
        )
    when = f"in {delay_hours:.0f}h" if delay_hours > 0 else "next check"
    return f"Task added (id={task['id']}): {description[:60]} -- will run {when}."


def list_autonomous_tasks() -> str:
    """Return a formatted list of all queued autonomous tasks."""
    return AutonomousTaskManager().format_list()


def delete_autonomous_task(task_id: str) -> str:
    """Remove a task from the queue by its id (first 8 chars of UUID)."""
    ok = AutonomousTaskManager().delete(task_id)
    return f"Task {task_id} removed." if ok else f"Task {task_id} not found."
