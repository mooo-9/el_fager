"""Tests for the native compact assistant (W3 hybrid-UI rewrite).

The overlay is the single default surface: no mode cycling, no embedded
QWebEngine, no HUD canvas. The rich HUD lives in ui/hud_window.py and is
constructed lazily by main.py.
"""
from unittest.mock import MagicMock


def _make_overlay(qapp):
    """Build a minimal OverlayWindow without a real wake listener or pipeline."""
    import ui.overlay
    voice_in = MagicMock()
    brain = MagicMock()
    brain._offline_mode = False
    voice_out = MagicMock()
    memory = MagicMock()
    w = ui.overlay.OverlayWindow(voice_in, brain, voice_out, memory)
    w.set_wake_listener(None)  # builds the UI
    return w


class TestCompactSurface:
    def test_no_mode_machinery_remains(self, qapp):
        w = _make_overlay(qapp)
        assert not hasattr(w, "cycle_mode")
        assert not hasattr(w, "switch_to_jarvis_hud")
        assert not hasattr(w, "_mode")
        assert not hasattr(w, "_stack")
        w.close()

    def test_no_webengine_in_overlay_module(self):
        import ui.overlay as mod
        assert not hasattr(mod, "HudWebView")
        assert not hasattr(mod, "HudCanvas")

    def test_builds_ui_with_input_and_history(self, qapp):
        w = _make_overlay(qapp)
        assert w._text_input is not None
        assert w._history_scroll is not None
        w.close()


class TestStateDisplay:
    def test_listening_state_sets_status(self, qapp):
        w = _make_overlay(qapp)
        w.on_state_update("listening", "", "")
        assert w._status_label.text() == "Listening..."
        assert w._current_state == "listening"
        w.close()

    def test_processing_adds_user_bubble(self, qapp):
        w = _make_overlay(qapp)
        w.on_state_update("processing", "what time is it", "")
        assert ("user", "what time is it") in w._history
        w.close()

    def test_speaking_adds_assistant_bubble(self, qapp):
        w = _make_overlay(qapp)
        w.on_state_update("speaking", "what time is it", "It is noon.")
        assert ("assistant", "It is noon.") in w._history
        w.close()

    def test_error_shows_message(self, qapp):
        w = _make_overlay(qapp)
        w.on_error("Nothing heard")
        assert w._current_state == "error"
        assert w._transcript_label.text() == "Nothing heard"
        w.close()


class TestTheme:
    def test_state_colors_are_distinct(self):
        from ui import theme
        colors = {theme.STATE_COLORS[s] for s in
                  ("listening", "processing", "speaking", "error")}
        assert len(colors) == 4

    def test_card_style_has_theme_variants(self):
        from ui import theme
        dark = theme.card_style("dark")
        oled = theme.card_style("oled")
        assert dark != oled
        assert "border-radius" in dark
