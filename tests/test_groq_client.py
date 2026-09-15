"""One Groq client per process.

Constructing one costs ~207 ms. voice_in built a fresh client per
transcription and voice_out built one per *sentence* of the reply, so a
five-sentence answer spent about a second on client construction alone —
against a time-to-first-token of roughly 1.6 s.
"""
import threading

import pytest

from core import groq_client


@pytest.fixture(autouse=True)
def clean():
    groq_client.reset()
    yield
    groq_client.reset()


class TestSharing:
    def test_it_builds_at_most_one(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "gsk_real_looking_key")
        built = []

        class FakeGroq:
            def __init__(self, api_key=None):
                built.append(api_key)

        import groq
        monkeypatch.setattr(groq, "Groq", FakeGroq)
        first = groq_client.get()
        for _ in range(10):
            assert groq_client.get() is first
        assert len(built) == 1

    def test_concurrent_callers_get_the_same_one(self, monkeypatch):
        # The TTS synth worker runs on its own thread while the pipeline
        # thread may also be reaching for a client.
        monkeypatch.setenv("GROQ_API_KEY", "gsk_real_looking_key")
        built = []

        class FakeGroq:
            def __init__(self, api_key=None):
                built.append(api_key)

        import groq
        monkeypatch.setattr(groq, "Groq", FakeGroq)

        seen = []
        threads = [threading.Thread(target=lambda: seen.append(groq_client.get()))
                   for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(built) == 1
        assert all(s is seen[0] for s in seen)

    def test_reset_lets_a_new_key_take_effect(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "gsk_real_looking_key")
        built = []

        class FakeGroq:
            def __init__(self, api_key=None):
                built.append(api_key)

        import groq
        monkeypatch.setattr(groq, "Groq", FakeGroq)
        groq_client.get()
        groq_client.reset()
        groq_client.get()
        assert len(built) == 2


class TestNoKey:
    @pytest.mark.parametrize("key", ["", "   ", "gsk_xxx_placeholder"])
    def test_a_missing_or_placeholder_key_returns_none(self, monkeypatch, key):
        # None rather than raising: both callers already fall back — STT to a
        # local model, TTS to Edge — and an exception would skip that path.
        monkeypatch.setenv("GROQ_API_KEY", key)
        assert groq_client.get() is None

    def test_it_does_not_import_groq_without_a_key(self, monkeypatch):
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        import groq

        def explode(*a, **k):
            raise AssertionError("constructed a client with no key")

        monkeypatch.setattr(groq, "Groq", explode)
        assert groq_client.get() is None


class TestCallersFallBack:
    def test_tts_falls_through_to_edge_when_there_is_no_client(self, monkeypatch):
        from core.voice_out import VoiceOutput
        monkeypatch.setenv("GROQ_API_KEY", "")
        vo = VoiceOutput.__new__(VoiceOutput)
        assert vo._synth_groq("hello") is None
