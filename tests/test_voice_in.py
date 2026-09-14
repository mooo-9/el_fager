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


# ── Repetition loops ───────────────────────────────────────────────────────
# Every line here is a real transcript from data/conversations. Whisper's own
# compression-ratio check (2.4) passes all of the loops: zlib barely compresses
# a sentence this short, so none of them scores above 2.1.

class TestRepetitionLoops:
    @pytest.mark.parametrize("looped", [
        # 2026-09-05: the mic heard the song El Fager had just started playing
        "I'm going to get a check on my calendar, and I'm going to get a check "
        "on my calendar, and I'm going to get a check on my calendar.",
        "I'm going to ask you a question. How are you? How are you? Sorry, I'm "
        "sorry. No, I'm sorry. I'm sorry, I'm sorry. I'm sorry, I'm sorry.",
        "I'm not sure if I can't get it. I'm not sure if I can't get it. You're "
        "not sure if I can't get it. Yes. I'm not sure.",
        "Jesus, I saw my life, I saw my life, I saw my life, I saw my life.",
        "اوه اوه اوه اوه اوه اوه",
    ])
    def test_a_looped_decode_is_dropped(self, looped):
        assert _join_speech_segments("en", [(looped, 0.1)]) == ""

    @pytest.mark.parametrize("real", [
        # Mo repeating a phrase on purpose — the loop check must leave these be
        "I only talk English and Arabic That's not even a language that I speak "
        "I told you how are you in Arabic How are you, Fager? How are you?",
        "أريد أن أضعه في To Do List أريد أن أضعه في To Do List ثاني حاجة أريد أن "
        "أزوده ليس راس الشمال راست الشمال أضلت W R I S T ثاني حاجة أريد أن أذهب "
        "لدكتور السنان يزودها في To Do List أيضا",
        "Hold up, close. Hold up, close. Hold up. That's my thing.",
        "Please, please, please, please. Huh?",
        "Send it.",
    ])
    def test_deliberate_repetition_is_kept(self, real):
        assert _join_speech_segments("en", [(real, 0.1)]) == real

    def test_a_loop_split_across_segments_is_still_caught(self):
        segments = [("I saw my life,", 0.1), ("I saw my life,", 0.1),
                    ("I saw my life, I saw my life.", 0.1)]
        assert _join_speech_segments("en", segments) == ""


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


# ── How loud the mic is, for the Cockpit's sphere ─────────────────────────

class TestSpeechLevel:
    """Mo chose for the sphere to swell with their voice while it listens, so
    the recorder reports a 0..1 loudness for every slice of audio it takes."""

    def _tone(self, rms):
        # A sine's RMS is its amplitude over root two.
        t = np.arange(512) / 16000
        return (np.sin(2 * np.pi * 220 * t) * rms * np.sqrt(2)).astype(np.float32)

    def test_silence_is_still(self):
        from core.voice_in import speech_level
        assert speech_level(np.zeros(512, dtype=np.float32)) == 0.0

    def test_the_speech_threshold_sits_low_in_the_range(self):
        # RMS_THRESHOLD (0.01, -40 dBFS) is where the recorder counts speech:
        # it should move the sphere, but only a little.
        from core.voice_in import RMS_THRESHOLD, speech_level
        assert 0.2 <= speech_level(self._tone(RMS_THRESHOLD)) <= 0.45

    def test_a_loud_voice_is_full_and_never_past_it(self):
        from core.voice_in import speech_level
        assert speech_level(self._tone(0.15)) == 1.0
        assert speech_level(np.ones(512, dtype=np.float32)) == 1.0

    def test_louder_is_never_less(self):
        from core.voice_in import speech_level
        levels = [speech_level(self._tone(r)) for r in (0.004, 0.01, 0.02, 0.04, 0.08)]
        assert levels == sorted(levels) and len(set(levels)) == len(levels)


class _FakeStream:
    """sounddevice.InputStream that plays back chunks instead of a mic."""

    def __init__(self, chunks, feed_on_enter, **kwargs):
        self._chunks = list(chunks)
        self._feed_on_enter = feed_on_enter
        self.callback = kwargs["callback"]

    def feed_one(self):
        if self._chunks:
            self.callback(self._chunks.pop(0).reshape(-1, 1), 0, None, None)

    def __enter__(self):
        if self._feed_on_enter:
            while self._chunks:
                self.feed_one()
        return self

    def __exit__(self, *exc):
        return False


class TestRecordingReportsLoudness:
    def _speech_then_silence(self, size):
        loud = np.full(size, 0.05, dtype=np.float32)
        quiet = np.zeros(size, dtype=np.float32)
        return [loud] * 3 + [quiet] * 60

    def _rms_recorder(self, voice, monkeypatch):
        import core.voice_in as vi
        chunks = self._speech_then_silence(int(vi.SAMPLE_RATE * vi.RMS_CHUNK_SEC))
        stream = {}

        def make(**kw):
            stream["s"] = _FakeStream(chunks, feed_on_enter=False, **kw)
            return stream["s"]

        monkeypatch.setattr(vi.sd, "InputStream", make)
        monkeypatch.setattr(vi.sd, "sleep", lambda ms: stream["s"].feed_one())
        voice._vad_model = None
        voice._stop_flag = vi.threading.Event()

    def test_the_vad_recorder_reports_every_chunk(self, voice, monkeypatch):
        import torch
        import core.voice_in as vi
        chunks = self._speech_then_silence(vi.VAD_CHUNK)
        monkeypatch.setattr(vi.sd, "InputStream",
                            lambda **kw: _FakeStream(chunks, feed_on_enter=True, **kw))

        class Vad:
            def reset_states(self):
                pass

            def __call__(self, frame, sr):
                return torch.tensor(1.0 if frame.abs().max() > 0 else 0.0)

        voice._vad_model = Vad()
        voice._stop_flag = vi.threading.Event()
        levels = []
        assert voice.record_audio(on_level=levels.append) is not None
        assert levels[:3] == [vi.speech_level(chunks[0])] * 3 and levels[0] > 0.5
        assert levels[3] == 0.0

    def test_the_rms_fallback_reports_every_chunk(self, voice, monkeypatch):
        self._rms_recorder(voice, monkeypatch)
        levels = []
        assert voice.record_audio(on_level=levels.append) is not None
        assert levels[0] > 0.5 and levels[3] == 0.0

    def test_recording_without_a_listener_still_works(self, voice, monkeypatch):
        self._rms_recorder(voice, monkeypatch)
        assert voice.record_audio() is not None
