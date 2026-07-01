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


class TestHudDataStrip:
    def test_refresh_hud_strip_no_status_file_is_safe(self, qapp, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        w = _make_overlay(qapp)
        w._refresh_hud_strip()   # must not raise
        assert w._hud._data_items == []
        w.close()

    def test_refresh_hud_strip_populates_from_status_file(self, qapp, tmp_path, monkeypatch):
        import json
        monkeypatch.chdir(tmp_path)
        (tmp_path / "data").mkdir()
        (tmp_path / "data" / "trading_status.json").write_text(json.dumps({
            "portfolio_value": 10500.0,
            "positions": [{"symbol": "AAPL", "unrealized_plpc": 2.1}],
        }))
        w = _make_overlay(qapp)
        w._refresh_hud_strip()
        assert any("AAPL" in item for item in w._hud._data_items)
        assert any("NAV" in item for item in w._hud._data_items)
        w.close()

    def test_cycle_mode_to_hud_refreshes_strip(self, qapp, tmp_path, monkeypatch):
        import json
        monkeypatch.chdir(tmp_path)
        (tmp_path / "data").mkdir()
        (tmp_path / "data" / "trading_status.json").write_text(json.dumps({
            "portfolio_value": 999.0,
            "positions": [],
        }))
        w = _make_overlay(qapp)
        w.cycle_mode()   # voice -> hud
        assert any("NAV" in item for item in w._hud._data_items)
        w.close()
