"""Compact overlay show/hide must not block the UI thread or lock out the hotkey.

Same contract as tests/ui/test_hud_window.py - PipelineWorker overrides
QThread.run(), so quit() cannot interrupt it and wait() would freeze Qt.
"""
from tests.ui.test_overlay_modes import _make_overlay


def _running_worker():
    from unittest.mock import MagicMock
    worker = MagicMock()
    worker.isRunning.return_value = True
    return worker


class TestHideDoesNotBlockUiThread:
    def test_hide_does_not_wait_on_worker(self, qapp):
        w = _make_overlay(qapp)
        w._worker = _running_worker()
        w._hide()
        w._worker.wait.assert_not_called()
        w.close()

    def test_hide_signals_the_worker_to_stop(self, qapp):
        w = _make_overlay(qapp)
        w._worker = _running_worker()
        w._hide()
        w.voice_in.stop_recording.assert_called_once()
        w.voice_out.stop.assert_called_once()
        w.close()


class TestShowWhileWorkerRuns:
    def test_show_displays_card_even_while_worker_runs(self, qapp):
        w = _make_overlay(qapp)
        w._worker = _running_worker()
        w._show_and_start()
        assert w.isVisible()
        w.close()

    def test_show_does_not_stack_a_second_pipeline(self, qapp):
        from unittest.mock import MagicMock
        w = _make_overlay(qapp)
        w._worker = _running_worker()
        w._start_pipeline = MagicMock()
        w._show_and_start()
        w._start_pipeline.assert_not_called()
        w.close()

    def test_show_starts_pipeline_when_idle(self, qapp):
        from unittest.mock import MagicMock
        w = _make_overlay(qapp)
        w._worker = None
        w._start_pipeline = MagicMock()
        w._show_and_start()
        w._start_pipeline.assert_called_once()
        w.close()
