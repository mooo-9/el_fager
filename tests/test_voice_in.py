"""
Tests for voice_in hallucination guards: English-only decode + no-speech filter.

No audio hardware or Whisper models needed — _join_speech_segments is pure,
and the backend calls are exercised with fake models.
"""
import numpy as np
import pytest

from core.voice_in import (
    NO_SPEECH_MAX,
    TRANSCRIBE_LANGUAGE,
    VoiceInput,
    _join_speech_segments,
)


# ── _join_speech_segments ──────────────────────────────────────────────────

class TestJoinSpeechSegments:
    def test_english_passes_through(self):
        assert _join_speech_segments("en", [("hello", 0.0), ("world", 0.2)]) == "hello world"

    def test_non_english_returns_empty(self):
        # Noise hallucinated as another language must never reach the brain
        for lang in ("is", "ko", "cs", "he", "ru", "ar", "fr"):
            assert _join_speech_segments(lang, [("Það er um þig", 0.1)]) == ""

    @pytest.mark.parametrize("reported", [
        "en", "EN", "en-US", "en_GB", "eng",
        "English",      # Groq's verbose_json says this, not "en"
        "english",
        None, "",       # a backend that declines to say
    ])
    def test_every_way_a_backend_spells_english_is_accepted(self, reported):
        # Comparing the raw value against "en" made Groq's "English" fail this
        # check, which silently discarded every utterance it transcribed.
        assert _join_speech_segments(reported, [("hello", 0.1)]) == "hello"

    def test_regional_code_normalised(self):
        assert _join_speech_segments("en-US", [("hello", 0.1)]) == "hello"

    def test_none_language_and_none_prob_kept(self):
        # Backends without detection/segment detail must not lose text
        assert _join_speech_segments(None, [("hello", None)]) == "hello"

    def test_high_no_speech_prob_segments_dropped(self):
        segments = [("real speech", 0.1), ("hallucinated tail", 0.95)]
        assert _join_speech_segments("en", segments) == "real speech"

    def test_all_segments_non_speech_returns_empty(self):
        assert _join_speech_segments("en", [("noise", 0.9), ("more", NO_SPEECH_MAX)]) == ""

    def test_language_is_english(self):
        assert TRANSCRIBE_LANGUAGE == "en"


# ── Backends decode English, and only English ──────────────────────────────

class _FakeOpenAIWhisper:
    """Records the language it was asked for; echoes it back, as a real
    backend does when the language is forced."""

    def __init__(self, reports=None):
        self.calls = []
        self._reports = reports          # override what the backend claims

    def transcribe(self, audio, language=None, **kwargs):
        self.calls.append(language)
        return {
            "language": self._reports or language or "en",
            "text": "hello there",
            "segments": [{"text": "hello there", "no_speech_prob": 0.2}],
        }


class _FakeFasterInfo:
    def __init__(self, language):
        self.language = language


class _FakeFasterSegment:
    def __init__(self, text, no_speech_prob):
        self.text = text
        self.no_speech_prob = no_speech_prob


class _FakeFasterWhisper:
    def __init__(self, reports=None):
        self.calls = []
        self._reports = reports

    def transcribe(self, audio, language=None, **kwargs):
        self.calls.append(language)
        return ([_FakeFasterSegment("hello there", 0.2)],
                _FakeFasterInfo(self._reports or language or "en"))


@pytest.fixture
def voice():
    v = VoiceInput.__new__(VoiceInput)  # skip __init__: no model download thread
    return v


class TestForcedEnglish:
    def test_openai_forces_english_once(self, voice):
        fake = _FakeOpenAIWhisper()
        voice._whisper = fake
        audio = np.zeros(16000, dtype=np.float32)
        assert voice._transcribe_openai(audio) == "hello there"
        assert fake.calls == ["en"]  # forced up front, never retried

    def test_faster_forces_english_once(self, voice):
        fake = _FakeFasterWhisper()
        voice._whisper = fake
        audio = np.zeros(16000, dtype=np.float32)
        assert voice._transcribe_faster(audio) == "hello there"
        assert fake.calls == ["en"]

    def test_a_backend_that_ignores_the_forced_language_is_dropped(self, voice):
        # The guard in _join_speech_segments has to be reachable from the real
        # call path, not only from a direct call with a hand-made language. It
        # regressed to dead code once because the call sites passed the
        # constant they had just asked for instead of what came back.
        fake = _FakeOpenAIWhisper(reports="ko")
        voice._whisper = fake
        audio = np.zeros(16000, dtype=np.float32)
        assert voice._transcribe_openai(audio) == ""
        assert fake.calls == ["en"]        # we still asked for English

    def test_the_same_holds_for_the_local_backend(self, voice):
        fake = _FakeFasterWhisper(reports="is")
        voice._whisper = fake
        audio = np.zeros(16000, dtype=np.float32)
        assert voice._transcribe_faster(audio) == ""

    def test_non_speech_still_filtered(self, voice):
        class _NoiseWhisper(_FakeOpenAIWhisper):
            def transcribe(self, audio, language=None, **kwargs):
                self.calls.append(language)
                return {
                    "language": language or "en",
                    "text": "여러분들과의",
                    "segments": [{"text": "여러분들과의", "no_speech_prob": 0.97}],
                }

        fake = _NoiseWhisper()
        voice._whisper = fake
        audio = np.zeros(16000, dtype=np.float32)
        assert voice._transcribe_openai(audio) == ""
        assert fake.calls == ["en"]
