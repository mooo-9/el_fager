"""Clicking the desktop icon while El Fager is already running.

main.py holds a single-instance mutex, and a second launch used to find it,
raise a toast saying "Already running. Check the system tray.", and exit. The
shortcut runs pythonw, so there is no console either — from Mo's side the icon
simply did nothing, and the app he was trying to open never appeared.

A second launch now signals a named event that the running instance waits on,
and that instance brings its overlay forward. The second process still exits;
the difference is that it hands off first.
"""
import ctypes
import threading
import time

import pytest

import main


@pytest.fixture(autouse=True)
def unique_event_name(monkeypatch):
    """Never touch the real instance's event while the tests run."""
    monkeypatch.setattr(main, "_SHOW_EVENT_NAME",
                        f"ElFagerShowRequestedTest{time.monotonic_ns()}")


class _Signaler:
    """Stands in for HotkeySignaler.second_launch."""

    def __init__(self):
        self.fired = threading.Event()
        self.count = 0

    @property
    def second_launch(self):
        return self

    def emit(self):
        self.count += 1
        self.fired.set()


class TestHandoff:
    def test_signalling_with_nobody_listening_reports_failure(self):
        # The mutex is held but no watcher exists — an older build, or a
        # process wedged mid-shutdown. main.py falls back to a toast, so this
        # must answer honestly rather than pretend it was delivered.
        assert main._signal_running_instance() is False

    def test_a_watcher_receives_the_signal(self):
        signaler = _Signaler()
        main._watch_for_second_launch(signaler)
        time.sleep(0.1)                       # let the wait thread start

        assert main._signal_running_instance() is True
        assert signaler.fired.wait(timeout=3.0), \
            "the running instance never heard the second launch"

    def test_each_launch_wakes_the_watcher_once(self):
        # Auto-reset: three clicks are three separate summons, not one.
        signaler = _Signaler()
        main._watch_for_second_launch(signaler)
        time.sleep(0.1)
        for _ in range(3):
            assert main._signal_running_instance() is True
            time.sleep(0.15)
        assert signaler.count == 3, f"expected 3 wake-ups, got {signaler.count}"

    def test_the_watcher_does_not_block_startup(self):
        signaler = _Signaler()
        started = time.monotonic()
        main._watch_for_second_launch(signaler)
        assert time.monotonic() - started < 0.5, \
            "the watcher blocked the main thread instead of running as a daemon"

    def test_the_watcher_thread_is_a_daemon_so_quit_still_works(self):
        before = {t.ident for t in threading.enumerate()}
        main._watch_for_second_launch(_Signaler())
        time.sleep(0.1)
        new = [t for t in threading.enumerate() if t.ident not in before]
        assert new, "no watcher thread was started"
        assert all(t.daemon for t in new), \
            "a non-daemon watcher would keep the process alive after Quit"


class TestTheEventItself:
    def test_the_name_is_stable_so_both_processes_agree(self):
        # Both sides look the event up by name; if they ever disagree the
        # handoff silently stops working and the icon looks broken again.
        assert isinstance(main._SHOW_EVENT_NAME, str)
        assert main._SHOW_EVENT_NAME

    def test_opening_a_missing_event_does_not_raise(self, monkeypatch):
        monkeypatch.setattr(main, "_SHOW_EVENT_NAME", "ElFagerDefinitelyNotThere")
        assert main._signal_running_instance() is False

    def test_a_failed_event_creation_leaves_startup_alone(self, monkeypatch):
        # If CreateEventW fails, the app must still boot — losing the handoff
        # is a nuisance, refusing to start is not acceptable.
        real = ctypes.windll.kernel32.CreateEventW
        monkeypatch.setattr(ctypes.windll.kernel32, "CreateEventW",
                            lambda *a: 0)
        try:
            main._watch_for_second_launch(_Signaler())      # must not raise
        finally:
            monkeypatch.setattr(ctypes.windll.kernel32, "CreateEventW", real)
