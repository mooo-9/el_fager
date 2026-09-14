"""With no internet, El Fager still speaks — in Windows' own offline voice.

Groq and Edge both need the network. When Edge failed too, _synthesize
returned None and the answer was never heard. Windows' speech engine (SAPI)
is installed on every Windows machine and needs no connection.

pyttsx3 was tried first and rejected: it hung on its second sentence when
called from a thread, which is exactly how the pipeline calls it.
"""
import sys
import threading
import wave

import pytest

from core import voice_out


@pytest.fixture
def vo(monkeypatch):
    out = voice_out.VoiceOutput.__new__(voice_out.VoiceOutput)
    out._backend = "auto"
    out._voice_en = "en-US-GuyNeural"
    monkeypatch.setenv("GROQ_API_KEY", "")          # Groq out of the picture
    return out


class TestTheOrder:
    def test_when_edge_fails_windows_speaks(self, vo, monkeypatch):
        monkeypatch.setattr(vo, "_synth_edge", lambda text: None)
        monkeypatch.setattr(vo, "_synth_sapi", lambda text: "offline.wav")
        assert vo._synthesize("The internet is down.") == "offline.wav"

    def test_when_edge_works_windows_is_never_asked(self, vo, monkeypatch):
        asked = []
        monkeypatch.setattr(vo, "_synth_edge", lambda text: "edge.mp3")
        monkeypatch.setattr(vo, "_synth_sapi", lambda text: asked.append(text))
        assert vo._synthesize("Hello.") == "edge.mp3"
        assert asked == []

    def test_with_every_voice_gone_it_still_returns_quietly(self, vo, monkeypatch):
        monkeypatch.setattr(vo, "_synth_edge", lambda text: None)
        monkeypatch.setattr(vo, "_synth_sapi", lambda text: None)
        assert vo._synthesize("Hello.") is None


@pytest.mark.skipif(sys.platform != "win32", reason="SAPI is Windows' speech engine")
class TestTheRealOfflineVoice:
    def _synth_on_a_thread(self, vo, sentences):
        paths = []
        def run():
            for sentence in sentences:
                paths.append(vo._synth_sapi(sentence))
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        thread.join(30)
        assert not thread.is_alive(), "the offline voice hung"
        return paths

    def test_sentence_after_sentence_from_a_thread_makes_real_audio(self, vo):
        # A thread, and more than one sentence: the two things pyttsx3 failed.
        paths = self._synth_on_a_thread(vo, ["The internet is down.", "I can still talk to you."])
        try:
            assert all(paths), "a sentence produced no audio"
            for path in paths:
                with wave.open(path) as audio:
                    assert audio.getnframes() / audio.getframerate() > 0.5
        finally:
            import os
            for path in paths:
                if path:
                    os.unlink(path)

    def test_it_picks_an_english_voice(self):
        name = voice_out._sapi_voice_name()
        assert name is None or "English" in name
