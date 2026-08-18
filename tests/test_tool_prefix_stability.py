"""The tools array is inside the cached prompt prefix.

Anthropic's cache prefix runs tools -> system -> messages, and the only
cache_control breakpoint sits on the system block — so the tools array is
cached along with it, and any change to that array throws the whole ~20k-token
prefix away.

It used to be recomputed inside the tool-iteration loop, so a turn that made
three tool calls could pay three cache writes. These pin that it is selected
once per turn and stays stable for as long as it honestly can.
"""
from unittest.mock import MagicMock

import pytest

from core.brain import Brain


@pytest.fixture
def brain(monkeypatch):
    b = Brain.__new__(Brain)
    b.conversation_history = []
    b._turn_tool_names = None
    b._offline_mode = False
    b.memory = None
    b.profile = {}
    b._logger = None
    return b


def _names(tools):
    return {t["name"] for t in tools}


class TestSelectedOncePerTurn:
    def test_chat_selects_the_tool_list_a_single_time(self, monkeypatch):
        """The regression that started this: _select_tools sat inside the
        `for _iteration in range(...)` loop, so a three-tool turn re-sent a
        freshly computed array three times."""
        import core.brain as brain_mod

        calls = []
        real = brain_mod._select_tools

        def counting(message, history=None):
            calls.append(message)
            return real(message, history)

        monkeypatch.setattr(brain_mod, "_select_tools", counting)

        b = Brain.__new__(Brain)
        b.conversation_history = []
        b._turn_tool_names = None
        b._offline_mode = False
        b.memory = None
        b.profile = {}
        b._logger = None
        b._model = "m"
        b._fast_model = "f"
        b._fast_path_enabled = False

        # Two tool round trips, then a final answer.
        tool_block = MagicMock(type="tool_use", name="x", id="1", input={})
        tool_block.name = "get_weather"
        responses = [
            MagicMock(stop_reason="tool_use", content=[tool_block],
                      usage=MagicMock(input_tokens=1, output_tokens=1)),
            MagicMock(stop_reason="tool_use", content=[tool_block],
                      usage=MagicMock(input_tokens=1, output_tokens=1)),
            MagicMock(stop_reason="end_turn",
                      content=[MagicMock(type="text", text="done")],
                      usage=MagicMock(input_tokens=1, output_tokens=1)),
        ]
        sent_tools = []

        def fake_create(_source, **kwargs):
            sent_tools.append(kwargs["tools"])
            return responses.pop(0)

        monkeypatch.setattr(b, "_create_message", fake_create)
        monkeypatch.setattr(b, "_build_system", lambda mc="": [])
        monkeypatch.setattr(b, "_dispatch_tool", lambda *a, **k: "ok")

        b.chat("what is the weather in cairo")

        assert len(calls) == 1, "tool selection ran per iteration, not per turn"
        assert len(sent_tools) == 3
        assert all(_names(s) == _names(sent_tools[0]) for s in sent_tools), \
            "the tools array changed between iterations of one turn"


class TestStableAcrossAConversation:
    def test_a_second_turn_reuses_the_first_turns_array(self, brain):
        first = brain._tools_for_turn("what is the weather in cairo", [])
        second = brain._tools_for_turn("what is the weather in cairo", [])
        assert _names(first) == _names(second)

    def test_a_new_group_is_added_and_nothing_is_dropped(self, brain):
        weather = _names(brain._tools_for_turn("what is the weather", []))
        both = _names(brain._tools_for_turn("check my unread email", []))
        assert weather <= both, "an earlier turn's tools disappeared mid-conversation"
        assert both > weather, "the new turn's group was never added"

    def test_resetting_the_conversation_starts_over(self, brain):
        brain._tools_for_turn("check my unread email", [])
        wide = len(brain._turn_tool_names)
        brain.reset_conversation()
        assert brain._turn_tool_names is None
        brain._tools_for_turn("say hello", [])
        assert len(brain._turn_tool_names) < wide

    def test_order_is_stable_because_the_cache_key_is_the_serialised_array(self, brain):
        # The same set in a different order is a different prefix, so the list
        # is rebuilt from the source order rather than from a set.
        brain._tools_for_turn("check my unread email", [])
        a = [t["name"] for t in brain._tools_for_turn("what is the weather", [])]
        b = [t["name"] for t in brain._tools_for_turn("what is the weather", [])]
        assert a == b


class TestSettingsStillWin:
    def test_disabling_a_skill_takes_effect_on_an_active_conversation(
            self, brain, monkeypatch):
        import core.brain as brain_mod
        before = _names(brain._tools_for_turn("check my unread email", []))
        assert "list_emails" in before

        monkeypatch.setattr(brain_mod, "_disabled_tool_names",
                            lambda: {"list_emails"})
        after = _names(brain._tools_for_turn("check my unread email", []))
        assert "list_emails" not in after, \
            "a tool disabled mid-conversation survived in the accumulated set"
