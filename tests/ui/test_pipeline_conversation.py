"""Conversation-mode tests for PipelineWorker: multi-turn context, follow-up
windows, end phrases, and single-turn text input. run() is called directly
(synchronously) with fakes — no mic, no Claude, no TTS."""
import numpy as np
import pytest

from core.pipeline import (
    FOLLOWUP_WINDOW_SEC,
    PipelineWorker,
    _is_end_phrase,
    _pop_sentences,
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

    def chat(self, text, memory_context=None, on_text=None):
        self.chats.append(text)
        return f"reply to: {text}"

    def reset_conversation(self):
        self.resets += 1


class FakeVoiceOut:
    def __init__(self):
        self.spoken = []

    # should_stop is the barge-in hook: the pipeline hands it to every speak
    # call so an utterance can be cut mid-word.
    def speak(self, text, should_stop=None):
        self.spoken.append(text)
        return False

    def speak_stream(self, sentences, should_stop=None):
        for s in sentences:
            self.spoken.append(s)
        return False


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


class StreamingFakeBrain(FakeBrain):
    """Streams the reply through on_text in arbitrary-sized deltas, the way
    the real Brain does with the Anthropic streaming API."""

    def chat(self, text, memory_context=None, on_text=None):
        self.chats.append(text)
        if on_text is not None:
            for delta in ("First sen", "tence. Sec", "ond sentence."):
                on_text(delta)
        return "First sentence. Second sentence."


class TestStreamingSpeech:
    def test_streamed_sentences_spoken_in_order_without_duplicate(self, qapp):
        w = PipelineWorker(
            voice_in=FakeVoiceIn(["hello"]),
            brain=StreamingFakeBrain(),
            voice_out=FakeVoiceOut(),
            memory=FakeMemory(),
        )
        w.run()
        # Sentence 1 streams as soon as its boundary arrives; the tail is
        # flushed after chat() returns. The full reply is NOT re-spoken.
        assert w.voice_out.spoken == ["First sentence.", "Second sentence."]

    def test_answer_text_grows_as_each_sentence_is_spoken(self, qapp):
        w = PipelineWorker(
            voice_in=FakeVoiceIn(["hello"]),
            brain=StreamingFakeBrain(),
            voice_out=FakeVoiceOut(),
            memory=FakeMemory(),
        )
        seen = []
        w.answer_text.connect(seen.append)
        w.run()
        assert seen == ["First sentence.", "First sentence. Second sentence."]

    def test_non_streaming_brain_falls_back_to_full_speak(self, qapp):
        w = _worker(["hello"])
        w.run()
        assert w.voice_out.spoken == ["reply to: hello"]


class TestPopSentences:
    def test_splits_on_period_before_space(self):
        state = {"buf": "One done. Two in progress"}
        assert _pop_sentences(state) == ["One done."]
        assert state["buf"] == "Two in progress"

    def test_decimal_number_not_split(self):
        state = {"buf": "It costs 3.5 dollars"}
        assert _pop_sentences(state) == []
        assert state["buf"] == "It costs 3.5 dollars"

    def test_question_mark(self):
        state = {"buf": "How are you? Fine"}
        assert _pop_sentences(state) == ["How are you?"]

    def test_newline_is_a_boundary(self):
        state = {"buf": "line one\nline two"}
        assert _pop_sentences(state) == ["line one"]
        assert state["buf"] == "line two"


class TestEndPhrase:
    @pytest.mark.parametrize("text", ["thanks", "Thank you.", "stop", "bye", "that's all"])
    def test_end_phrases(self, text):
        assert _is_end_phrase(text) is True

    @pytest.mark.parametrize("text", [
        "thanks to the fed the market dropped today what happened",
        "what's the weather",
    ])
    def test_normal_speech_is_not_end(self, text):
        assert _is_end_phrase(text) is False


class TestThePipelineDucksWhileItRecords:
    def test_audio_is_low_during_recording_and_back_before_thinking(self, monkeypatch):
        import numpy as np
        from core import ducking

        state = {"ducked": False}
        seen = {}

        class Ducked:
            def __enter__(self):
                state["ducked"] = True

            def __exit__(self, *exc):
                state["ducked"] = False
                return False

        monkeypatch.setattr(ducking, "ducked", Ducked)

        class VoiceIn:
            def __init__(self):
                self.left = 1

            def is_ready(self):
                return True

            def record_audio(self, start_timeout_sec=None):
                seen.setdefault("record", []).append(state["ducked"])
                if self.left:
                    self.left -= 1
                    return np.ones(16000, dtype=np.float32)
                return None

            def transcribe(self, audio):
                seen["transcribe"] = state["ducked"]
                return "what's the weather"

            def stop_recording(self):
                pass

        worker = PipelineWorker(VoiceIn(), FakeBrain(), FakeVoiceOut(), FakeMemory())
        worker.run()
        assert seen["record"] and all(seen["record"]), "recording was not ducked"
        assert seen["transcribe"] is False, "music should be back before thinking"
