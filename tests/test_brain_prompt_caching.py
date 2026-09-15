"""The system prompt is ~10k tokens and was re-processed on every API call.
These lock in the cache breakpoint and the once-per-turn tool selection."""
from unittest.mock import MagicMock, patch


def _make_brain():
    from core.brain import Brain
    return Brain(profile={})


def _end_turn_response(text="ok"):
    block = MagicMock()
    block.type = "text"
    block.text = text
    response = MagicMock()
    response.stop_reason = "end_turn"
    response.content = [block]
    return response


def _tool_use_response(name="list_facts", tool_id="t1"):
    block = MagicMock()
    block.type = "tool_use"
    block.name = name
    block.input = {}
    block.id = tool_id
    response = MagicMock()
    response.stop_reason = "tool_use"
    response.content = [block]
    return response


def _capture(brain, *responses, message="hello"):
    calls = []

    def _create(**kwargs):
        calls.append(kwargs)
        return responses[len(calls) - 1]

    with patch.object(brain.client.messages, "create", side_effect=_create):
        brain.chat(message)
    return calls


def test_static_system_prompt_carries_a_cache_breakpoint():
    from core.brain import SYSTEM_PROMPT
    calls = _capture(_make_brain(), _end_turn_response())
    system = calls[0]["system"]
    assert isinstance(system, list)
    assert system[0]["text"] == SYSTEM_PROMPT
    assert system[0]["cache_control"] == {"type": "ephemeral"}


def test_per_turn_context_stays_after_the_breakpoint():
    brain = _make_brain()
    brain.memory = MagicMock()
    brain.memory.format_facts_for_prompt.return_value = "Known fact: Mo likes tea."
    brain.memory.get_upcoming_deadlines.return_value = ""
    calls = _capture(brain, _end_turn_response())
    system = calls[0]["system"]
    assert len(system) == 2
    assert "Mo likes tea" in system[1]["text"]
    assert "cache_control" not in system[1]


def test_prefix_is_identical_across_tool_loop_iterations():
    calls = _capture(
        _make_brain(),
        _tool_use_response(),
        _end_turn_response(),
    )
    assert len(calls) == 2
    # A prefix that changes mid-loop would miss the cache on every iteration.
    assert calls[0]["system"] == calls[1]["system"]
    assert calls[0]["tools"] == calls[1]["tools"]
