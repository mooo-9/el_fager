import pytest


class TestHudCanvasConstruction:
    def test_widget_created(self, qapp):
        from ui.hud_canvas import HudCanvas
        w = HudCanvas()
        assert w is not None
        w.close()

    def test_default_state_is_idle(self, qapp):
        from ui.hud_canvas import HudCanvas
        w = HudCanvas()
        assert w._state == "idle"
        w.close()

    def test_minimum_size_set(self, qapp):
        from ui.hud_canvas import HudCanvas
        w = HudCanvas()
        assert w.minimumWidth() >= 400
        assert w.minimumHeight() >= 300
        w.close()

    def test_default_response_text_empty(self, qapp):
        from ui.hud_canvas import HudCanvas
        w = HudCanvas()
        assert w._response_text == ""
        assert w._text_alpha == 0
        w.close()


class TestHudCanvasState:
    def test_set_state_listening(self, qapp):
        from ui.hud_canvas import HudCanvas
        w = HudCanvas()
        w.set_state("listening")
        assert w._state == "listening"
        w.close()

    def test_set_state_speaking(self, qapp):
        from ui.hud_canvas import HudCanvas
        w = HudCanvas()
        w.set_state("speaking")
        assert w._state == "speaking"
        w.close()

    def test_set_response_text_sets_alpha(self, qapp):
        from ui.hud_canvas import HudCanvas
        w = HudCanvas()
        w.set_response_text("Analysis complete")
        assert w._response_text == "Analysis complete"
        assert w._text_alpha == 255
        w.close()

    def test_set_amplitude_clamps_high(self, qapp):
        from ui.hud_canvas import HudCanvas
        w = HudCanvas()
        w.set_amplitude(2.5)
        assert w._amplitude <= 1.0
        w.close()

    def test_set_amplitude_clamps_low(self, qapp):
        from ui.hud_canvas import HudCanvas
        w = HudCanvas()
        w.set_amplitude(-1.0)
        assert w._amplitude >= 0.0
        w.close()


class TestHudCanvasDataStrip:
    def test_set_data_strip_stored(self, qapp):
        from ui.hud_canvas import HudCanvas
        w = HudCanvas()
        w.set_data_strip(["SPY: +1.2%", "AAPL: -0.5%"])
        assert len(w._data_items) == 2
        assert w._data_items[0] == "SPY: +1.2%"
        w.close()

    def test_data_strip_capped_at_five(self, qapp):
        from ui.hud_canvas import HudCanvas
        w = HudCanvas()
        w.set_data_strip(["A", "B", "C", "D", "E", "F", "G"])
        assert len(w._data_items) == 5
        w.close()
