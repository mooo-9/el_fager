"""Conversation-mode tests for PipelineWorker: multi-turn context, follow-up
windows, end phrases, and single-turn text input. run() is called directly
(synchronously) with fakes — no mic, no Claude, no TTS."""
import numpy as np
import pytest

from core.pipeline import (
    FOLLOWUP_WINDOW_SEC,
    PipelineWorker,
    _is_end_phrase,
)


class FakeVoiceIn:
    """Yields queued utterances, then silence (None). Records the
    start_timeout_sec passed to each record_audio call."""

    def __init__(self, utterances):
        self._utterances = list(utterances)
        self.timeouts = []

    def is_ready(self):
        return True

    def record_audio(self, start_timeout_sec=None):
        self.timeouts.append(start_timeout_sec)
        if self._utterances:
            return np.ones(16000, dtype=np.float32)
        return None

    def transcribe(self, audio):
        return self._utterances.pop(0)


class FakeBrain:
    def __init__(self):
        self.chats = []
        self.resets = 0

    def chat(self, text, memory_context=None):
        self.chats.append(text)
        return f"reply to: {text}"

    def reset_conversation(self):
        self.resets += 1


class FakeVoiceOut:
    def __init__(self):
        self.spoken = []

    def speak(self, text):
        self.spoken.append(text)


class FakeMemory:
    def get_recent_context(self, text):
        return ""

    def store_conversation_summary(self, transcript, response):
        pass


def _worker(utterances, text_input=None):
    return PipelineWorker(
        voice_in=FakeVoiceIn(utterances),
        brain=FakeBrain(),
        voice_out=FakeVoiceOut(),
        memory=FakeMemory(),
        text_input=text_input,
    )


class TestConversationMode:
    def test_multi_turn_keeps_context_until_silence(self, qapp):
        w = _worker(["what's NVDA at", "and its P/E ratio?"])
        w.run()
        # Both turns hit the same brain conversation; reset only at the end
        assert w.brain.chats == ["what's NVDA at", "and its P/E ratio?"]
        assert w.brain.resets == 1
        assert len(w.voice_out.spoken) == 2

    def test_first_listen_has_no_timeout_followups_do(self, qapp):
        w = _worker(["hello", "how are you"])
        w.run()
        # Turn 1: wait indefinitely (Mo pressed the hotkey / said wake word).
        # Turns 2+: bounded follow-up window.
        assert w.voice_in.timeouts[0] is None
        assert all(t == FOLLOWUP_WINDOW_SEC for t in w.voice_in.timeouts[1:])

    def test_end_phrase_stops_conversation_after_reply(self, qapp):
        w = _worker(["what time is it", "thanks", "SHOULD NEVER BE HEARD"])
        w.run()
        assert w.brain.chats == ["what time is it", "thanks"]
        assert w.brain.resets == 1

    def test_silence_on_first_turn_exits_quietly(self, qapp):
        w = _worker([])
        w.run()
        assert w.brain.chats == []
        assert w.voice_out.spoken == []

    def test_text_input_is_single_turn(self, qapp):
        w = _worker([], text_input="convert 5 km to miles")
        w.run()
        assert w.brain.chats == ["convert 5 km to miles"]
        assert w.brain.resets == 1
        # No mic activity for text input
        assert w.voice_in.timeouts == []


class TestEndPhrase:
    @pytest.mark.parametrize("text", ["thanks", "Thank you.", "خلاص", "bye", "that's all"])
    def test_end_phrases(self, text):
        assert _is_end_phrase(text) is True

    @pytest.mark.parametrize("text", [
        "thanks to the fed the market dropped today what happened",
        "what's the weather",
    ])
    def test_normal_speech_is_not_end(self, text):
        assert _is_end_phrase(text) is False
