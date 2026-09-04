"""Tests for play_music in tools/spotify_tool.py — the search-then-play path
and its handoff to the desktop app when the Web API can't drive playback."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import MagicMock

import pytest

import tools.spotify_tool as st


def _results(tracks=(), playlists=(), albums=()):
    return {
        "tracks":    {"items": list(tracks)},
        "playlists": {"items": list(playlists)},
        "albums":    {"items": list(albums)},
    }


TRACK = {"uri": "spotify:track:abc", "name": "Enta Eih",
         "artists": [{"name": "Nancy Ajram"}]}


@pytest.fixture
def launched(monkeypatch):
    """Record every URI handed to the desktop app."""
    calls = []
    monkeypatch.setattr(st, "_launch_spotify_app", lambda uri="spotify:": calls.append(uri) or True)
    return calls


@pytest.fixture
def sp(monkeypatch):
    """A Spotify client with credentials present and one track in search."""
    monkeypatch.setattr(st, "SPOTIFY_AVAILABLE", True)
    client = MagicMock()
    client.search.return_value = _results(tracks=[TRACK])
    monkeypatch.setattr(st, "get_spotify", lambda: client)
    return client


class TestPlayMusic:
    def test_plays_through_api_when_a_device_is_live(self, sp, launched):
        sp.devices.return_value = {"devices": [
            {"id": "dev1", "name": "Mo's Laptop", "is_active": True}]}

        assert st.play_music("enta eih") == "Playing: Enta Eih by Nancy Ajram"
        sp.start_playback.assert_called_once_with(device_id="dev1",
                                                  uris=["spotify:track:abc"])
        assert launched == []

    def test_opens_the_app_on_the_track_when_no_device(self, sp, launched):
        sp.devices.return_value = {"devices": []}

        assert st.play_music("enta eih") == "Playing: Enta Eih by Nancy Ajram"
        sp.start_playback.assert_not_called()
        assert launched == ["spotify:track:abc"]

    def test_falls_back_to_the_app_when_playback_is_refused(self, sp, launched):
        """Free accounts get a 403 from the playback endpoint — the app still plays."""
        sp.devices.return_value = {"devices": [
            {"id": "dev1", "name": "Mo's Laptop", "is_active": True}]}
        sp.start_playback.side_effect = Exception("403 Premium required")

        assert st.play_music("enta eih") == "Playing: Enta Eih by Nancy Ajram"
        assert launched == ["spotify:track:abc"]

    def test_mood_query_resolves_to_a_playlist(self, sp, launched):
        sp.devices.return_value = {"devices": []}
        sp.search.return_value = _results(playlists=[
            {"uri": "spotify:playlist:xyz", "name": "Deep Focus"}])

        assert st.play_music("play something focus") == "Playing: focus vibes — Deep Focus"
        assert launched == ["spotify:playlist:xyz"]

    def test_skips_null_playlist_items(self, sp, launched):
        """Spotify's search returns null entries in the playlist list."""
        sp.devices.return_value = {"devices": []}
        sp.search.return_value = _results(playlists=[
            None, {"uri": "spotify:playlist:xyz", "name": "Tarab"}])

        assert st.play_music("tarab") == "Playing: playlist Tarab"
        assert launched == ["spotify:playlist:xyz"]

    def test_nothing_found(self, sp, launched):
        sp.devices.return_value = {"devices": []}
        sp.search.return_value = _results()

        assert st.play_music("asdfqwer") == "Nothing found for 'asdfqwer'"
        assert launched == []

    def test_without_credentials_opens_the_search_page(self, monkeypatch, launched):
        monkeypatch.setattr(st, "SPOTIFY_AVAILABLE", False)

        out = st.play_music("enta eih")
        assert launched == ["spotify:search:enta%20eih"]
        assert "searched for 'enta eih'" in out

    def test_reports_when_the_app_cannot_be_opened(self, sp, monkeypatch):
        sp.devices.return_value = {"devices": []}
        monkeypatch.setattr(st, "_launch_spotify_app", lambda uri="spotify:": False)

        assert "Couldn't open Spotify" in st.play_music("enta eih")
