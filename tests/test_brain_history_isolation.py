"""Tests for chat history isolation and multi-turn tool selection.

Covers the review findings: background callers must not touch the shared
interactive conversation (thread contamination + unbounded growth), and
_select_tools must keep tool groups active for conversational follow-ups.
"""
from unittest.mock import patch

from core.brain import Brain, _select_tools


def _make_brain():
    return Brain(profile={})


def _end_turn(text: str):
    from unittest.mock import MagicMock
    block = MagicMock()
    block.type = "text"
    block.text = text
    response = MagicMock()
    response.stop_reason = "end_turn"
    response.content = [block]
    return response


class TestBackgroundIsolation:
    def test_chat_background_never_touches_shared_history(self):
        brain = _make_brain()
        with patch.object(brain.client.messages, "create",
                          return_value=_end_turn("task done")):
            result = brain.chat_background("check NVDA price")
        assert result == "task done"
        assert brain.conversation_history == []

    def test_interactive_chat_still_accumulates(self):
        brain = _make_brain()
        with patch.object(brain.client.messages, "create",
                          side_effect=[_end_turn("a"), _end_turn("b")]):
            brain.chat("hello")
            brain.chat("again")
        roles = [m["role"] for m in brain.conversation_history]
        assert roles == ["user", "assistant", "user", "assistant"]

    def test_background_between_interactive_turns_leaves_no_trace(self):
        """A proactive task firing mid-conversation must not splice its turns
        into Mo's conversation context."""
        brain = _make_brain()
        with patch.object(brain.client.messages, "create",
                          side_effect=[_end_turn("hi"), _end_turn("bg"),
                                       _end_turn("follow-up")]):
            brain.chat("hello")
            brain.chat_background("autonomous task: check something")
            brain.chat("and then?")
        contents = [m["content"] for m in brain.conversation_history]
        assert "autonomous task: check something" not in contents
        assert "bg" not in contents

    def test_cut_off_branch_records_and_logs(self):
        from unittest.mock import MagicMock
        brain = _make_brain()
        response = MagicMock()
        response.stop_reason = "max_tokens"  # neither end_turn nor tool_use
        response.content = []
        with patch.object(brain.client.messages, "create",
                          return_value=response):
            result = brain.chat("hello")
        assert "cut off" in result.lower()
        assert brain.conversation_history[-1]["role"] == "assistant"


class TestMultiTurnToolSelection:
    def _names(self, tools):
        return {t["name"] for t in tools}

    def test_followup_keeps_finance_group_active(self):
        history = [
            {"role": "user", "content": "any unpaid invoices?"},
            {"role": "assistant", "content": "Two invoices are unpaid."},
        ]
        # "and who owes the most?" has no finance trigger keyword itself
        names = self._names(_select_tools("and who owes the most?", history))
        assert "list_invoices" in names

    def test_no_history_matches_old_behavior(self):
        with_trigger = self._names(_select_tools("any unpaid invoices?"))
        without = self._names(_select_tools("and who owes the most?"))
        assert "list_invoices" in with_trigger
        assert "list_invoices" not in without

    def test_non_string_content_blocks_ignored(self):
        history = [{"role": "user", "content": [{"type": "tool_result"}]}]
        _select_tools("hello", history)  # must not raise
