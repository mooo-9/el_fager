"""Unit tests for watchdog.py restart-backoff logic."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import watchdog
from watchdog import RestartTracker


class TestRestartTracker:
    def test_no_crashes_no_give_up(self):
        t = RestartTracker(max_crashes=3, window_seconds=600)
        assert t.should_give_up(now=1000.0) is False

    def test_two_crashes_keeps_going(self):
        t = RestartTracker(max_crashes=3, window_seconds=600)
        t.record_crash(now=1000.0)
        t.record_crash(now=1100.0)
        assert t.should_give_up(now=1100.0) is False

    def test_three_rapid_crashes_gives_up(self):
        t = RestartTracker(max_crashes=3, window_seconds=600)
        t.record_crash(now=1000.0)
        t.record_crash(now=1100.0)
        t.record_crash(now=1200.0)
        assert t.should_give_up(now=1200.0) is True

    def test_old_crashes_fall_out_of_window(self):
        t = RestartTracker(max_crashes=3, window_seconds=600)
        t.record_crash(now=1000.0)
        t.record_crash(now=1100.0)
        t.record_crash(now=2000.0)  # first crash now 1000s old
        assert t.should_give_up(now=2000.0) is False

    def test_boundary_crash_still_counts(self):
        t = RestartTracker(max_crashes=3, window_seconds=600)
        t.record_crash(now=1000.0)
        t.record_crash(now=1300.0)
        t.record_crash(now=1600.0)  # exactly 600s after the first
        assert t.should_give_up(now=1600.0) is True


class _FakeGit:
    """Stand-in for watchdog._git driven by a {command: (ok, output)} table."""

    def __init__(self, responses: dict):
        self.responses = responses
        self.calls: list[tuple] = []

    def __call__(self, *args):
        self.calls.append(args)
        for prefix, result in self.responses.items():
            if args[:len(prefix)] == prefix:
                return result
        return True, ""


class TestDeployableCommit:
    def test_no_network_no_deploy(self, monkeypatch):
        git = _FakeGit({("fetch",): (False, "could not resolve host")})
        monkeypatch.setattr(watchdog, "_git", git)
        assert watchdog._deployable_commit() is None

    def test_already_on_the_verified_commit(self, monkeypatch):
        git = _FakeGit({("rev-parse",): (True, "abc123")})
        monkeypatch.setattr(watchdog, "_git", git)
        assert watchdog._deployable_commit() is None

    def test_returns_sha_when_ci_is_ahead(self, monkeypatch):
        git = _FakeGit({
            ("rev-parse", "origin/verified"): (True, "newsha"),
            ("rev-parse", "HEAD"): (True, "oldsha"),
        })
        monkeypatch.setattr(watchdog, "_git", git)
        assert watchdog._deployable_commit() == "newsha"


class TestDeploy:
    def test_dirty_tree_is_left_alone(self, monkeypatch):
        git = _FakeGit({("status",): (True, " M core/brain.py")})
        monkeypatch.setattr(watchdog, "_git", git)
        monkeypatch.setattr(watchdog, "_log", lambda msg: None)
        assert watchdog._deploy("newsha") is False
        assert not any(c[0] == "merge" for c in git.calls)

    def test_refuses_when_not_a_fast_forward(self, monkeypatch):
        git = _FakeGit({
            ("status",): (True, ""),
            ("rev-parse",): (True, "oldsha"),
            ("merge",): (False, "Not possible to fast-forward"),
        })
        monkeypatch.setattr(watchdog, "_git", git)
        monkeypatch.setattr(watchdog, "_log", lambda msg: None)
        assert watchdog._deploy("newsha") is False

    def test_fast_forwards_a_clean_tree(self, monkeypatch):
        git = _FakeGit({("status",): (True, ""), ("rev-parse",): (True, "oldsha")})
        monkeypatch.setattr(watchdog, "_git", git)
        monkeypatch.setattr(watchdog, "_log", lambda msg: None)
        assert watchdog._deploy("newsha") is True
        assert ("merge", "--ff-only", "newsha") in git.calls


class TestSyncDependencies:
    def test_reinstalls_when_requirements_changed(self, monkeypatch):
        git = _FakeGit({("diff",): (True, "requirements.txt")})
        monkeypatch.setattr(watchdog, "_git", git)
        monkeypatch.setattr(watchdog, "_log", lambda msg: None)
        ran = []
        monkeypatch.setattr(watchdog.subprocess, "run",
                            lambda *a, **k: ran.append(a) or None)
        watchdog._sync_dependencies("oldsha", "newsha")
        assert len(ran) == 1
        assert "pip" in ran[0][0]

    def test_skips_pip_when_requirements_untouched(self, monkeypatch):
        git = _FakeGit({("diff",): (True, "")})
        monkeypatch.setattr(watchdog, "_git", git)
        ran = []
        monkeypatch.setattr(watchdog.subprocess, "run",
                            lambda *a, **k: ran.append(a) or None)
        watchdog._sync_dependencies("oldsha", "newsha")
        assert ran == []
