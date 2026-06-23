import pytest


def _make_overlay(qapp):
    """Build a minimal OverlayWindow without a real wake listener or pipeline."""
    from unittest.mock import MagicMock
    from ui.overlay import OverlayWindow
    voice_in = MagicMock()
    brain = MagicMock()
    brain._offline_mode = False
    voice_out = MagicMock()
    memory = MagicMock()
    w = OverlayWindow(voice_in, brain, voice_out, memory)
    w.set_wake_listener(None)
    return w


class TestOverlayModes:
    def test_initial_mode_is_zero(self, qapp):
        w = _make_overlay(qapp)
        assert w._mode == 0
        w.close()

    def test_cycle_mode_advances(self, qapp):
        w = _make_overlay(qapp)
        w.cycle_mode()
        assert w._mode == 1
        w.close()

    def test_cycle_mode_wraps_at_three(self, qapp):
        w = _make_overlay(qapp)
        w.cycle_mode()   # 1
        w.cycle_mode()   # 2
        w.cycle_mode()   # 0
        assert w._mode == 0
        w.close()

    def test_mode_name_voice(self, qapp):
        w = _make_overlay(qapp)
        assert w.mode_name == "voice"
        w.close()

    def test_mode_name_hud(self, qapp):
        w = _make_overlay(qapp)
        w.cycle_mode()
        assert w.mode_name == "hud"
        w.close()

    def test_stacked_widget_has_three_pages(self, qapp):
        from PyQt6.QtWidgets import QStackedWidget
        w = _make_overlay(qapp)
        assert w._stack.count() == 3
        w.close()
