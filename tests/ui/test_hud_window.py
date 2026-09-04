"""HUD show/hide must never block the UI thread or lock out Ctrl+Space.

A PipelineWorker overrides QThread.run(), so quit() cannot interrupt it and
wait() would freeze the Qt main thread. Closing must signal and move on, and
reopening must still show the window while the old worker unwinds.
"""
import pytest


class _FakeHudWebView:
    """Stand-in for HudWebView - a real QWebEngineView crashes under pytest."""

    def __new__(cls, parent=None):
        from PyQt6.QtWidgets import QWidget
        from unittest.mock import MagicMock
        widget = QWidget(parent)
        for method in ("enter_standby", "push_telemetry", "goto_scene",
                       "set_state", "push_voice_result", "push_market_data",
                       "push_proactive"):
            setattr(widget, method, MagicMock())
        widget.ready = MagicMock()
        return widget


def _make_hud(qapp):
    """Build a HudWindow with no real web view, timers, or pipeline."""
    from unittest.mock import MagicMock, patch
    import ui.hud_window
    voice_in, brain, voice_out, memory = (MagicMock() for _ in range(4))
    with patch.object(ui.hud_window, "HudWebView", _FakeHudWebView), \
         patch.object(ui.hud_window.HudWindow, "_setup_timers", lambda self: None):
        w = ui.hud_window.HudWindow(voice_in, brain, voice_out, memory)
    return w


def _running_worker():
    from unittest.mock import MagicMock
    worker = MagicMock()
    worker.isRunning.return_value = True
    return worker


class TestCloseDoesNotBlockUiThread:
    def test_close_does_not_wait_on_worker(self, qapp):
        w = _make_hud(qapp)
        w._worker = _running_worker()
        w._close_hud()
        # wait() on the Qt main thread freezes the whole HUD for its timeout.
        w._worker.wait.assert_not_called()
        w.close()

    def test_close_signals_the_worker_to_stop(self, qapp):
        w = _make_hud(qapp)
        w._worker = _running_worker()
        w._close_hud()
        w.voice_in.stop_recording.assert_called_once()
        w.voice_out.stop.assert_called_once()
        w.close()


class TestReopenWhileWorkerRuns:
    def test_open_shows_window_even_while_worker_runs(self, qapp):
        w = _make_hud(qapp)
        w._worker = _running_worker()
        w._open_hud()
        # Previously this returned early, so Ctrl+Space did nothing at all
        # until the in-flight pipeline finished.
        assert w.isVisible()
        w.close()

    def test_open_does_not_stack_a_second_pipeline(self, qapp):
        from unittest.mock import MagicMock
        w = _make_hud(qapp)
        w._worker = _running_worker()
        w._start_pipeline = MagicMock()
        w._open_hud()
        w._start_pipeline.assert_not_called()
        w.close()

    def test_open_starts_pipeline_when_idle(self, qapp):
        from unittest.mock import MagicMock
        w = _make_hud(qapp)
        w._worker = None
        w._start_pipeline = MagicMock()
        w._open_hud()
        w._start_pipeline.assert_called_once()
        w.close()

    def test_open_respects_mic_mute(self, qapp):
        from unittest.mock import MagicMock
        w = _make_hud(qapp)
        w._worker = None
        w._mic_muted = True
        w._start_pipeline = MagicMock()
        w._open_hud()
        w._start_pipeline.assert_not_called()
        w.close()
