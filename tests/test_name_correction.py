"""After transcription, a near-miss of a known name becomes the name.

Even with the names in Whisper's hint it still writes what it hears:
"Abusif" for Abyusif, "Hussain Yasser" for Hussein Yasser, "Shahab" for
Shehab. The misses here are from a real Groq Whisper run on 2026-09-14; the
sentences that must stay untouched are from Mo's own conversation logs, where
a looser matcher turned "at the end of the day" into "The Weeknd".
"""
import pytest

from core import voice_in

VOCABULARY = ["Estanna", "Fares Sokar", "Tawsen", "Tamer Hosny", "Shehab", "Erzaa",
              "Abyusif", "Hussein Yasser", "Afroto", "Marwan Moussa", "Marwan Pablo",
              "Amr Diab", "The Weeknd", "Don Toliver", "Elissa", "TRRR"]


def fix(text):
    return voice_in._correct_names(text, VOCABULARY)


class TestNearMissesBecomeTheName:
    @pytest.mark.parametrize("heard,meant", [
        ("Play Estanna by Fares Soker and Tawsen on Spotify.",
         "Play Estanna by Fares Sokar and Tawsen on Spotify."),
        ("Play the latest song by Shahab on Spotify.", "Play the latest song by Shehab on Spotify."),
        ("Open YouTube and play the latest video by Erza.",
         "Open YouTube and play the latest video by Erzaa."),
        ("Play the latest song by Abusif.", "Play the latest song by Abyusif."),
        ("Play something by Hussain Yasser.", "Play something by Hussein Yasser."),
        ("Play Afrodo on Spotify.", "Play Afroto on Spotify."),
        ("Play the new song by Mawrwan Moussa.", "Play the new song by Marwan Moussa."),
        ("Play the latest song by Tamer Hosni.", "Play the latest song by Tamer Hosny."),
        ("Play Something by Houssein Yasser", "Play Something by Hussein Yasser"),
        # from Mo's logs
        ("Hey, Fagir, turn on a music called Yama by Amradiab.",
         "Hey, Fagir, turn on a music called Yama by Amr Diab."),
    ])
    def test_it_writes_the_name(self, heard, meant):
        assert fix(heard) == meant

    def test_a_name_heard_as_two_words_becomes_one(self):
        assert fix("Play Afro to On Spotify") == "Play Afroto On Spotify"

    def test_the_whole_miss_is_replaced_not_half_of_it(self):
        assert fix("Play the latest song by Eby Yusif.") == "Play the latest song by Abyusif."


class TestEverydaySpeechIsLeftAlone:
    @pytest.mark.parametrize("said", [
        "When I'm at the end of the day, I'm not going to be able to do this.",
        "There is in front of me an email, a draft that I told you to send.",
        "By Sep I said, let's go a thing, after we finish, don't give up.",
        "Some might she have what she have.",
        "Play the little song by Shehab.",               # already right: keep "by"
        "Play, Estanna.",
        "No, that's not the word. Focus, it's called Estanna, E-S-T-A-N-A.",
        "Send it.",
        "what is the weather in cairo",
    ])
    def test_it_is_not_rewritten(self, said):
        assert fix(said) == said

    def test_a_name_too_short_to_match_safely_is_never_used(self):
        # "TRRR" is four letters: "Try" would score too close.
        assert fix("Try the other one.") == "Try the other one."

    def test_no_vocabulary_changes_nothing(self):
        assert voice_in._correct_names("Play Abusif.", []) == "Play Abusif."


class TestTranscriptionUsesIt:
    def test_what_whisper_heard_is_corrected_before_anyone_reads_it(self, monkeypatch):
        import numpy as np
        monkeypatch.setattr(voice_in, "_vocabulary", lambda: ["Abyusif"])

        class FakeOpenAIWhisper:
            def transcribe(self, audio, **kwargs):
                return {"language": "en", "text": "Play Abusif.",
                        "segments": [{"text": "Play the latest song by Abusif.", "no_speech_prob": 0.1}]}

        voice = voice_in.VoiceInput.__new__(voice_in.VoiceInput)
        voice._whisper = FakeOpenAIWhisper()
        voice._backend = voice_in._BACKEND_OPENAI
        assert voice.transcribe(np.zeros(16000, dtype=np.float32)) == "Play the latest song by Abyusif."
