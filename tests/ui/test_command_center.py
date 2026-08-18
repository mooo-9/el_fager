"""Tests for the Command Center.

Three properties of the design are load-bearing and easy to lose in a
refactor, so they are pinned here:

  * the 12-column grid, with each card in the cell the handoff gives it
  * exactly ONE action per card footer, and it goes through the same
    pipeline a spoken turn does
  * nothing costs open latency — cards and the briefing paint from cache
    before any network call, and a failed refresh keeps what was cached
"""
import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def cache_file(tmp_path, monkeypatch):
    import ui.command_center as cc
    path = tmp_path / "command_center_cache.json"
    path.write_text(json.dumps({
        "cards": {
            "calendar": {"text": "19:00  Gym — push day", "updated": "18:42"},
            "mail": {"text": "Stripe — payout failed", "updated": "18:40"},
        },
        "briefing": {"text": "Two things left today.", "updated": "18:42"},
    }), encoding="utf-8")
    monkeypatch.setattr(cc, "_CACHE_FILE", path)
    return path


@pytest.fixture(autouse=True)
def settings_file(tmp_path, monkeypatch):
    """The briefing TTL is read from settings, so keep it off the real file."""
    import ui.overlay as overlay_mod
    path = tmp_path / "settings.json"
    path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(overlay_mod, "_SETTINGS_FILE", path)
    return path


def _age_briefing(cache_file, minutes: float):
    """Backdate the cached briefing so staleness can be tested."""
    cache = json.loads(cache_file.read_text(encoding="utf-8"))
    written = datetime.now() - timedelta(minutes=minutes)
    cache["briefing"]["at"] = written.isoformat(timespec="seconds")
    cache_file.write_text(json.dumps(cache), encoding="utf-8")


@pytest.fixture(autouse=True)
def no_background_work(monkeypatch):
    """Keep the fetch/weather daemon threads out of the tests."""
    import ui.command_center as cc
    monkeypatch.setattr(cc.CommandCenterWindow, "refresh_cards", lambda self: None)
    monkeypatch.setattr(cc.CommandCenterWindow, "_refresh_weather", lambda self: None)


class FakeMemory:
    def __init__(self):
        self.facts = [{"id": "1", "category": "other", "content": "Coffee black",
                       "created_at": "2026-08-01"}]
        self.deleted = []

    def get_all_facts(self, category=None):
        return list(self.facts)

    def delete_fact(self, fact_id):
        self.deleted.append(fact_id)
        self.facts = [f for f in self.facts if f["id"] != fact_id]
        return "Forgotten"


def _window(memory=None, brain=None):
    from ui.command_center import CommandCenterWindow
    return CommandCenterWindow(MagicMock(), brain or MagicMock(), MagicMock(),
                               memory if memory is not None else FakeMemory())


class TestLayout:
    def test_the_grid_is_twelve_columns(self, qapp):
        from PyQt6.QtWidgets import QGridLayout
        w = _window()
        grid = next(g for g in w.findChildren(QGridLayout))
        assert grid.columnCount() == 12
        assert all(grid.columnStretch(c) == 1 for c in range(12))
        w.close()

    def test_each_card_sits_in_its_designed_cell(self, qapp):
        from PyQt6.QtWidgets import QGridLayout
        from ui.command_center import _CARD_CELLS
        w = _window()
        grid = next(g for g in w.findChildren(QGridLayout))
        placed = {}
        for i in range(grid.count()):
            item = grid.itemAt(i)
            row, column, _rowspan, span = grid.getItemPosition(i)
            placed[id(item.widget())] = (row, column, span)
        for card_id, cell in _CARD_CELLS.items():
            assert placed[id(w._cards[card_id])] == cell
        w.close()

    def test_the_knows_you_row_spans_the_whole_grid(self, qapp):
        from PyQt6.QtWidgets import QGridLayout
        w = _window()
        grid = next(g for g in w.findChildren(QGridLayout))
        spans = [grid.getItemPosition(i)[3] for i in range(grid.count())]
        assert 12 in spans
        w.close()

    def test_it_never_opens_narrower_than_the_grid_needs(self, qapp):
        w = _window()
        assert w.minimumWidth() >= 1100
        w.close()


class TestCardActions:
    def test_every_card_carries_exactly_one_action(self, qapp):
        from ui.command_center import _CARD_ACTIONS, _CARDS
        w = _window()
        for card_id, _title, _fetch in _CARDS:
            assert w._cards[card_id].action.text() == _CARD_ACTIONS[card_id][0]
        w.close()

    def test_a_say_action_goes_through_the_normal_pipeline(self, qapp):
        w = _window()
        with patch.object(w, "_dispatch") as dispatch:
            w._cards["calendar"].action.click()
        assert dispatch.call_count == 1
        assert "tomorrow" in dispatch.call_args[0][0].lower()
        w.close()

    def test_a_listen_action_opens_the_mic(self, qapp):
        w = _window()
        with patch.object(w, "_start_listening") as listen:
            w._cards["health"].action.click()
        listen.assert_called_once()
        w.close()

    def test_an_action_is_ignored_while_a_turn_is_running(self, qapp):
        w = _window()
        w._worker = MagicMock()
        w._worker.isRunning.return_value = True
        with patch.object(w, "_dispatch") as dispatch:
            w._cards["news"].action.click()
        dispatch.assert_not_called()
        w.close()


class TestCacheFirstPaint:
    def test_cards_paint_from_cache_before_any_fetch(self, qapp):
        w = _window()
        assert "Gym — push day" in w._card_texts["calendar"]
        assert w._cards["calendar"].meta.text() == "AS OF 18:42"
        w.close()

    def test_a_failed_refresh_keeps_the_cached_text(self, qapp):
        w = _window()
        w._on_card_ready("calendar", "[calendar error: no network]")
        assert "Gym — push day" in w._card_texts["calendar"]
        assert w._cards["calendar"].meta.text() == "REFRESH FAILED"
        w.close()

    def test_a_good_refresh_writes_the_cache_back(self, qapp, cache_file):
        w = _window()
        w._on_card_ready("tasks", "Book the dentist")
        saved = json.loads(cache_file.read_text(encoding="utf-8"))
        assert saved["cards"]["tasks"]["text"] == "Book the dentist"
        w.close()


class TestBriefing:
    def test_the_cached_prose_is_on_screen_in_the_first_frame(self, qapp):
        w = _window()
        assert w._briefing_label.text() == "Two things left today."
        w.close()

    def _settle(self, qapp, w):
        for _ in range(200):
            qapp.processEvents()
            if not w._briefing_pending:
                return

    def test_it_writes_from_the_cards_instead_of_re_fetching_the_day(self, qapp):
        # The whole point of the cost fix: one short call against text this
        # surface already has, not a tool loop that goes and fetches it again.
        brain = MagicMock()
        brain.synthesize.return_value = "Fresh synthesis."
        w = _window(brain=brain)
        w.refresh_briefing(force=True)
        self._settle(qapp, w)
        assert brain.chat.called is False
        assert brain.chat_background.called is False
        notes = brain.synthesize.call_args[0][0]
        assert "Gym — push day" in notes          # the calendar card's text
        assert w._briefing_label.text() == "Fresh synthesis."
        w.close()

    def test_a_fresh_cached_briefing_costs_nothing(self, qapp, cache_file):
        _age_briefing(cache_file, minutes=5)
        brain = MagicMock()
        w = _window(brain=brain)
        w.refresh_briefing()
        self._settle(qapp, w)
        assert brain.synthesize.called is False
        assert "5 MIN AGO" in w._briefing_state.text()
        w.close()

    def test_a_stale_one_is_rewritten(self, qapp, cache_file):
        _age_briefing(cache_file, minutes=90)
        brain = MagicMock()
        brain.synthesize.return_value = "Rewritten."
        w = _window(brain=brain)
        w.refresh_briefing()
        self._settle(qapp, w)
        assert brain.synthesize.called
        w.close()

    def test_yesterdays_briefing_is_never_fresh(self, qapp, cache_file):
        # A date change invalidates regardless of the clock: at 00:30 a
        # briefing from 21:00 is only 3.5 hours old but belongs to yesterday.
        _age_briefing(cache_file, minutes=24 * 60)
        w = _window()
        assert w._briefing_age() is None
        w.close()

    def test_a_ttl_of_zero_means_only_on_request(self, qapp, cache_file,
                                                 settings_file):
        settings_file.write_text(json.dumps({"briefing_ttl_minutes": 0}),
                                 encoding="utf-8")
        _age_briefing(cache_file, minutes=300)
        brain = MagicMock()
        w = _window(brain=brain)
        w.refresh_briefing()
        self._settle(qapp, w)
        assert brain.synthesize.called is False
        w.refresh_briefing(force=True)          # the Rewrite button
        self._settle(qapp, w)
        assert brain.synthesize.called
        w.close()

    def test_a_stale_briefing_waits_for_todays_cards(self, qapp, cache_file):
        # Writing while fetches are still in flight would describe the last
        # open's data — at the start of a day, yesterday's.
        _age_briefing(cache_file, minutes=90)
        brain = MagicMock()
        brain.synthesize.return_value = "Written after the cards."
        w = _window(brain=brain)
        w._pending = {"calendar"}
        w.refresh_briefing()
        assert brain.synthesize.called is False
        assert w._briefing_wanted is True
        w._on_card_ready("calendar", "19:00  Gym — push day")
        self._settle(qapp, w)
        assert brain.synthesize.called
        w.close()

    def test_a_dead_fetch_does_not_strand_the_briefing(self, qapp, cache_file):
        _age_briefing(cache_file, minutes=90)
        brain = MagicMock()
        brain.synthesize.return_value = "Written anyway."
        w = _window(brain=brain)
        w._pending = {"mail"}
        w.refresh_briefing()
        w._on_card_ready("mail", "[mail error: no network]")
        self._settle(qapp, w)
        assert brain.synthesize.called
        w.close()

    def test_a_failed_synthesis_keeps_the_last_one(self, qapp):
        w = _window()
        w._on_briefing_ready("")
        assert w._briefing_label.text() == "Two things left today."
        assert "LAST ONE" in w._briefing_state.text()
        w.close()

    def test_a_fresh_briefing_is_cached_with_a_full_timestamp(self, qapp,
                                                              cache_file):
        w = _window()
        w._on_briefing_ready("Gym in 73 minutes.")
        saved = json.loads(cache_file.read_text(encoding="utf-8"))
        assert saved["briefing"]["text"] == "Gym in 73 minutes."
        # "18:42" alone cannot tell yesterday from an hour ago.
        assert saved["briefing"]["at"].startswith(str(datetime.now().date()))
        w.close()

    def test_it_spends_nothing_when_there_is_nothing_to_write_about(
            self, qapp, cache_file):
        cache_file.write_text(json.dumps({"cards": {}}), encoding="utf-8")
        brain = MagicMock()
        w = _window(brain=brain)
        w.refresh_briefing(force=True)
        self._settle(qapp, w)
        assert brain.synthesize.called is False
        w.close()


class TestKnowsYou:
    def test_a_fact_chip_forgets_for_real(self, qapp):
        memory = FakeMemory()
        w = _window(memory=memory)
        w._forget_fact(memory.facts[0])
        assert memory.deleted == ["1"]
        assert w._facts_caption.text() == "LEARNED FACTS · 0"
        w.close()

    def test_the_count_is_the_real_count(self, qapp):
        w = _window()
        assert w._facts_caption.text() == "LEARNED FACTS · 1"
        w.close()

    def test_yes_on_a_proposal_saves_the_skill(self, qapp):
        w = _window()
        w._proposal = {"id": "abc", "example": "read me the news",
                       "count": 5, "days_seen": 4}
        with patch("tools.skill_tool.accept_skill_proposal",
                   return_value="Learned skill 'read me the news'.") as accept:
            w._accept_proposal()
        accept.assert_called_once_with("abc")
        assert "LEARNED SKILL" in w._proposal_receipt.text()
        w.close()

    def test_not_now_retires_the_proposal(self, qapp):
        w = _window()
        w._proposal = {"id": "abc", "example": "x", "count": 3, "days_seen": 3}
        with patch("tools.skill_tool.dismiss_skill_proposal",
                   return_value="dismissed") as dismiss:
            w._dismiss_proposal()
        dismiss.assert_called_once_with("abc")
        assert w._proposal is None
        w.close()


class TestExchange:
    def test_a_spoken_turn_is_not_bubbled_twice(self, qapp):
        w = _window()
        w._on_state_update("processing", "what's on my calendar", "")
        w._on_state_update("processing", "what's on my calendar", "")
        assert w._history.count(("user", "what's on my calendar")) == 1
        w.close()
