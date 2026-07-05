"""
Tests for voice_in hallucination guards: language whitelist + no-speech filter.

No audio hardware or Whisper models needed — _join_speech_segments is pure,
and the backend retry logic is exercised with fake models.
"""
import numpy as np
import pytest

from core.voice_in import (
    ALLOWED_LANGUAGES,
    NO_SPEECH_MAX,
    VoiceInput,
    _join_speech_segments,
)


# ── _join_speech_segments ──────────────────────────────────────────────────

class TestJoinSpeechSegments:
    def test_allowed_language_passes_through(self):
        assert _join_speech_segments("ar", [("ازيك يا فجر", 0.1)]) == "ازيك يا فجر"
        assert _join_speech_segments("en", [("hello", 0.0), ("world", 0.2)]) == "hello world"
        assert _join_speech_segments("fr", [("bonjour", 0.3)]) == "bonjour"

    def test_disallowed_language_returns_empty(self):
        # Noise hallucinated as Icelandic/Korean/Czech must never reach the brain
        for lang in ("is", "ko", "cs", "he", "ru"):
            assert _join_speech_segments(lang, [("Það er um þig", 0.1)]) == ""

    def test_regional_code_normalised(self):
        assert _join_speech_segments("ar-EG", [("اهلا", 0.1)]) == "اهلا"

    def test_high_no_speech_prob_segments_dropped(self):
        segments = [("real speech", 0.1), ("hallucinated tail", 0.95)]
        assert _join_speech_segments("en", segments) == "real speech"

    def test_all_segments_non_speech_returns_empty(self):
        assert _join_speech_segments("en", [("noise", 0.9), ("more", NO_SPEECH_MAX)]) == ""

    def test_none_language_and_none_prob_kept(self):
        # Backends without detection/segment detail must not lose text
        assert _join_speech_segments(None, [("hello", None)]) == "hello"

    def test_whitelist_matches_mo_languages(self):
        assert ALLOWED_LANGUAGES == {"ar", "en", "fr"}


# ── Forced-Arabic retry on disallowed detection ────────────────────────────

class _FakeOpenAIWhisper:
    """Detects Icelandic on autodetect; returns Arabic when forced."""

    def __init__(self):
        self.calls = []

    def transcribe(self, audio, language=None, **kwargs):
        self.calls.append(language)
        if language is None:
            return {
                "language": "is",
                "text": "Það er um þig",
                "segments": [{"text": "Það er um þig", "no_speech_prob": 0.2}],
            }
        return {
            "language": language,
            "text": "صباح الخير",
            "segments": [{"text": "صباح الخير", "no_speech_prob": 0.2}],
        }


class _FakeFasterInfo:
    def __init__(self, language):
        self.language = language


class _FakeFasterSegment:
    def __init__(self, text, no_speech_prob):
        self.text = text
        self.no_speech_prob = no_speech_prob


class _FakeFasterWhisper:
    def __init__(self):
        self.calls = []

    def transcribe(self, audio, language=None, **kwargs):
        self.calls.append(language)
        if language is None:
            return [_FakeFasterSegment("Það er um þig", 0.2)], _FakeFasterInfo("is")
        return [_FakeFasterSegment("صباح الخير", 0.2)], _FakeFasterInfo(language)


@pytest.fixture
def voice():
    v = VoiceInput.__new__(VoiceInput)  # skip __init__: no model download thread
    return v


class TestForcedArabicRetry:
    def test_openai_disallowed_detection_retries_forced_ar(self, voice):
        fake = _FakeOpenAIWhisper()
        voice._whisper = fake
        audio = np.zeros(16000, dtype=np.float32)
        assert voice._transcribe_openai(audio) == "صباح الخير"
        assert fake.calls == [None, "ar"]

    def test_faster_disallowed_detection_retries_forced_ar(self, voice):
        fake = _FakeFasterWhisper()
        voice._whisper = fake
        audio = np.zeros(16000, dtype=np.float32)
        assert voice._transcribe_faster(audio) == "صباح الخير"
        assert fake.calls == [None, "ar"]

    def test_openai_allowed_detection_no_retry(self, voice):
        class _EnglishWhisper(_FakeOpenAIWhisper):
            def transcribe(self, audio, language=None, **kwargs):
                self.calls.append(language)
                return {
                    "language": "en",
                    "text": "hello there",
                    "segments": [{"text": "hello there", "no_speech_prob": 0.1}],
                }

        fake = _EnglishWhisper()
        voice._whisper = fake
        audio = np.zeros(16000, dtype=np.float32)
        assert voice._transcribe_openai(audio) == "hello there"
        assert fake.calls == [None]

    def test_forced_retry_still_filters_non_speech(self, voice):
        class _NoiseWhisper(_FakeOpenAIWhisper):
            def transcribe(self, audio, language=None, **kwargs):
                self.calls.append(language)
                lang = "ko" if language is None else language
                return {
                    "language": lang,
                    "text": "여러분들과의",
                    "segments": [{"text": "여러분들과의", "no_speech_prob": 0.97}],
                }

        fake = _NoiseWhisper()
        voice._whisper = fake
        audio = np.zeros(16000, dtype=np.float32)
        # Pure noise: retry happens, but the no-speech filter empties the result
        assert voice._transcribe_openai(audio) == ""
        assert fake.calls == [None, "ar"]
