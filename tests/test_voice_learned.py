"""Names Whisper should know, learned from the songs El Fager plays.

Only a song that keeps playing is learned. On 2026-09-13 El Fager played four
wrong songs — Stand By Me, Futura Free, Estanani, Estana Maaya — before
"Estanna by Tawsen and Fares Sokar"; each wrong one was replaced within a
minute. Learning those would teach Whisper the mistakes.
"""
import json

import pytest

from core import voice_learned


@pytest.fixture
def clock(monkeypatch):
    now = {"t": 1_000_000.0}
    monkeypatch.setattr(voice_learned, "_now", lambda: now["t"])
    return now


class TestKeptSongsAreLearned:
    def test_a_song_that_keeps_playing_is_learned(self, clock):
        voice_learned.played("Estanna", ["Tawsen", "Fares Sokar"])
        clock["t"] += voice_learned.KEEP_SECONDS + 1
        assert voice_learned.names() == ["Estanna", "Tawsen", "Fares Sokar"]

    def test_not_before_it_has_kept_playing(self, clock):
        voice_learned.played("Estanna", ["Tawsen"])
        clock["t"] += voice_learned.KEEP_SECONDS - 5
        assert voice_learned.names() == []

    def test_a_song_replaced_within_a_minute_was_a_miss(self, clock):
        voice_learned.played("Stand By Me", ["Ben E. King"])
        clock["t"] += 20
        voice_learned.played("Estanna", ["Tawsen", "Fares Sokar"])
        clock["t"] += voice_learned.KEEP_SECONDS + 1
        learned = voice_learned.names()
        assert "Stand By Me" not in learned and "Ben E. King" not in learned
        assert "Estanna" in learned

    def test_a_song_learned_earlier_stays_when_the_next_is_a_miss(self, clock):
        voice_learned.played("Estanna", ["Tawsen"])
        clock["t"] += voice_learned.KEEP_SECONDS + 1
        voice_learned.names()
        voice_learned.played("Futura Free", ["Frank Ocean"])
        clock["t"] += 10
        voice_learned.played("Stand By Me", ["Ben E. King"])
        assert "Estanna" in voice_learned.names()


class TestWhatIsKept:
    def test_names_in_arabic_script_are_kept(self, clock):
        # Mo wants his Arabic song names in the hint as Spotify spells them.
        voice_learned.played("إستنى", ["Tawsen", "فارس سكر"])
        clock["t"] += voice_learned.KEEP_SECONDS + 1
        assert voice_learned.names() == ["إستنى", "Tawsen", "فارس سكر"]

    def test_punctuation_trailing_a_title_is_trimmed(self, clock):
        # Spotify's title is "Estanna," — in the hint that read "Estanna,, Tawsen".
        voice_learned.played("Estanna,", ["Tawsen"])
        clock["t"] += voice_learned.KEEP_SECONDS + 1
        assert voice_learned.names() == ["Estanna", "Tawsen"]

    def test_the_newest_come_first_and_repeats_move_up(self, clock):
        for title, artist in (("One", "A"), ("Two", "B"), ("One", "A")):
            voice_learned.played(title, [artist])
            clock["t"] += voice_learned.KEEP_SECONDS + 1
            voice_learned.names()
        assert voice_learned.names() == ["One", "A", "Two", "B"]

    def test_the_list_stays_small(self, clock):
        for n in range(40):
            voice_learned.played(f"Song {n}", [f"Artist {n}"])
            clock["t"] += voice_learned.KEEP_SECONDS + 1
            voice_learned.names()
        learned = voice_learned.names()
        assert len(learned) == voice_learned.MAX_NAMES
        assert learned[0] == "Song 39"

    def test_a_broken_file_is_an_empty_list(self, clock):
        voice_learned._FILE.parent.mkdir(parents=True, exist_ok=True)
        voice_learned._FILE.write_text("{nope", encoding="utf-8")
        assert voice_learned.names() == []
        voice_learned.played("Estanna", ["Tawsen"])          # and it recovers
        clock["t"] += voice_learned.KEEP_SECONDS + 1
        assert voice_learned.names() == ["Estanna", "Tawsen"]


class TestTheSuiteNeverTouchesTheRealFile:
    def test_the_file_a_test_sees_is_not_the_real_one(self):
        from pathlib import Path
        assert Path(voice_learned._FILE).resolve() != Path("data/voice_learned.json").resolve()


class TestTheHintUsesThem:
    def test_learned_names_follow_the_hand_written_ones(self, clock, tmp_path, monkeypatch):
        from core import voice_in
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps({"voice_vocabulary": ["Erzaa", "Tawsen"]}), encoding="utf-8")
        monkeypatch.setattr(voice_in, "_SETTINGS", settings)
        monkeypatch.setattr(voice_in, "_PROFILE", tmp_path / "none.json")
        monkeypatch.setattr(voice_in, "_CONTACTS", tmp_path / "none.json")
        monkeypatch.setattr(voice_in, "_BIAS_CACHE", None)
        voice_learned.played("Estanna", ["Tawsen", "Fares Sokar"])
        clock["t"] += voice_learned.KEEP_SECONDS + 1
        prompt = voice_in._bias_prompt()
        tail = prompt.split("then play ", 1)[1]
        assert tail == "Erzaa, Tawsen, Estanna, Fares Sokar."


class TestSpotifyReportsWhatItPlays:
    def test_a_played_track_is_handed_over_with_its_artists(self, monkeypatch):
        from tools import spotify_tool
        heard = []
        monkeypatch.setattr(voice_learned, "played", lambda title, artists: heard.append((title, artists)))

        class FakeSpotify:
            def search(self, q, type, limit):
                return {"tracks": {"items": [{"name": "Estanna", "uri": "spotify:track:1",
                                              "artists": [{"name": "Tawsen"}, {"name": "Fares Sokar"}]}]}}

            def start_playback(self, **kwargs):
                pass

        monkeypatch.setattr(spotify_tool, "SPOTIFY_AVAILABLE", True)
        monkeypatch.setattr(spotify_tool, "get_spotify", lambda: FakeSpotify())
        monkeypatch.setattr(spotify_tool, "_get_device", lambda sp: "device")
        assert spotify_tool.play_music("estanna").startswith("Playing: Estanna")
        assert heard == [("Estanna", ["Tawsen", "Fares Sokar"])]

    def test_a_learning_failure_never_stops_the_music(self, monkeypatch):
        from tools import spotify_tool
        def broken(title, artists):
            raise OSError("disk full")
        monkeypatch.setattr(voice_learned, "played", broken)

        class FakeSpotify:
            def search(self, q, type, limit):
                return {"tracks": {"items": [{"name": "Estanna", "uri": "u", "artists": [{"name": "Tawsen"}]}]}}

            def start_playback(self, **kwargs):
                pass

        monkeypatch.setattr(spotify_tool, "SPOTIFY_AVAILABLE", True)
        monkeypatch.setattr(spotify_tool, "get_spotify", lambda: FakeSpotify())
        monkeypatch.setattr(spotify_tool, "_get_device", lambda sp: "device")
        assert spotify_tool.play_music("estanna").startswith("Playing: Estanna")


class TestPeopleMoContacts:
    """Names of people Mo WhatsApps or emails are learned at once — a sent
    message is already confirmed, there is no wrong pick to wait out."""

    def test_a_contacted_name_is_learned_straight_away(self, clock):
        voice_learned.contacted("Yasmeen Adam")
        assert voice_learned.names() == ["Yasmeen Adam"]

    def test_arabic_names_are_kept(self, clock):
        voice_learned.contacted("العائله")
        assert voice_learned.names() == ["العائله"]

    def test_newest_first_and_repeats_move_up(self, clock):
        for name in ("Seif Magdy", "Yasmeen Adam", "seif magdy"):
            voice_learned.contacted(name)
        assert voice_learned.names() == ["seif magdy", "Yasmeen Adam"]

    def test_people_come_before_songs_and_neither_pushes_the_other_out(self, clock):
        voice_learned.played("Estanna", ["Tawsen"])
        clock["t"] += voice_learned.KEEP_SECONDS + 1
        for i in range(voice_learned.MAX_NAMES + 5):
            voice_learned.contacted(f"Person {i}")
        learned = voice_learned.names()
        assert learned[0] == f"Person {voice_learned.MAX_NAMES + 4}"
        assert "Estanna" in learned and "Tawsen" in learned
        assert len([n for n in learned if n.startswith("Person")]) == voice_learned.MAX_NAMES

    def test_blank_and_bare_numbers_are_not_names(self, clock):
        for name in ("", "  ", "+201001234567", "201001234567"):
            voice_learned.contacted(name)
        assert voice_learned.names() == []
