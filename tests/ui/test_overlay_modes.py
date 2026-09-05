import pytest


class _FakeHudWebView:
    """Stand-in for HudWebView — a real QWebEngineView crashes under pytest."""

    def __new__(cls, parent=None, defer_load=False):
        from PyQt6.QtWidgets import QWidget
        from unittest.mock import MagicMock
        widget = QWidget(parent)
        for method in ("enter_standby", "push_telemetry", "goto_scene",
                       "set_state", "push_voice_result", "push_market_data",
                       "push_proactive", "ensure_loaded"):
            setattr(widget, method, MagicMock())
        return widget


def _make_overlay(qapp):
    """Build a minimal OverlayWindow without a real wake listener or pipeline."""
    from unittest.mock import MagicMock, patch
    import ui.overlay
    voice_in = MagicMock()
    brain = MagicMock()
    brain._offline_mode = False
    voice_out = MagicMock()
    memory = MagicMock()
    with patch.object(ui.overlay, "HudWebView", _FakeHudWebView):
        w = ui.overlay.OverlayWindow(voice_in, brain, voice_out, memory)
        w.set_wake_listener(None)  # builds the UI — must run with the stub active
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

    def test_cycle_mode_wraps_at_four(self, qapp):
        w = _make_overlay(qapp)
        w.cycle_mode()   # 1
        w.cycle_mode()   # 2
        w.cycle_mode()   # 3 (jarvis HUD)
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

    def test_mode_name_jarvis(self, qapp):
        w = _make_overlay(qapp)
        w.cycle_mode()   # 1 hud
        w.cycle_mode()   # 2 trading
        w.cycle_mode()   # 3 jarvis
        assert w.mode_name == "jarvis"
        w.close()

    def test_switch_to_jarvis_hud_jumps_directly(self, qapp):
        w = _make_overlay(qapp)
        w.switch_to_jarvis_hud()
        assert w._mode == 3
        assert w.mode_name == "jarvis"
        w.close()

    def test_stacked_widget_has_four_pages(self, qapp):
        w = _make_overlay(qapp)
        assert w._stack.count() == 4
        w.close()


class TestOverlayHudWebDeferred:
    """hud.html is ~850 KB and spawns its own renderer process — the compact
    overlay must not load a second copy just by being constructed."""

    def test_hud_page_not_loaded_on_construction(self, qapp):
        w = _make_overlay(qapp)
        w._hud_web.ensure_loaded.assert_not_called()
        w.close()

    def test_hud_page_loads_when_entering_jarvis_mode(self, qapp):
        w = _make_overlay(qapp)
        w.switch_to_jarvis_hud()
        w._hud_web.ensure_loaded.assert_called()
        w.close()


class TestOverlayIdleTimers:
    def test_status_bar_poll_skips_while_hidden(self, qapp):
        w = _make_overlay(qapp)
        assert not w.isVisible()
        w._status_bar.setVisible(True)
        w._update_status_bar()
        # Untouched — the poll returned before reading any state file.
        assert w._status_bar.isVisibleTo(w)
        w.close()
