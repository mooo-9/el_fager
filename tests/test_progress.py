"""Tests for the step ledger — what a turn is actually doing.

The ledger is written from the brain's single tool dispatch, so these pin
the recording rules: a new turn clears the last one, a failed tool goes red
rather than silently vanishing, and tools are tinted by the skill they
belong to.
"""
import pytest

from core import progress


@pytest.fixture(autouse=True)
def clean():
    progress.reset()
    yield
    progress.reset()


class TestRecording:
    def test_a_step_is_active_until_it_finishes(self):
        i = progress.step_started("list_events")
        assert progress.steps()[i].status == "active"
        progress.step_finished(i, ok=True)
        assert progress.steps()[i].status == "done"

    def test_a_failed_tool_goes_red_not_missing(self):
        i = progress.step_started("prepare_whatsapp_message")
        progress.step_finished(i, ok=False)
        assert progress.steps()[i].status == "failed"

    def test_a_new_turn_clears_the_previous_one(self):
        progress.step_started("list_events")
        progress.begin_turn()
        assert progress.steps() == []

    def test_the_active_label_is_what_it_is_doing_now(self):
        a = progress.step_started("list_events")
        progress.step_started("search_messages")
        progress.step_finished(a, ok=True)
        assert progress.active_label() == "search messages"

    def test_no_active_label_once_everything_lands(self):
        i = progress.step_started("list_events")
        progress.step_finished(i, ok=True)
        assert progress.active_label() is None

    def test_the_ledger_does_not_grow_without_bound(self):
        for n in range(30):
            progress.step_started(f"tool_{n}")
        assert len(progress.steps()) <= 12


class TestSkillTints:
    @pytest.mark.parametrize("tool,skill", [
        ("prepare_whatsapp_message", "whatsapp"),
        ("confirm_whatsapp_send", "whatsapp"),
        ("send_message", "gmail"),
        ("list_events", "calendar"),
        ("delete_event", "calendar"),
        ("add_todoist_task", "todoist"),
        ("web_search", "browser"),
    ])
    def test_tools_carry_their_skill(self, tool, skill):
        assert progress.skill_for(tool) == skill

    def test_the_apps_own_utilities_have_no_skill(self):
        assert progress.skill_for("get_clipboard") is None

    def test_every_skill_has_a_tint_in_the_tokens(self):
        from ui import tokens
        for skill in set(progress._SKILLS.values()):
            assert skill in tokens.SKILL_TINT

    def test_labels_read_as_plain_words(self):
        assert progress.label_for("prepare_whatsapp_message") == "prepare whatsapp message"


class TestSubscribers:
    def test_surfaces_are_notified_as_the_turn_moves(self):
        seen = []
        progress.subscribe(lambda: seen.append(1))
        progress.begin_turn()
        i = progress.step_started("list_events")
        progress.step_finished(i, ok=True)
        assert len(seen) == 3

    def test_a_broken_surface_cannot_break_a_turn(self):
        def explode():
            raise RuntimeError("gone")
        progress.subscribe(explode)
        i = progress.step_started("list_events")     # must not raise
        progress.step_finished(i, ok=True)
        assert progress.steps()[i].status == "done"


class TestBrainWiring:
    def test_the_dispatch_records_a_step(self, monkeypatch):
        """The brain funnels every tool through _dispatch_tool — that is the
        one place the ledger is written, so it must not be bypassed."""
        import core.brain as brain_mod
        import inspect
        src = inspect.getsource(brain_mod.Brain._dispatch_tool)
        assert "progress.step_started" in src
        assert "progress.step_finished" in src
