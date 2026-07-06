"""Unit tests for core/missions.py — multi-step mission state machine."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import core.missions as mi
from core.missions import MissionManager


@pytest.fixture
def mgr(tmp_path, monkeypatch):
    monkeypatch.setattr(mi, "_MISSIONS_PATH", tmp_path / "missions.json")
    return MissionManager()


class TestCreate:
    def test_create_sets_up_steps(self, mgr):
        m = mgr.create("research brokers", ["find brokers", "compare fees",
                                            "write summary"])
        assert m["status"] == "in_progress"
        assert len(m["steps"]) == 3
        assert all(s["status"] == "pending" for s in m["steps"])
        assert m["steps"][0]["n"] == 1

    def test_create_requires_steps(self, mgr):
        with pytest.raises(ValueError):
            mgr.create("goal", [])

    def test_only_one_active_mission(self, mgr):
        mgr.create("first", ["a"])
        with pytest.raises(ValueError):
            mgr.create("second", ["b"])

    def test_persistence(self, mgr, tmp_path, monkeypatch):
        mgr.create("goal", ["a", "b"])
        fresh = MissionManager()
        assert fresh.get_active()["goal"] == "goal"


class TestExecutionFlow:
    def test_next_step_returns_first_pending(self, mgr):
        mgr.create("g", ["one", "two"])
        step = mgr.next_step()
        assert step["n"] == 1 and step["description"] == "one"

    def test_complete_step_advances(self, mgr):
        m = mgr.create("g", ["one", "two"])
        mgr.complete_step(m["id"], 1, "result of one")
        step = mgr.next_step()
        assert step["n"] == 2
        active = mgr.get_active()
        assert active["steps"][0]["status"] == "done"
        assert active["steps"][0]["result"] == "result of one"

    def test_completing_last_step_finishes_mission(self, mgr):
        m = mgr.create("g", ["only"])
        mgr.complete_step(m["id"], 1, "done!")
        assert mgr.get_active() is None
        assert mgr.last_finished()["status"] == "done"

    def test_first_failure_retries(self, mgr):
        m = mgr.create("g", ["fragile"])
        mgr.fail_step(m["id"], 1, "API down")
        active = mgr.get_active()
        assert active is not None
        assert active["steps"][0]["status"] == "pending"  # retry
        assert active["steps"][0]["attempts"] == 1

    def test_second_failure_blocks_mission(self, mgr):
        m = mgr.create("g", ["fragile", "never reached"])
        mgr.fail_step(m["id"], 1, "boom")
        mgr.fail_step(m["id"], 1, "boom again")
        assert mgr.get_active() is None
        finished = mgr.last_finished()
        assert finished["status"] == "blocked"
        assert "boom again" in finished["steps"][0]["result"]

    def test_completed_results_feed_context(self, mgr):
        m = mgr.create("g", ["a", "b", "c"])
        mgr.complete_step(m["id"], 1, "alpha result")
        mgr.complete_step(m["id"], 2, "beta result")
        ctx = mgr.step_context()
        assert "alpha result" in ctx and "beta result" in ctx
        assert "g" in ctx  # goal included

    def test_cancel(self, mgr):
        m = mgr.create("g", ["a"])
        assert mgr.cancel(m["id"]) is True
        assert mgr.get_active() is None
        assert mgr.last_finished()["status"] == "cancelled"

    def test_new_mission_allowed_after_finish(self, mgr):
        m = mgr.create("g", ["a"])
        mgr.complete_step(m["id"], 1, "ok")
        m2 = mgr.create("g2", ["x"])
        assert m2["goal"] == "g2"


class TestParallelGroups:
    def test_default_groups_are_sequential(self, mgr):
        mgr.create("g", ["a", "b", "c"])
        steps = mgr.next_steps()
        assert [s["n"] for s in steps] == [1]

    def test_same_group_steps_returned_together(self, mgr):
        mgr.create("g", ["a", "b", "c"], groups=[1, 1, 2])
        steps = mgr.next_steps()
        assert [s["n"] for s in steps] == [1, 2]

    def test_next_group_waits_for_current(self, mgr):
        m = mgr.create("g", ["a", "b", "c"], groups=[1, 1, 2])
        mgr.complete_step(m["id"], 1, "r1")
        # step 2 (same group) still pending -> group 2 must wait
        assert [s["n"] for s in mgr.next_steps()] == [2]
        mgr.complete_step(m["id"], 2, "r2")
        assert [s["n"] for s in mgr.next_steps()] == [3]

    def test_groups_length_mismatch_rejected(self, mgr):
        with pytest.raises(ValueError):
            mgr.create("g", ["a", "b"], groups=[1])

    def test_retry_keeps_step_in_current_group(self, mgr):
        m = mgr.create("g", ["a", "b"], groups=[1, 1])
        mgr.complete_step(m["id"], 1, "ok")
        mgr.fail_step(m["id"], 2, "boom")
        assert [s["n"] for s in mgr.next_steps()] == [2]


class TestFormatStatus:
    def test_no_mission(self, mgr):
        assert "No mission" in mgr.format_status()

    def test_progress_shown(self, mgr):
        m = mgr.create("research brokers", ["find", "compare", "summarize"])
        mgr.complete_step(m["id"], 1, "found 5 brokers")
        out = mgr.format_status()
        assert "research brokers" in out
        assert "1/3" in out or "1 of 3" in out
