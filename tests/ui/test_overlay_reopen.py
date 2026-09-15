"""Opening, closing and reopening the overlay.

The reported symptom: after a couple of open/close cycles it lags, then stops
appearing while still answering out loud. Three defects combined to produce
exactly that.

  * PipelineWorker.run() is a plain blocking function with no event loop, so
    QThread.quit() did nothing at all.
  * _hide() called quit() and then wait(2000) on the GUI thread — up to two
    seconds of frozen UI, and the worker survived it regardless.
  * _show_and_start() returned early whenever a worker was running. With an
    orphan alive from the failed hide, every subsequent open silently did
    nothing while the orphan kept the microphone: no window, audio still live.

These drive the sequence rather than the units, because each piece is
defensible alone and only the combination is broken.
"""
from unittest.mock import MagicMock

import pytest


def _overlay(qapp):
    from ui.overlay import OverlayWindow
    w = OverlayWindow(MagicMock(), MagicMock(), MagicMock(), MagicMock())
    w.set_wake_listener(None)
    return w


class _StuckWorker:
    """A worker that will not stop — the state the old code could not leave."""

    def __init__(self):
        self.cancelled = False

    def isRunning(self):
        return True

    def cancel(self):
        self.cancelled = True

    def wait(self, ms=None):
        return False          # still running when the wait expires

    def quit(self):
        raise AssertionError("quit() does nothing on this worker; use cancel()")


class TestReopenAfterAStuckTurn:
    def test_it_still_opens_while_a_worker_is_winding_down(self, qapp):
        w = _overlay(qapp)
        w._worker = _StuckWorker()
        w._show_and_start()
        assert w.isVisible(), \
            "the window did not appear — this is the 'audio only' bug"
        w.close()

    def test_hiding_cancels_rather_than_calling_quit(self, qapp):
        w = _overlay(qapp)
        worker = _StuckWorker()
        w._worker = worker
        w._show_anchored()
        w._hide()
        assert worker.cancelled, "the worker was never told to stop"
        assert not w.isVisible()
        w.close()

    def test_hiding_does_not_block_the_gui_thread_for_seconds(self, qapp):
        import time
        w = _overlay(qapp)
        w._worker = _StuckWorker()
        w._show_anchored()
        started = time.monotonic()
        w._hide()
        elapsed = time.monotonic() - started
        assert elapsed < 0.6, f"_hide blocked the GUI thread for {elapsed:.2f}s"
        w.close()

    def test_repeated_open_close_always_leaves_it_visible(self, qapp):
        w = _overlay(qapp)
        for cycle in range(5):
            w._worker = _StuckWorker()     # every cycle strands another
            w._show_and_start()
            assert w.isVisible(), f"invisible on cycle {cycle}"
            w._hide()
            assert not w.isVisible(), f"still visible after hide on cycle {cycle}"
        w._show_and_start()
        assert w.isVisible(), "the window stopped opening after repeated cycles"
        w.close()

    def test_a_second_turn_is_not_stacked_on_a_live_one(self, qapp, monkeypatch):
        # Showing must be unconditional, but starting a second pipeline while
        # one is live must not be.
        w = _overlay(qapp)
        starts = []
        monkeypatch.setattr(w, "_start_pipeline",
                            lambda *a, **k: starts.append(True))
        w._worker = _StuckWorker()
        w._show_and_start()
        assert w.isVisible()
        assert starts == [], "a second pipeline was started over a live one"
        w.close()


class TestTheOtherEntryPoints:
    """analyze_screen, query_memory and the wake word had the same shape."""

    @pytest.mark.parametrize("entry", ["analyze_screen", "query_memory",
                                       "wake_word_activate"])
    def test_they_show_the_window_even_with_a_worker_running(self, qapp, entry):
        w = _overlay(qapp)
        w._worker = _StuckWorker()
        w._mic_muted = False
        getattr(w, entry)()
        assert w.isVisible(), f"{entry} left the window hidden"
        w.close()


class TestWorkerCancellation:
    def test_cancel_stops_the_recorder_and_the_voice(self):
        from core.pipeline import PipelineWorker
        voice_in, voice_out = MagicMock(), MagicMock()
        worker = PipelineWorker(voice_in, MagicMock(), voice_out, MagicMock())
        assert worker.cancelled is False
        worker.cancel()
        assert worker.cancelled is True
        voice_in.stop_recording.assert_called_once()
        voice_out.stop.assert_called_once()

    def test_cancel_survives_a_broken_device(self):
        # cancel() runs while the UI is closing; a failing device must not
        # take the close down with it.
        from core.pipeline import PipelineWorker
        voice_in = MagicMock()
        voice_in.stop_recording.side_effect = RuntimeError("device gone")
        worker = PipelineWorker(voice_in, MagicMock(), MagicMock(), MagicMock())
        worker.cancel()
        assert worker.cancelled is True

    def test_playback_stops_for_a_cancel_as_well_as_a_barge_in(self):
        from core.pipeline import PipelineWorker
        worker = PipelineWorker(MagicMock(), MagicMock(), MagicMock(), MagicMock())

        monitor = MagicMock()
        monitor.tripped.is_set.return_value = False
        should_stop = worker._should_stop(monitor)
        assert should_stop() is False
        worker.cancel()
        assert should_stop() is True, "playback ignored the cancel"

    def test_it_stops_without_a_barge_in_monitor_too(self):
        from core.pipeline import PipelineWorker
        worker = PipelineWorker(MagicMock(), MagicMock(), MagicMock(), MagicMock())
        should_stop = worker._should_stop(None)
        assert should_stop() is False
        worker.cancel()
        assert should_stop() is True
