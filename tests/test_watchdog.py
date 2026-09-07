"""Unit tests for watchdog.py exit classification and restart-backoff logic."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from watchdog import RestartTracker, classify_exit


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


class TestClassifyExit:
    def test_clean_exit_is_a_user_quit(self):
        # Tray menu -> Quit: the watchdog must not resurrect El Fager.
        assert classify_exit(0) == "quit"

    def test_exit_three_is_the_single_instance_mutex(self):
        assert classify_exit(3) == "already_running"

    def test_nonzero_exit_is_a_crash(self):
        assert classify_exit(1) == "crash"

    def test_negative_exit_is_a_crash(self):
        # Killed by a signal / unhandled Windows exception.
        assert classify_exit(-1) == "crash"
