"""Tests for AutonomousTaskManager and autonomous_task_tool."""
import json
from datetime import datetime, timedelta

import pytest


def _make_manager(tmp_path, monkeypatch):
    import core.autonomous_tasks as at
    monkeypatch.setattr(at, "_TASKS_PATH", tmp_path / "tasks.json")
    return at.AutonomousTaskManager()


class TestAutonomousTaskManager:
    def test_add_creates_pending_task(self, tmp_path, monkeypatch):
        mgr = _make_manager(tmp_path, monkeypatch)
        task = mgr.add("Research Python ORMs")
        assert task["status"] == "pending"
        assert task["description"] == "Research Python ORMs"
        assert task["run_at"] is None
        assert len(task["id"]) == 8

    def test_add_with_delay(self, tmp_path, monkeypatch):
        mgr = _make_manager(tmp_path, monkeypatch)
        task = mgr.add("Check NVDA RSI", delay_hours=2.0)
        assert task["run_at"] is not None
        run_dt = datetime.fromisoformat(task["run_at"])
        diff = (run_dt - datetime.now()).total_seconds()
        assert 7100 < diff < 7300  # roughly 2 hours

    def test_get_due_returns_tasks_with_no_run_at(self, tmp_path, monkeypatch):
        mgr = _make_manager(tmp_path, monkeypatch)
        mgr.add("Task A")
        due = mgr.get_due()
        assert len(due) == 1
        assert due[0]["description"] == "Task A"

    def test_get_due_returns_past_run_at(self, tmp_path, monkeypatch):
        mgr = _make_manager(tmp_path, monkeypatch)
        past = (datetime.now() - timedelta(hours=1)).isoformat()
        mgr.add("Past task", delay_hours=0)
        # Override run_at directly
        tasks = mgr._load()
        tasks[0]["run_at"] = past
        mgr._save(tasks)
        due = mgr.get_due()
        assert len(due) == 1

    def test_get_due_skips_future_tasks(self, tmp_path, monkeypatch):
        mgr = _make_manager(tmp_path, monkeypatch)
        mgr.add("Future task", delay_hours=10.0)
        assert mgr.get_due() == []

    def test_complete_marks_done(self, tmp_path, monkeypatch):
        mgr = _make_manager(tmp_path, monkeypatch)
        task = mgr.add("Do something")
        mgr.mark_running(task["id"])
        mgr.complete(task["id"], "All done.")
        tasks = mgr.list_all()
        assert tasks[0]["status"] == "done"
        assert tasks[0]["result"] == "All done."

    def test_recurring_task_resets_to_pending(self, tmp_path, monkeypatch):
        mgr = _make_manager(tmp_path, monkeypatch)
        task = mgr.add("Daily NVDA check", recurring_hours=24.0)
        mgr.mark_running(task["id"])
        mgr.complete(task["id"], "RSI is 45.")
        tasks = mgr.list_all()
        t = tasks[0]
        assert t["status"] == "pending"
        assert t["run_at"] is not None
        # run_at should be ~24h from now
        diff = (datetime.fromisoformat(t["run_at"]) - datetime.now()).total_seconds()
        assert 86000 < diff < 87000

    def test_fail_marks_failed(self, tmp_path, monkeypatch):
        mgr = _make_manager(tmp_path, monkeypatch)
        task = mgr.add("Failing task")
        mgr.fail(task["id"], "Network error")
        tasks = mgr.list_all()
        assert tasks[0]["status"] == "failed"
        assert "Network error" in tasks[0]["result"]

    def test_delete_removes_task(self, tmp_path, monkeypatch):
        mgr = _make_manager(tmp_path, monkeypatch)
        task = mgr.add("Temp task")
        assert mgr.delete(task["id"]) is True
        assert mgr.list_all() == []

    def test_delete_returns_false_for_missing(self, tmp_path, monkeypatch):
        mgr = _make_manager(tmp_path, monkeypatch)
        assert mgr.delete("nonexist") is False

    def test_format_list_empty(self, tmp_path, monkeypatch):
        mgr = _make_manager(tmp_path, monkeypatch)
        assert "No autonomous tasks" in mgr.format_list()

    def test_format_list_shows_status(self, tmp_path, monkeypatch):
        mgr = _make_manager(tmp_path, monkeypatch)
        task = mgr.add("Research X")
        mgr.mark_running(task["id"])
        mgr.complete(task["id"], "Done research.")
        text = mgr.format_list()
        assert "DONE" in text
        assert "Research X" in text

    def test_get_due_skips_running_and_done(self, tmp_path, monkeypatch):
        mgr = _make_manager(tmp_path, monkeypatch)
        t1 = mgr.add("Task1")
        t2 = mgr.add("Task2")
        mgr.mark_running(t1["id"])
        mgr.complete(t2["id"], "x")
        assert mgr.get_due() == []


class TestAutonomousTaskTool:
    def test_add_returns_confirmation(self, tmp_path, monkeypatch):
        import core.autonomous_tasks as at
        monkeypatch.setattr(at, "_TASKS_PATH", tmp_path / "tasks.json")
        from tools.autonomous_task_tool import add_autonomous_task
        result = add_autonomous_task("Check NVDA RSI", delay_hours=0)
        assert "Task added" in result
        assert "Check NVDA RSI" in result

    def test_add_recurring_mentions_interval(self, tmp_path, monkeypatch):
        import core.autonomous_tasks as at
        monkeypatch.setattr(at, "_TASKS_PATH", tmp_path / "tasks.json")
        from tools.autonomous_task_tool import add_autonomous_task
        result = add_autonomous_task("Daily brief", recurring_hours=24)
        assert "24h" in result or "Recurring" in result

    def test_list_reflects_added_tasks(self, tmp_path, monkeypatch):
        import core.autonomous_tasks as at
        monkeypatch.setattr(at, "_TASKS_PATH", tmp_path / "tasks.json")
        from tools.autonomous_task_tool import add_autonomous_task, list_autonomous_tasks
        add_autonomous_task("Research Python")
        text = list_autonomous_tasks()
        assert "Research Python" in text

    def test_delete_by_id(self, tmp_path, monkeypatch):
        import core.autonomous_tasks as at
        monkeypatch.setattr(at, "_TASKS_PATH", tmp_path / "tasks.json")
        from tools.autonomous_task_tool import add_autonomous_task, delete_autonomous_task
        result = add_autonomous_task("Temp task")
        task_id = result.split("id=")[1].split(")")[0]
        del_result = delete_autonomous_task(task_id)
        assert "removed" in del_result.lower()
