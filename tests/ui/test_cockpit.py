"""Tests for the Cockpit — the design's primary full-screen surface.

These never call open(): that would put a real full-screen window on the
user's desktop. What matters here is the contract around the orb — that
Chromium stays unbuilt until the cockpit is actually opened, and that state
maps onto the orb's own vocabulary.
"""
from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def settings_file(tmp_path, monkeypatch):
    """The Cockpit remembers its window in settings; keep that off the real
    data/settings.json, which closing a window in a test would overwrite."""
    import ui.overlay as overlay_mod
    path = tmp_path / "settings.json"
    path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(overlay_mod, "_SETTINGS_FILE", path)
    return path


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
        assert w._status.time.text().endswith(("AM", "PM"))
        assert not w._status.time.text().startswith("0")
        w.close()


class TestStatusCard:
    """The reel's small card at the top of the left rail: the time, what El
    Fager has done today, and what is next."""

    def test_it_heads_the_left_rail_in_place_of_the_big_readouts(self, qapp):
        from PyQt6.QtWidgets import QLabel
        w = _make_cockpit(qapp)
        rail = w._status.parentWidget().layout()
        assert rail.indexOf(w._status) == 0
        kickers = [l.text() for l in w._status.parentWidget().findChildren(QLabel)
                   if l.isVisibleTo(w._status.parentWidget())]
        assert "TIME" not in kickers
        w.close()

    def test_done_today_counts_only_todays_actions(self, qapp, monkeypatch):
        from datetime import datetime, timedelta
        from core import ledger
        now = datetime.now()
        today, yesterday = now.isoformat(timespec="seconds"),             (now - timedelta(days=1)).isoformat(timespec="seconds")
        monkeypatch.setattr(ledger, "entries", lambda limit=50, category=None: [
            {"ts": today, "category": "sent", "revoked": False},
            {"ts": today, "category": "logged", "revoked": False},
            {"ts": today, "category": "sent", "revoked": True},      # walked back
            {"ts": today, "category": "revoked", "revoked": False},  # the undo itself
            {"ts": yesterday, "category": "sent", "revoked": False},
        ])
        w = _make_cockpit(qapp)
        w._refresh_readouts()
        assert w._status.done.text() == "2"
        w.close()

    def test_an_unreadable_ledger_reads_as_a_dash(self, qapp, monkeypatch):
        from core import ledger
        def broken(**_):
            raise OSError("no key")
        monkeypatch.setattr(ledger, "entries", broken)
        w = _make_cockpit(qapp)
        w._refresh_readouts()
        assert w._status.done.text() == "—"
        w.close()

    def test_next_comes_from_the_calendar_cache(self, qapp, tmp_path, monkeypatch):
        import ui.cockpit as mod
        cache = tmp_path / "cache.json"
        cache.write_text('{"cards": {"calendar": {"text": "19:00  Gym"}}}', encoding="utf-8")
        monkeypatch.setattr(mod, "_CACHE", cache)
        w = _make_cockpit(qapp)
        w._refresh_readouts()
        assert w._status.next.text() == "19:00  Gym"
        w.close()


class TestMonthArrows:
    def _title(self, w):
        return w._calendar._title.text()

    def test_the_arrows_step_through_the_months(self, qapp):
        from datetime import datetime
        w = _make_cockpit(qapp)
        now = datetime.now()
        this = now.strftime("%B %Y").upper()
        w._calendar._next.click()
        nxt = datetime(now.year + (now.month == 12), now.month % 12 + 1, 1)
        assert self._title(w) == nxt.strftime("%B %Y").upper()
        w._calendar._prev.click()
        w._calendar._prev.click()
        prev = datetime(now.year - (now.month == 1), (now.month - 2) % 12 + 1, 1)
        assert self._title(w) == prev.strftime("%B %Y").upper()
        w._calendar.refresh()
        assert self._title(w) == this
        w.close()

    def test_today_is_lit_only_in_its_own_month(self, qapp):
        from ui import tokens
        w = _make_cockpit(qapp)
        def lit():
            return [c for c in w._calendar.findChildren(type(w._calendar._title))
                    if tokens.EMBER in c.styleSheet()]
        assert len(lit()) == 1
        w._calendar._next.click()
        assert lit() == []
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
        assert w._status.graphicsEffect().opacity() == pytest.approx(0.12)
        w.close()

    def test_the_readouts_come_back_when_the_turn_ends(self, qapp):
        w = _make_cockpit(qapp)
        w.on_state_update("processing", "x", "")
        w.on_pipeline_done()
        assert w._attention == "ready"
        assert w._status.graphicsEffect().opacity() == pytest.approx(1.0)
        w.close()

    def test_silence_falls_to_ambient_but_keeps_the_transcript(self, qapp):
        w = _make_cockpit(qapp)
        w.on_state_update("speaking", "", "Three things today.")
        w.on_pipeline_done()
        w._go_ambient()                       # what the timer would do
        assert w._attention == "ambient"
        assert w._status.graphicsEffect().opacity() == 0.0
        from PyQt6.QtWidgets import QLabel     # saved until the Cockpit closes
        assert "Three things today." in [
            label.text() for label in w._reading_box.findChildren(QLabel)]
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


class TestAutomationRows:
    def test_each_row_leads_with_a_painted_file_icon(self, qapp):
        from PyQt6.QtWidgets import QLabel
        from ui.cockpit import _FileMark, _RailRow
        row = _RailRow("morning routine", "MANUAL")
        assert len(row.findChildren(_FileMark)) == 1
        assert "▪" not in [label.text() for label in row.findChildren(QLabel)]
        row.deleteLater()

    def test_the_icon_is_ember_not_a_blank_box(self, qapp):
        # Painted, not typed: a font without the glyph would draw nothing.
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QColor, QImage
        from ui import tokens
        from ui.cockpit import _FileMark
        mark = _FileMark()
        image = QImage(mark.size(), QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        mark.render(image)
        inked = [image.pixelColor(x, y)
                 for x in range(image.width()) for y in range(image.height())
                 if image.pixelColor(x, y).alpha() > 200]
        assert inked, "the icon painted nothing"
        ember = QColor(tokens.EMBER)
        assert all(abs(c.hue() - ember.hue()) <= 12 for c in inked
                   if c.saturation() > 60), "the icon is not ember"
        mark.deleteLater()


class TestStepMark:
    @pytest.mark.parametrize("status", ["active", "done", "failed"])
    def test_each_mark_paints_without_a_font_glyph(self, qapp, status):
        # No bundled face carries U+2713, so the ledger's marks are painted.
        from ui.widgets import StepMark
        mark = StepMark(status, "#56C99C")
        assert not mark.grab().isNull()
        mark.deleteLater()


class TestConversation:
    """The right rail's TRANSCRIPT panel is one scrolling conversation: every
    exchange this session stacked in order, kept until the Cockpit closes.
    The words live only there — none of them is painted over the sphere."""

    def _exchange(self, w, heard, answer):
        w.on_state_update("listening", "", "")
        w.on_state_update("processing", heard, "")
        w.on_state_update("speaking", heard, answer)

    def _panel(self, w):
        from PyQt6.QtWidgets import QLabel
        return [label.text() for label in w._reading_box.findChildren(QLabel)]

    def test_automations_sit_above_the_conversation_which_takes_the_height(self, qapp):
        w = _make_cockpit(qapp)
        rail = w._reading_panel.parentWidget().layout()
        assert rail.indexOf(w._reading_panel) == 1
        assert rail.stretch(1) == 1
        w.close()

    def test_no_words_are_painted_over_the_sphere(self, qapp):
        from PyQt6.QtWidgets import QLabel
        w = _make_cockpit(qapp)
        self._exchange(w, "what's on my calendar", "Gym at seven.")
        outside_panel = [label.text() for label in w.findChildren(QLabel)
                         if not w._reading_panel.isAncestorOf(label)]
        assert "what's on my calendar" not in outside_panel
        assert "Gym at seven." not in outside_panel
        w.close()


    def test_a_short_answer_is_in_the_panel_too(self, qapp):
        w = _make_cockpit(qapp)
        self._exchange(w, "thanks", "Any time.")
        assert "Any time." in self._panel(w)
        w.close()

    def test_asking_again_adds_the_question_before_the_answer(self, qapp):
        w = _make_cockpit(qapp)
        self._exchange(w, "first question", "first answer")
        w.on_state_update("listening", "", "")
        w.on_state_update("processing", "second question", "")
        assert "second question" in self._panel(w)
        assert "first answer" in self._panel(w)
        w.close()

    def test_the_same_words_twice_are_two_exchanges(self, qapp):
        w = _make_cockpit(qapp)
        self._exchange(w, "Send it.", "Sent.")
        self._exchange(w, "Send it.", "Already sent.")
        assert self._panel(w).count("Send it.") == 2
        w.close()

    def test_every_exchange_is_kept_not_just_the_last_twenty(self, qapp):
        w = _make_cockpit(qapp)
        for n in range(30):
            self._exchange(w, f"question {n}", f"answer {n}")
        assert "answer 0" in self._panel(w)
        assert "answer 29" in self._panel(w)
        w.close()

    def test_each_exchange_carries_its_time(self, qapp):
        import re
        w = _make_cockpit(qapp)
        self._exchange(w, "first question", "first answer")
        self._exchange(w, "second question", "second answer")
        stamps = [t for t in self._panel(w) if re.fullmatch(r"\d{1,2}:\d{2} [AP]M", t)]
        assert len(stamps) == 2
        w.close()

    def test_a_long_answer_keeps_its_sections(self, qapp):
        w = _make_cockpit(qapp)
        self._exchange(w, "summary please", "**Academic:** " + "two left. " * 30)
        assert "ACADEMIC" in self._panel(w)
        assert not any("**" in t for t in self._panel(w))
        w.close()

    def test_listening_again_keeps_the_conversation(self, qapp):
        # The mic reopens a beat after every answer; that must not wipe what
        # Mo is still reading.
        w = _make_cockpit(qapp)
        self._exchange(w, "old question", "old answer")
        w.on_state_update("listening", "", "")
        assert "old answer" in self._panel(w)
        w.close()

    def test_an_interrupted_answer_says_so_and_only_that_one(self, qapp):
        w = _make_cockpit(qapp)
        self._exchange(w, "first question", "first answer")
        self._exchange(w, "tell me a story", "Once upon a time")
        w.on_state_update("interrupted", "tell me a story", "Once upon a time")
        panel = self._panel(w)
        assert panel.count("INTERRUPTED") == 1
        assert panel.index("INTERRUPTED") > panel.index("Once upon a time")
        w.close()

    def test_escape_clears_the_conversation(self, qapp):
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QKeyEvent
        from core import staging
        staging.reset()
        w = _make_cockpit(qapp)
        self._exchange(w, "first question", "first answer")
        w.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape,
                                  Qt.KeyboardModifier.NoModifier))
        assert self._panel(w) == []
        w.close()

    def test_the_next_session_starts_empty(self, qapp):
        w = _make_cockpit(qapp)
        self._exchange(w, "yesterday", "old")
        w._close()
        self._exchange(w, "today", "new")
        assert "yesterday" not in self._panel(w)
        assert "today" in self._panel(w)
        w.close()

    def test_the_pipeline_caption_is_not_taken_for_what_mo_said(self, qapp):
        w = _make_cockpit(qapp)
        w.on_state_update("listening", "", "")
        w.on_state_update("processing", "Transcribing...", "")
        w.on_error("Nothing heard — please try again")
        assert self._panel(w) == []
        assert w._notice.text() == "Nothing heard — please try again"
        w.close()

    def test_the_voice_bar_names_who_you_are_talking_to(self, qapp):
        w = _make_cockpit(qapp)
        assert "talking to El Fager through voice" in w._voice_bar.text()
        w.on_state_update("listening", "", "")
        assert w._voice_bar.text().strip().startswith("LISTENING")
        w.on_state_update("speaking", "hi", "Hello.")
        assert w._voice_bar.text().strip().startswith("SPEAKING")
        w.on_pipeline_done()
        assert "talking to El Fager through voice" in w._voice_bar.text()
        w.close()

    def test_the_voice_bar_starts_a_turn(self, qapp):
        from unittest.mock import patch
        w = _make_cockpit(qapp)
        with patch("core.pipeline.PipelineWorker") as worker:
            w._voice_bar.click()
        assert worker.called
        w.close()


class TestTranscriptTabs:
    """One tab per question along the top of the TRANSCRIPT panel, as the
    reel's panel has them; the selected tab's exchange is the one on show."""

    def _exchange(self, w, heard, answer):
        w.on_state_update("listening", "", "")
        w.on_state_update("processing", heard, "")
        w.on_state_update("speaking", heard, answer)

    def _showing(self, w):
        from PyQt6.QtWidgets import QLabel
        return [label.text() for label in w._reading_box.findChildren(QLabel)
                if label.isVisibleTo(w._reading_box)]

    def test_the_tabs_head_the_transcript_panel(self, qapp):
        w = _make_cockpit(qapp)
        assert w._reading_panel.isAncestorOf(w._tabs_scroll)
        assert w._reading_panel.column.indexOf(w._tabs_row) == 0
        w.close()

    def test_each_question_gets_a_tab_named_for_its_topic_in_order(self, qapp):
        w = _make_cockpit(qapp)
        self._exchange(w, "give me my daily briefing", "…")
        self._exchange(w, "what's the weather tomorrow?", "…")
        self._exchange(w, "Thanks.", "Any time.")
        assert [b.text() for b in w._tab_buttons] == [
            "Daily briefing", "Weather tomorrow", "Thanks"]
        w.close()

    def test_the_mouse_wheel_scrolls_the_tabs_sideways(self, qapp):
        from PyQt6.QtCore import QPoint, QPointF, Qt
        from PyQt6.QtGui import QWheelEvent
        w = _make_cockpit(qapp)
        w.resize(1536, 816)
        w.show()
        for n in range(12):
            self._exchange(w, f"tell me about topic number {n}", "…")
        for _ in range(20):
            qapp.processEvents()
        bar = w._tabs_scroll.horizontalScrollBar()
        assert bar.maximum() > 0
        bar.setValue(bar.maximum())
        wheel = QWheelEvent(QPointF(10, 10), QPointF(10, 10), QPoint(0, 0), QPoint(0, 120),
                            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                            Qt.ScrollPhase.NoScrollPhase, False)
        w._tabs_scroll.wheelEvent(wheel)
        assert bar.value() < bar.maximum(), "wheel up should move toward the first tab"
        w.close()

    def test_hovering_a_tab_shows_the_whole_question(self, qapp):
        w = _make_cockpit(qapp)
        self._exchange(w, "give me my daily briefing", "…")
        assert w._tab_buttons[0].toolTip() == "give me my daily briefing"
        w.close()

    def test_a_tab_is_wide_enough_for_its_name(self, qapp):
        w = _make_cockpit(qapp)
        self._exchange(w, "play Estanna by Fares Sokkar on Spotify", "Playing.")
        tab = w._tab_buttons[0]
        assert tab.width() >= tab.fontMetrics().horizontalAdvance(tab.text()) + 16
        w.close()

    def test_a_turn_with_nothing_heard_falls_back_to_its_number(self, qapp):
        w = _make_cockpit(qapp)
        w.on_state_update("speaking", "", "Good morning.")   # no question came first
        assert [b.text() for b in w._tab_buttons] == ["1"]
        w.close()


    def test_only_the_selected_exchange_is_on_show(self, qapp):
        w = _make_cockpit(qapp)
        self._exchange(w, "first question", "first answer")
        self._exchange(w, "second question", "second answer")
        assert "second answer" in self._showing(w)
        assert "first answer" not in self._showing(w)

        w._tab_buttons[0].click()
        assert "first question" in self._showing(w)
        assert "first answer" in self._showing(w)
        assert "second answer" not in self._showing(w)
        assert [b.isChecked() for b in w._tab_buttons] == [True, False]
        w.close()

    def test_asking_again_opens_the_next_tab_before_the_answer(self, qapp):
        w = _make_cockpit(qapp)
        self._exchange(w, "first question", "first answer")
        w._tab_buttons[0].click()
        w.on_state_update("listening", "", "")
        w.on_state_update("processing", "second question", "")
        assert len(w._tab_buttons) == 2
        assert w._tab_buttons[1].isChecked()
        assert "second question" in self._showing(w)
        w.close()

    def test_the_arrows_and_the_tabs_agree(self, qapp):
        w = _make_cockpit(qapp)
        for n in range(3):
            self._exchange(w, f"question {n}", f"answer {n}")
        w._scrub_prev.click()
        assert w._tab_buttons[1].isChecked()
        w._tab_buttons[0].click()
        assert w._scrub_value.text() == "1 / 3"
        w.close()

    def test_a_long_answer_scrolls_inside_its_tab_from_the_top(self, qapp):
        w = _make_cockpit(qapp)
        w.resize(1536, 816)
        w.show()
        self._exchange(w, "brief me", "**Mail:** " + "five unread from LinkedIn. " * 80)
        self._exchange(w, "thanks", "Any time.")
        w._tab_buttons[0].click()
        for _ in range(20):
            qapp.processEvents()
        bar = w._reading_scroll.verticalScrollBar()
        assert bar.maximum() > 0, "a long answer should scroll"
        assert bar.value() == 0, "it should open at its first line"
        w.close()

    def _wrapped_on_show(self, w):
        from PyQt6.QtWidgets import QLabel
        return [label for label in w._reading_box.findChildren(QLabel)
                if label.isVisibleTo(w._reading_box) and label.wordWrap()]

    def test_every_word_of_a_long_exchange_can_be_scrolled_to(self, qapp):
        # 2026-09-13: Mo's question and the answer were both cut off mid-line
        # at 93px each when they needed ~155, and the panel scrolled 12px.
        w = _make_cockpit(qapp)
        w.setGeometry(0, 0, 1536, 816)
        w.show()
        heard = ("Ok, let's go one by one. First one, the October deadline was my "
                 "graduation, which is on the 4th of October. That's why I was talking "
                 "about October and you wanted the deadline. Class schedule, I don't "
                 "need it anymore because I finished. Todoist, keep it off for now.")
        answer = ("Locked in — October 4th for graduation, no class schedule needed "
                  "anymore since you're done, and Todoist stays off the list till your "
                  "days actually have a shape to track. Notion can wait as well, till "
                  "you need somewhere to put the bigger projects. Anything else?")
        self._exchange(w, heard, answer)
        for _ in range(60):
            qapp.processEvents()
        for label in self._wrapped_on_show(w):
            assert label.height() >= label.heightForWidth(label.width()),                 f"clipped: {label.text()[:30]!r}"
        bar = w._reading_scroll.verticalScrollBar()
        viewport = w._reading_scroll.viewport().height()
        assert bar.maximum() + viewport >= sum(
            label.heightForWidth(label.width()) for label in self._wrapped_on_show(w))
        w.close()

    def test_a_short_answer_sits_right_under_the_question(self, qapp):
        w = _make_cockpit(qapp)
        w.setGeometry(0, 0, 1536, 816)
        w.show()
        self._exchange(w, "thanks", "Any time, Mo.")
        for _ in range(60):
            qapp.processEvents()
        said, reply = self._wrapped_on_show(w)[:2]
        gap = reply.mapTo(w, reply.rect().topLeft()).y() -             said.mapTo(w, said.rect().bottomLeft()).y()
        assert gap < 30, f"the answer floats {gap}px below the question"
        w.close()

    def test_escape_clears_the_tabs(self, qapp):
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QKeyEvent
        from core import staging
        staging.reset()
        w = _make_cockpit(qapp)
        self._exchange(w, "first question", "first answer")
        w.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape,
                                  Qt.KeyboardModifier.NoModifier))
        assert w._tab_buttons == []
        assert w._tabs_layout.count() == 0
        w.close()


class TestTopic:
    @pytest.mark.parametrize("heard,topic", [
        ("give me my daily briefing", "Daily briefing"),
        ("what's the weather tomorrow?", "Weather tomorrow"),
        ("Hey Fager, what's on my calendar today?", "Calendar today"),
        ("Can you send an email to Ahmed please", "Send email Ahmed"),
        ("play Estanna by Fares Sokkar on Spotify", "Play Estanna Fares"),
        ("Thanks.", "Thanks"),
        ("I want you to open YouTube and play the first video", "Open YouTube play"),
    ])
    def test_it_names_the_question_in_a_few_words(self, heard, topic):
        from ui.cockpit import _topic
        assert _topic(heard) == topic

    @pytest.mark.parametrize("heard,topic", [
        # Mo's own words from the logs, where filler used to crowd out the topic
        ("Now I want you to open YouTube and play the first video", "Open YouTube play"),
        ("and tell me what's on my calendar and the review", "Calendar review"),
        ("No, it's by Ferris Sokhar and someone else", "Ferris Sokhar someone"),
        ("I'm trying the new transcript, tell me how it works", "Trying new transcript"),
    ])
    def test_everyday_filler_does_not_crowd_out_the_topic(self, heard, topic):
        from ui.cockpit import _topic
        assert _topic(heard) == topic

    def test_a_long_name_drops_whole_words_not_half_of_one(self):
        from ui.cockpit import _topic
        assert _topic("Is everything working alright?") == "Everything working"

    def test_one_overlong_word_is_cut_short(self):
        from ui.cockpit import _topic
        from ui.cockpit import _TOPIC_MAX
        topic = _topic("supercalifragilisticexpialidocious")
        assert len(topic) <= _TOPIC_MAX and topic.endswith("…")

    def test_a_repeated_word_is_named_once(self):
        from ui.cockpit import _topic
        assert _topic("Yes, I help! Yes, I help!") == "Help"

    def test_nothing_but_filler_names_nothing(self):
        from ui.cockpit import _topic
        assert _topic("hey fager, can you please") == ""


class TestNeverWiderThanTheScreen:
    """Mo's screen is 1536 wide. The old stage's heard line never wrapped, so
    one long sentence made the window 2007px wide and the whole Cockpit slid
    over until a restart. Nothing said, answered or reported may do that."""

    URL = ("https://www.youtube.com/watch?v=dQw4w9WgXcQ"
           "&list=PLx0sYbCqOb8TBPRdmBHs5Iftvv9TPboYG&index=4")
    LOOP = ("I'm going to get a check on my calendar, and I'm going to get a check "
            "on my calendar, and I'm going to get a check on my calendar today")

    def _min_width(self, qapp, w):
        for _ in range(20):
            qapp.processEvents()
        return w.minimumSizeHint().width()

    def test_a_long_sentence_does_not_widen_the_window(self, qapp):
        w = _make_cockpit(qapp)
        w.on_state_update("processing", self.LOOP, "")
        w.on_state_update("speaking", self.LOOP, self.LOOP)
        assert self._min_width(qapp, w) <= 1280
        w.close()

    def test_a_long_unbroken_error_does_not_widen_the_window(self, qapp):
        w = _make_cockpit(qapp)
        w.on_error("Pipeline error: " + "x" * 240)
        assert self._min_width(qapp, w) <= 1280
        w.close()

    def test_a_link_in_an_answer_wraps_inside_the_panel(self, qapp):
        w = _make_cockpit(qapp)
        w.setGeometry(0, 0, 1536, 816)
        w.show()
        w.on_state_update("processing", "open the video", "")
        w.on_state_update("speaking", "open the video", f"Here it is: {self.URL}")
        self._min_width(qapp, w)
        assert w._reading_box.minimumSizeHint().width() <= w._reading_scroll.viewport().width()
        w.close()


class TestReadableTranscript:
    """The transcript is the thing to read on this surface, so it is set
    large and heavy enough to read from a normal sitting distance."""

    def _exchange_labels(self, w):
        from PyQt6.QtWidgets import QLabel
        w.on_state_update("processing", "what's on my calendar", "")
        w.on_state_update("speaking", "what's on my calendar", "Gym at seven.")
        return {label.text(): label.styleSheet()
                for label in w._reading_box.findChildren(QLabel)}

    @staticmethod
    def _px(style):
        import re
        return int(re.search(r"font-size:\s*(\d+)px", style).group(1))

    def test_what_mo_said_is_bold_and_large(self, qapp):
        import re
        w = _make_cockpit(qapp)
        style = self._exchange_labels(w)["what's on my calendar"]
        assert self._px(style) >= 15
        assert int(re.search(r"font-weight:\s*(\d+)", style).group(1)) >= 600
        w.close()

    def test_the_answer_is_large(self, qapp):
        import re
        w = _make_cockpit(qapp)
        style = self._exchange_labels(w)["Gym at seven."]
        assert self._px(style) >= 16
        assert int(re.search(r"font-weight:\s*(\d+)", style).group(1)) >= 500
        w.close()

    def test_the_link_text_itself_is_unchanged_for_copying(self, qapp):
        # Break points are zero-width: the words read and copy as written.
        w = _make_cockpit(qapp)
        w.on_state_update("processing", "q", "")
        w.on_state_update("speaking", "q", "see https://a.example.com/very/long/path_name")
        from PyQt6.QtWidgets import QLabel
        texts = [label.text().replace("​", "")
                 for label in w._reading_box.findChildren(QLabel)]
        assert "see https://a.example.com/very/long/path_name" in texts
        w.close()


class TestArrows:
    """‹ › under the sphere step through the conversation in the rail."""

    def _exchange(self, w, heard, answer):
        w.on_state_update("listening", "", "")
        w.on_state_update("processing", heard, "")
        w.on_state_update("speaking", heard, answer)

    def _focused(self, w):
        return [button.isChecked() for button in w._tab_buttons]

    def test_they_sit_under_the_sphere_not_in_the_rail(self, qapp):
        w = _make_cockpit(qapp)
        for widget in (w._scrub_prev, w._scrub_value, w._scrub_next):
            assert not w._reading_panel.isAncestorOf(widget)
        w.close()

    def test_with_nothing_said_they_are_harmless(self, qapp):
        w = _make_cockpit(qapp)
        assert w._scrub_value.text() == "—"
        w._scrub_prev.click()
        w._scrub_next.click()
        assert w._scrub_value.text() == "—"
        w.close()

    def test_they_step_through_the_exchanges_and_stop_at_the_ends(self, qapp):
        w = _make_cockpit(qapp)
        for n in range(3):
            self._exchange(w, f"question {n}", f"answer {n}")
        assert w._scrub_value.text() == "3 / 3"
        w._scrub_prev.click()
        assert w._scrub_value.text() == "2 / 3"
        for _ in range(5):
            w._scrub_prev.click()
        assert w._scrub_value.text() == "1 / 3"
        for _ in range(5):
            w._scrub_next.click()
        assert w._scrub_value.text() == "3 / 3"
        w.close()

    def test_the_exchange_they_point_at_is_marked_in_the_rail(self, qapp):
        w = _make_cockpit(qapp)
        for n in range(3):
            self._exchange(w, f"question {n}", f"answer {n}")
        assert self._focused(w) == [False, False, True]
        w._scrub_prev.click()
        assert self._focused(w) == [False, True, False]
        w.close()

    def test_a_new_question_takes_the_focus_to_itself(self, qapp):
        w = _make_cockpit(qapp)
        for n in range(3):
            self._exchange(w, f"question {n}", f"answer {n}")
        w._scrub_prev.click()
        w._scrub_prev.click()
        w.on_state_update("listening", "", "")
        w.on_state_update("processing", "question 3", "")
        assert w._scrub_value.text() == "4 / 4"
        assert self._focused(w) == [False, False, False, True]
        w.close()

    def test_an_answer_landing_keeps_the_mark(self, qapp):
        w = _make_cockpit(qapp)
        self._exchange(w, "question", "answer")
        w.on_state_update("interrupted", "question", "answer")
        assert self._focused(w) == [True]
        w.close()

    def test_closing_resets_them(self, qapp):
        w = _make_cockpit(qapp)
        self._exchange(w, "question", "answer")
        w._close()
        assert w._scrub_value.text() == "—"
        w.close()

    def test_under_the_sphere_only_the_arrows_and_the_pill(self, qapp):
        # The reel has ‹ › and the view pill there and nothing else; the
        # ledger stays on L and the SKILLS button, the keys on ?.
        from PyQt6.QtWidgets import QLabel, QPushButton
        w = _make_cockpit(qapp)
        texts = [x.text() for x in w.findChildren((QLabel, QPushButton))]
        assert "LEDGER" not in texts
        assert not any("ESC CLOSE" in t for t in texts)
        w.close()

    def test_the_view_pill_asks_for_the_command_center(self, qapp):
        w = _make_cockpit(qapp)
        seen = []
        w.knowledge_requested.connect(lambda: seen.append(True))
        w._view_pill.click()
        assert seen == [True]
        w.close()


class TestRails:
    def test_the_skills_count_rides_on_the_skills_button(self, qapp, tmp_path, monkeypatch):
        # The reel's panel is the list and its buttons; the count used to take
        # a tall readout of its own under them.
        import json
        import ui.overlay as overlay_mod
        from PyQt6.QtWidgets import QLabel
        path = tmp_path / "settings.json"
        path.write_text(json.dumps({"skills_disabled": ["gmail", "browser"]}), encoding="utf-8")
        monkeypatch.setattr(overlay_mod, "_SETTINGS_FILE", path)
        w = _make_cockpit(qapp)
        w._refresh_readouts()
        assert w._skills_btn.text() == "SKILLS  4/6"
        assert "SKILLS ONLINE" not in [l.text() for l in w.findChildren(QLabel)]
        w.close()

    def test_the_automations_panel_ends_at_its_buttons(self, qapp):
        w = _make_cockpit(qapp)
        w._refresh_readouts()
        w._show_window()
        for _ in range(40):
            qapp.processEvents()
        panel = w._skills_btn.parentWidget()
        bottom_of_buttons = w._skills_btn.mapTo(panel, w._skills_btn.rect().bottomLeft()).y()
        assert panel.height() - bottom_of_buttons <= 24,             f"{panel.height() - bottom_of_buttons}px of panel below the buttons"
        w.close()

    def test_automations_never_render_an_empty_rail(self, qapp):
        w = _make_cockpit(qapp)
        w._refresh_rails()
        assert w._auto_list.count() >= 1
        w.close()


class TestNormalWindow:
    """A normal window, not full screen: it sits above the taskbar, has a dark
    title bar of its own, and remembers where it was left."""

    def test_it_opens_smaller_than_the_screen_and_above_the_taskbar(self, qapp):
        from PyQt6.QtWidgets import QApplication
        w = _make_cockpit(qapp)
        w._show_window()
        area = QApplication.primaryScreen().availableGeometry()
        assert not w.isFullScreen()
        assert area.contains(w.frameGeometry())
        assert w.width() < area.width() or w.height() < area.height()
        w.close()

    def test_it_can_never_be_shrunk_past_what_the_layout_needs(self, qapp):
        w = _make_cockpit(qapp)
        w._show_window()
        assert w.minimumWidth() >= w.minimumSizeHint().width()
        assert w.minimumHeight() >= w.minimumSizeHint().height()
        w.close()

    def test_the_title_bar_has_minimise_maximise_and_close(self, qapp):
        w = _make_cockpit(qapp)
        assert {w._btn_min.toolTip(), w._btn_max.toolTip(), w._btn_close.toolTip()}             == {"Minimise", "Maximise", "Close"}
        assert w._title_bar.isAncestorOf(w._btn_close)
        w.close()

    def test_close_hides_it_but_el_fager_keeps_running(self, qapp):
        w = _make_cockpit(qapp)
        w._show_window()
        w._btn_close.click()
        assert w.isHidden()
        w.close()

    def test_minimise_keeps_the_conversation(self, qapp):
        w = _make_cockpit(qapp)
        w._show_window()
        w.on_state_update("processing", "what's the weather", "")
        w.on_state_update("speaking", "what's the weather", "Sunny.")
        w._btn_min.click()
        for _ in range(20):
            qapp.processEvents()
        assert w.isMinimized()
        assert len(w._tab_buttons) == 1
        w.close()

    def test_maximise_toggles(self, qapp):
        w = _make_cockpit(qapp)
        w._show_window()
        w._btn_max.click()
        for _ in range(20):
            qapp.processEvents()
        assert w.isMaximized()
        w._btn_max.click()
        for _ in range(20):
            qapp.processEvents()
        assert not w.isMaximized()
        w.close()

    def test_it_reopens_where_it_was_left(self, qapp, settings_file):
        import json
        w = _make_cockpit(qapp)
        w._show_window()
        w.setGeometry(120, 90, 1200, 720)
        w._btn_close.click()
        saved = json.loads(settings_file.read_text(encoding="utf-8"))["cockpit_geometry"]
        assert saved == [120, 90, 1200, 720]
        w.close()

        again = _make_cockpit(qapp)
        again._show_window()
        assert [again.x(), again.y(), again.width(), again.height()] == [120, 90, 1200, 720]
        again.close()

    def test_a_saved_spot_off_screen_is_ignored(self, qapp, settings_file):
        import json
        from PyQt6.QtWidgets import QApplication
        settings_file.write_text(json.dumps({"cockpit_geometry": [9000, 9000, 1200, 720]}),
                                 encoding="utf-8")
        w = _make_cockpit(qapp)
        w._show_window()
        assert QApplication.primaryScreen().availableGeometry().contains(w.frameGeometry())
        w.close()
