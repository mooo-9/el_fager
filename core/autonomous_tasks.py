"""
AutonomousTaskManager — persistent store for tasks El Fager executes on its own.

Tasks are stored in data/autonomous_tasks.json.
The ProactiveEngine picks up pending tasks every 60 seconds and executes them
by calling brain.chat(description), then speaks the result to Mo.
"""
import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from core import atomic

_TASKS_PATH = Path("data/autonomous_tasks.json")


class AutonomousTaskManager:
    def add(
        self,
        description: str,
        delay_hours: float = 0.0,
        recurring_hours: float = 0.0,
    ) -> dict:
        """
        Create a new task.
        delay_hours=0  → run on the next ProactiveEngine check cycle (within 60s).
        recurring_hours > 0 → re-queue automatically after each completion.
        """
        run_at = None
        if delay_hours > 0:
            run_at = (datetime.now() + timedelta(hours=delay_hours)).isoformat()

        task: dict = {
            "id": str(uuid.uuid4())[:8],
            "description": description,
            "status": "pending",
            "recurring_hours": recurring_hours,
            "run_at": run_at,
            "created_at": datetime.now().isoformat(),
            "completed_at": None,
            "result": None,
        }
        tasks = self._load()
        tasks.append(task)
        self._save(tasks)
        return task

    def list_all(self) -> list[dict]:
        return self._load()

    def get_due(self) -> list[dict]:
        """Return tasks whose run_at has passed, or tasks with no run_at."""
        now = datetime.now()
        result = []
        for t in self._load():
            if t["status"] != "pending":
                continue
            run_at = t.get("run_at")
            if run_at is None:
                result.append(t)
            else:
                try:
                    if datetime.fromisoformat(run_at) <= now:
                        result.append(t)
                except Exception:
                    result.append(t)
        return result

    def mark_running(self, task_id: str) -> None:
        self._update(task_id, {"status": "running"})

    def complete(self, task_id: str, result: str) -> None:
        tasks = self._load()
        for t in tasks:
            if t["id"] != task_id:
                continue
            t["result"] = result[:500]
            t["completed_at"] = datetime.now().isoformat()
            hours = t.get("recurring_hours", 0)
            if hours and hours > 0:
                t["status"] = "pending"
                t["run_at"] = (
                    datetime.now() + timedelta(hours=hours)
                ).isoformat()
            else:
                t["status"] = "done"
        self._save(tasks)

    def fail(self, task_id: str, error: str) -> None:
        self._update(task_id, {
            "status": "failed",
            "result": f"Error: {error[:200]}",
            "completed_at": datetime.now().isoformat(),
        })

    def delete(self, task_id: str) -> bool:
        tasks = self._load()
        before = len(tasks)
        tasks = [t for t in tasks if t["id"] != task_id]
        if len(tasks) < before:
            self._save(tasks)
            return True
        return False

    def format_list(self) -> str:
        tasks = self._load()
        if not tasks:
            return "No autonomous tasks queued."
        lines = []
        for t in tasks:
            status = t["status"].upper()
            desc = t["description"][:70]
            if t["status"] == "done":
                res = (t.get("result") or "")[:50]
                lines.append(f"[{status}] {desc} => {res}")
            elif t["status"] == "pending":
                run_at = t.get("run_at")
                when = run_at[:16] if run_at else "next check"
                lines.append(f"[{status}] {desc}  (due {when})")
            else:
                lines.append(f"[{status}] {desc}")
        return "\n".join(lines)

    # ── Persistence ────────────────────────────────────────────────────────────

    def _load(self) -> list[dict]:
        if not _TASKS_PATH.exists():
            return []
        try:
            return json.loads(_TASKS_PATH.read_text(encoding="utf-8"))
        except Exception:
            return []

    def _save(self, tasks: list[dict]) -> None:
        _TASKS_PATH.parent.mkdir(parents=True, exist_ok=True)
        atomic.write(_TASKS_PATH,
            json.dumps(tasks, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def _update(self, task_id: str, fields: dict) -> None:
        tasks = self._load()
        for t in tasks:
            if t["id"] == task_id:
                t.update(fields)
        self._save(tasks)
