"""Names from Mo's Spotify Liked Songs, for Whisper's hint sentence.

Most of what Mo asks to play is in Liked Songs, so its names are the ones
Whisper most needs — even for songs El Fager has never played. The most-liked
artists and the newest liked songs are read once a day; these run on a fake
Spotify client.
"""
import json

import pytest

from core import voice_liked


def track(title, *artists):
    return {"track": {"name": title, "artists": [{"name": a} for a in artists]}}


class FakeLibrary:
    """Pages of saved tracks, newest first, as Spotify returns them."""

    def __init__(self, items, fail=False):
        self.items = items
        self.fail = fail
        self.calls = 0

    def current_user_saved_tracks(self, limit=20, offset=0):
        self.calls += 1
        if self.fail:
            raise ConnectionError("offline")
        page = self.items[offset:offset + limit]
        return {"items": page, "total": len(self.items),
                "next": "more" if offset + limit < len(self.items) else None}


@pytest.fixture
def clock(monkeypatch):
    now = {"t": 2_000_000.0}
    monkeypatch.setattr(voice_liked, "_now", lambda: now["t"])
    return now


class TestSummary:
    def test_newest_liked_songs_then_most_liked_artists(self):
        items = [track("Estanna", "Tawsen", "Fares Sokar"),
                 track("Ya Sater", "Tamer Hosny"),
                 track("Nasseny Leh", "Tamer Hosny"),
                 track("Bahebak", "Tamer Hosny"),
                 track("Ghareeb", "Shehab"),
                 track("Wala Hagah", "Shehab")]
        summary = voice_liked.summarise(items, recent=2, artists=2)
        assert summary["recent"] == ["Estanna", "Tawsen", "Fares Sokar", "Ya Sater", "Tamer Hosny"]
        assert summary["artists"] == ["Tamer Hosny", "Shehab"]

    def test_a_tie_goes_to_the_artist_liked_more_recently(self):
        items = [track("A", "Newer"), track("B", "Older"), track("C", "Newer"), track("D", "Older")]
        assert voice_liked.summarise(items, recent=0, artists=1)["artists"] == ["Newer"]

    def test_arabic_script_names_are_kept_and_empty_rows_skipped(self):
        # Mo wants his Arabic song names in the hint as Spotify spells them.
        items = [track("إستنى", "Tawsen"), {"track": None}, track("Ghareeb", "شهاب")]
        summary = voice_liked.summarise(items, recent=3, artists=3)
        assert "إستنى" in summary["recent"] and "شهاب" in summary["artists"]
        assert "Tawsen" in summary["recent"] and "Ghareeb" in summary["recent"]

    def test_punctuation_trailing_a_title_is_trimmed(self):
        # Spotify has the song as "Estanna," — in the hint that read "Estanna,, Tawsen".
        summary = voice_liked.summarise([track("Estanna,", "Tawsen")], recent=1, artists=1)
        assert summary["recent"] == ["Estanna", "Tawsen"]


class TestRefresh:
    def test_it_reads_the_library_and_saves_the_summary(self, clock, monkeypatch):
        library = FakeLibrary([track("Estanna", "Tawsen"), track("Ya Sater", "Tamer Hosny")])
        monkeypatch.setattr(voice_liked, "_client", lambda: library)
        assert voice_liked.refresh_if_stale() is True
        saved = json.loads(voice_liked._FILE.read_text(encoding="utf-8"))
        assert saved["at"] == clock["t"]
        assert "Estanna" in voice_liked.names() and "Tamer Hosny" in voice_liked.names()

    def test_it_pages_through_but_stops_at_the_cap(self, clock, monkeypatch):
        library = FakeLibrary([track(f"Song {n}", f"Artist {n}") for n in range(voice_liked.MAX_TRACKS + 300)])
        monkeypatch.setattr(voice_liked, "_client", lambda: library)
        voice_liked.refresh_if_stale()
        assert library.calls == voice_liked.MAX_TRACKS // 50

    def test_not_again_the_same_day(self, clock, monkeypatch):
        library = FakeLibrary([track("Estanna", "Tawsen")])
        monkeypatch.setattr(voice_liked, "_client", lambda: library)
        voice_liked.refresh_if_stale()
        clock["t"] += voice_liked.REFRESH_SECONDS - 60
        assert voice_liked.refresh_if_stale() is False
        assert library.calls == 1

    def test_again_once_a_day_has_passed(self, clock, monkeypatch):
        library = FakeLibrary([track("Estanna", "Tawsen")])
        monkeypatch.setattr(voice_liked, "_client", lambda: library)
        voice_liked.refresh_if_stale()
        clock["t"] += voice_liked.REFRESH_SECONDS + 60
        library.items.insert(0, track("New Like", "Erzaa"))
        assert voice_liked.refresh_if_stale() is True
        assert "New Like" in voice_liked.names()

    def test_a_failed_read_keeps_yesterdays_names(self, clock, monkeypatch):
        good = FakeLibrary([track("Estanna", "Tawsen")])
        monkeypatch.setattr(voice_liked, "_client", lambda: good)
        voice_liked.refresh_if_stale()
        clock["t"] += voice_liked.REFRESH_SECONDS + 60
        monkeypatch.setattr(voice_liked, "_client", lambda: FakeLibrary([], fail=True))
        assert voice_liked.refresh_if_stale() is False
        assert "Estanna" in voice_liked.names()

    def test_without_the_library_login_nothing_happens(self, clock, monkeypatch):
        monkeypatch.setattr(voice_liked, "_client", lambda: None)
        assert voice_liked.refresh_if_stale() is False
        assert not voice_liked._FILE.exists()
        assert voice_liked.names() == []


class TestTheSuiteNeverTouchesTheRealFile:
    def test_the_file_a_test_sees_is_not_the_real_one(self):
        from pathlib import Path
        assert Path(voice_liked._FILE).resolve() != Path("data/voice_liked.json").resolve()


class TestTheHintUsesThem:
    def test_liked_names_come_after_the_hand_written_and_learned_ones(self, clock, tmp_path, monkeypatch):
        from core import voice_in, voice_learned
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps({"voice_vocabulary": ["Erzaa"]}), encoding="utf-8")
        monkeypatch.setattr(voice_in, "_SETTINGS", settings)
        monkeypatch.setattr(voice_in, "_PROFILE", tmp_path / "none.json")
        monkeypatch.setattr(voice_in, "_CONTACTS", tmp_path / "none.json")
        monkeypatch.setattr(voice_in, "_BIAS_CACHE", None)
        monkeypatch.setattr(voice_learned, "names", lambda: ["Estanna"])
        library = FakeLibrary([track("Ya Sater", "Tamer Hosny")])
        monkeypatch.setattr(voice_liked, "_client", lambda: library)
        voice_liked.refresh_if_stale()
        tail = voice_in._bias_prompt().split("then play ", 1)[1]
        assert tail == "Erzaa, Estanna, Ya Sater, Tamer Hosny."
