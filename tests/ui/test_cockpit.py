"""Tests for the Cockpit — the design's primary full-screen surface.

These never call open(): that would put a real full-screen window on the
user's desktop. What matters here is the contract around the orb — that
Chromium stays unbuilt until the cockpit is actually opened, and that state
maps onto the orb's own vocabulary.
"""
from unittest.mock import MagicMock

import pytest


def _make_cockpit(qapp):
    from ui.cockpit import CockpitWindow
    w = CockpitWindow(MagicMock(), MagicMock(), MagicMock(), MagicMock())
    w.set_wake_listener(None)
    return w


class TestLazyWebEngine:
    def test_no_chromium_until_the_cockpit_is_opened(self, qapp):
        # The hard rule: QWebEngine is lazy and single-instance.
        w = _make_cockpit(qapp)
        assert w._orb is None
        assert w._orb_ready is False
        w.close()

    def test_pushing_state_before_the_orb_exists_is_harmless(self, qapp):
        w = _make_cockpit(qapp)
        w.on_state_update("listening", "", "")     # must not raise
        assert w._current_state == "listening"
        w.close()


class TestStateMapping:
    @pytest.mark.parametrize("pipeline_state,orb_state", [
        ("idle", "idle"),
        ("listening", "listening"),
        ("processing", "thinking"),   # the pipeline's word → the design's
        ("speaking", "speaking"),
        ("error", "error"),
    ])
    def test_pipeline_states_map_onto_the_orbs_vocabulary(self, pipeline_state, orb_state):
        from ui.cockpit import _ORB_STATE
        assert _ORB_STATE[pipeline_state] == orb_state

    def test_every_orb_state_has_a_colour_in_the_cockpit_palette(self):
        from ui import tokens
        from ui.cockpit import _ORB_STATE
        for orb_state in set(_ORB_STATE.values()):
            assert orb_state in tokens.CK_STATE

    def test_state_carries_a_label_not_just_a_hue(self, qapp):
        w = _make_cockpit(qapp)
        seen = set()
        for state in ("listening", "processing", "speaking", "error"):
            w.on_state_update(state, "x", "y") if state != "error" else w.on_error("x")
            assert w._state_label.text().strip()
            seen.add(w._state_label.text())
        assert len(seen) == 4
        w.close()


class TestReadouts:
    def test_readouts_come_from_the_local_cache_never_the_network(self, tmp_path, monkeypatch):
        import ui.cockpit as mod
        cache = tmp_path / "cache.json"
        cache.write_text(
            '{"cards": {"calendar": {"text": "Standup at 10:00\\nthen review"}}}',
            encoding="utf-8",
        )
        monkeypatch.setattr(mod, "_CACHE", cache)
        assert mod._cached("calendar") == "Standup at 10:00"

    def test_a_missing_cache_reads_as_an_em_dash(self, tmp_path, monkeypatch):
        import ui.cockpit as mod
        monkeypatch.setattr(mod, "_CACHE", tmp_path / "nope.json")
        assert mod._cached("calendar") == "—"

    def test_the_clock_is_twelve_hour(self, qapp):
        w = _make_cockpit(qapp)
        w._tick_clock()
        assert w._r_time._value.text().endswith(("AM", "PM"))
        assert not w._r_time._value.text().startswith("0")
        w.close()


class TestStagedAction:
    def test_an_armed_action_shows_on_the_stage(self, qapp):
        from core import staging
        staging.reset()
        w = _make_cockpit(qapp)
        assert not w._staged.isVisibleTo(w)
        staging.stage(medium="whatsapp", target="Omar", body="the meeting moved")
        w._refresh_staged()
        assert w._staged.isVisibleTo(w)
        assert "WHATSAPP → Omar" in w._staged.text()
        staging.reset()
        w.close()

    def test_it_clears_when_the_action_resolves(self, qapp):
        from core import staging
        staging.reset()
        w = _make_cockpit(qapp)
        staging.stage(medium="gmail", target="mo@x.com", body="hi")
        w._refresh_staged()
        staging.resolve("sent")
        w._refresh_staged()
        assert not w._staged.isVisibleTo(w)
        staging.reset()
        w.close()


class TestAttention:
    """ambient (orb alone) → ready (readouts up) → exchange (words own it)."""

    def test_an_exchange_dims_the_readouts(self, qapp):
        w = _make_cockpit(qapp)
        w.on_state_update("processing", "what's on my plate", "")
        assert w._attention == "exchange"
        assert w._r_time.graphicsEffect().opacity() == pytest.approx(0.12)
        w.close()

    def test_the_readouts_come_back_when_the_turn_ends(self, qapp):
        w = _make_cockpit(qapp)
        w.on_state_update("processing", "x", "")
        w.on_pipeline_done()
        assert w._attention == "ready"
        assert w._r_time.graphicsEffect().opacity() == pytest.approx(1.0)
        w.close()

    def test_silence_falls_to_ambient_and_takes_the_exchange_with_it(self, qapp):
        w = _make_cockpit(qapp)
        w.on_state_update("speaking", "", "Three things today.")
        w.on_pipeline_done()
        w._go_ambient()                       # what the timer would do
        assert w._attention == "ambient"
        assert w._r_time.graphicsEffect().opacity() == 0.0
        assert w._answer.text() == ""
        w.close()

    def test_a_turn_in_flight_never_falls_to_ambient(self, qapp):
        w = _make_cockpit(qapp)
        w.on_state_update("listening", "", "")
        w._go_ambient()
        assert w._attention == "exchange"
        w.close()

    def test_anything_you_do_wakes_it_back_up(self, qapp):
        w = _make_cockpit(qapp)
        w._go_ambient()
        w._wake_attention()
        assert w._attention == "ready"
        assert w._ambient_timer.isActive()
        w.close()

    @pytest.mark.parametrize("setting,seconds", [
        ("30s", 30), ("60s", 60), ("2m", 120), (45, 45), ("90", 90),
        ("nonsense", 60), (None, 60),
    ])
    def test_the_delay_comes_from_settings(self, qapp, tmp_path, monkeypatch,
                                           setting, seconds):
        import json
        import ui.overlay as overlay_mod
        path = tmp_path / "settings.json"
        path.write_text(json.dumps({} if setting is None
                                   else {"ambient_delay": setting}),
                        encoding="utf-8")
        monkeypatch.setattr(overlay_mod, "_SETTINGS_FILE", path)
        w = _make_cockpit(qapp)
        assert w._ambient_delay_ms() == seconds * 1000
        w.close()


class TestKeyboardMap:
    def test_the_map_lists_only_keys_the_cockpit_honours(self, qapp):
        from ui.cockpit import _KEYS
        keys = {key for key, _ in _KEYS}
        assert keys == {"SPACE", "ENTER", "ESC", "L", "?"}

    def test_it_toggles(self, qapp):
        w = _make_cockpit(qapp)
        assert w._keymap.isHidden()
        w.toggle_keymap()
        assert not w._keymap.isHidden()
        w.toggle_keymap()
        assert w._keymap.isHidden()
        w.close()

    def test_escape_closes_the_map_before_anything_else(self, qapp):
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QKeyEvent
        w = _make_cockpit(qapp)
        w.toggle_keymap()
        w.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape,
                                  Qt.KeyboardModifier.NoModifier))
        assert w._keymap.isHidden()
        assert w.isHidden()          # never opened, so still hidden
        w.close()

    def test_escape_cancels_a_staged_action_before_closing(self, qapp):
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QKeyEvent
        from core import staging
        staging.reset()
        w = _make_cockpit(qapp)
        staging.stage(medium="whatsapp", target="Omar", body="hi")
        w.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape,
                                  Qt.KeyboardModifier.NoModifier))
        assert staging.current() is None
        staging.reset()
        w.close()


class TestReceiptLedger:
    def test_a_send_writes_one_green_line(self, qapp):
        from core import staging
        staging.reset()
        w = _make_cockpit(qapp)
        staging.stage(medium="whatsapp", target="Omar", body="hi")
        staging.resolve("sent", "whatsapp → Omar · sent")
        w._refresh_receipts()
        assert w._receipts_layout.count() == 1
        assert "Omar" in w._receipts_layout.itemAt(0).widget().text()
        staging.reset()
        w.close()

    def test_it_keeps_three_at_most(self, qapp):
        from core import staging
        staging.reset()
        w = _make_cockpit(qapp)
        for i in range(5):
            staging.stage(medium="gmail", target=f"person{i}", body="hi")
            staging.resolve("sent", f"gmail → person{i} · sent")
        w._refresh_receipts()
        assert w._receipts_layout.count() == 3
        staging.reset()
        w.close()

    def test_ambient_takes_the_receipts_too(self, qapp):
        from core import staging
        staging.reset()
        w = _make_cockpit(qapp)
        staging.stage(medium="gmail", target="a@b.c", body="hi")
        staging.resolve("sent", "gmail → a@b.c · sent")
        w._refresh_receipts()
        w._go_ambient()
        assert w._receipts_box.isHidden()
        staging.reset()
        w.close()


class TestSkillsReadout:
    def test_it_counts_what_settings_left_switched_on(self, qapp, tmp_path,
                                                     monkeypatch):
        import json
        import ui.overlay as overlay_mod
        path = tmp_path / "settings.json"
        path.write_text(json.dumps({"skills_disabled": ["gmail", "browser"]}),
                        encoding="utf-8")
        monkeypatch.setattr(overlay_mod, "_SETTINGS_FILE", path)
        w = _make_cockpit(qapp)
        assert w._skills_online() == "4 of 6"
        w.close()


class TestDataMoments:
    def _turn(self, tool):
        from core import progress
        progress.begin_turn("show me")
        progress.step_finished(progress.step_started(tool), True)

    def test_a_mail_turn_materialises_mail_rows(self, qapp, tmp_path, monkeypatch):
        import ui.cockpit as mod
        cache = tmp_path / "cache.json"
        cache.write_text('{"cards": {"mail": {"text": "Stripe — payout failed"}}}',
                         encoding="utf-8")
        monkeypatch.setattr(mod, "_CACHE", cache)
        w = _make_cockpit(qapp)
        self._turn("list_emails")
        w._show_data_moment()
        assert w._moment_layout.count() > 0
        w.close()

    def test_a_turn_that_touched_nothing_shows_nothing(self, qapp):
        from core import progress
        w = _make_cockpit(qapp)
        progress.begin_turn("what's the weather")
        progress.step_finished(progress.step_started("get_weather"), True)
        w._show_data_moment()
        assert w._moment.isHidden()
        w.close()

    def test_the_next_turn_clears_it(self, qapp, tmp_path, monkeypatch):
        import ui.cockpit as mod
        cache = tmp_path / "cache.json"
        cache.write_text('{"cards": {"mail": {"text": "Stripe — payout failed"}}}',
                         encoding="utf-8")
        monkeypatch.setattr(mod, "_CACHE", cache)
        w = _make_cockpit(qapp)
        self._turn("list_emails")
        w._show_data_moment()
        w.on_state_update("listening", "", "")
        assert w._moment_layout.count() == 0
        w.close()


class TestStepMark:
    @pytest.mark.parametrize("status", ["active", "done", "failed"])
    def test_each_mark_paints_without_a_font_glyph(self, qapp, status):
        # No bundled face carries U+2713, so the ledger's marks are painted.
        from ui.widgets import StepMark
        mark = StepMark(status, "#56C99C")
        assert not mark.grab().isNull()
        mark.deleteLater()


class TestScrubber:
    """The controls under the stage are the reel's; these pin that they do
    something real rather than sitting there as decoration."""

    def _exchange(self, w, heard, answer):
        w.on_state_update("processing", heard, "")
        w.on_state_update("speaking", heard, answer)

    def test_it_steps_back_through_the_sessions_turns(self, qapp):
        w = _make_cockpit(qapp)
        self._exchange(w, "first question", "first answer")
        self._exchange(w, "second question", "second answer")
        assert w._scrub_value.text() == "NOW"
        assert w._answer.text() == "second answer"

        w._scrub(-1)                      # the ‹ arrow: further back
        assert w._answer.text() == "second answer"
        assert w._scrub_value.text() == "1 BACK"
        w._scrub(-1)
        assert w._answer.text() == "first answer"
        assert w._heard.text() == "first question"
        w.close()

    def test_it_cannot_run_off_either_end(self, qapp):
        w = _make_cockpit(qapp)
        self._exchange(w, "only question", "only answer")
        for _ in range(5):
            w._scrub(-1)
        assert w._scrub_value.text() == "1 BACK"
        for _ in range(5):
            w._scrub(1)
        assert w._scrub_value.text() == "NOW"
        w.close()

    def test_a_new_turn_takes_the_stage_back_from_the_scrubber(self, qapp):
        w = _make_cockpit(qapp)
        self._exchange(w, "old question", "old answer")
        w._scrub(-1)
        assert w._scrub_value.text() == "1 BACK"
        w.on_state_update("listening", "", "")
        assert w._scrub_value.text() == "NOW"
        assert w._answer.text() == ""
        w.close()

    def test_the_pipeline_caption_is_not_shown_as_what_mo_said(self, qapp):
        # When nothing was heard the error lands next to the heard line, which
        # used to read "Transcribing..." as though Mo had said it.
        w = _make_cockpit(qapp)
        w.on_state_update("listening", "", "")
        w.on_state_update("processing", "Transcribing...", "")
        w.on_error("Nothing heard — please try again")
        assert w._heard.text() == ""
        w.close()

    def test_scrubbing_with_no_history_is_harmless(self, qapp):
        w = _make_cockpit(qapp)
        w._scrub(-1)
        assert w._scrub_value.text() == "TODAY"
        w.close()

    def test_the_view_pill_asks_for_the_command_center(self, qapp):
        w = _make_cockpit(qapp)
        seen = []
        w.knowledge_requested.connect(lambda: seen.append(True))
        w._view_pill.click()
        assert seen == [True]
        w.close()


class TestRails:
    def test_the_skills_count_sits_with_the_list_it_counts(self, qapp):
        # It used to float unparented at the foot of the rail.
        w = _make_cockpit(qapp)
        assert w._r_skills.parent() is not None
        w.close()

    def test_automations_never_render_an_empty_rail(self, qapp):
        w = _make_cockpit(qapp)
        w._refresh_rails()
        assert w._auto_list.count() >= 1
        w.close()
