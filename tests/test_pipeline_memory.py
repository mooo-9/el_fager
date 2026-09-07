"""Conversation history survives across exchanges.

Follow-ups ("and tomorrow?", "do that again") only work if the brain still
holds the previous turns when the next pipeline run starts.
"""
from unittest.mock import MagicMock

import pytest

# core.pipeline pulls in PyQt6, numpy and sounddevice. requirements-dev.txt
# deliberately omits the heavy runtime deps, so CI skips this the same way
# tests/_optional.py handles the rest; it runs for real on the target machine.
pipeline = pytest.importorskip(
    "core.pipeline",
    reason="needs PyQt6 + numpy + sounddevice (runtime deps, not in requirements-dev)",
)


def _worker(text: str):
    voice_in, brain, voice_out, memory = (MagicMock() for _ in range(4))
    brain.chat.return_value = "a reply"
    memory.get_recent_context.return_value = ""
    return pipeline.PipelineWorker(voice_in, brain, voice_out, memory, text_input=text)


class TestHistoryIsPreserved:
    def test_run_does_not_reset_the_conversation(self):
        w = _worker("what's the weather in Cairo?")
        w.run()
        w.brain.reset_conversation.assert_not_called()

    def test_second_exchange_still_does_not_reset(self):
        w = _worker("first")
        w.run()
        w.brain.reset_conversation.assert_not_called()
        w.text_input = "and tomorrow?"
        w.run()
        w.brain.reset_conversation.assert_not_called()
        assert w.brain.chat.call_count == 2

    def test_reply_is_still_stored_in_long_term_memory(self):
        w = _worker("remember this")
        w.run()
        w.memory.store_conversation_summary.assert_called_once_with("remember this", "a reply")
