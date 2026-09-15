"""'play X' should reach Spotify without a round trip to the model, and
without re-discovering the device on every request."""
from unittest.mock import MagicMock, patch

import pytest

import tools.spotify_tool as sp_tool
from tools.spotify_tool import match_play_command


@pytest.fixture(autouse=True)
def _clear_device_cache():
    sp_tool._device_id = None
    yield
    sp_tool._device_id = None


class TestMatchPlayCommand:
    @pytest.mark.parametrize("message,query", [
        ("play Blinding Lights", "Blinding Lights"),
        ("Play Bohemian Rhapsody on Spotify", "Bohemian Rhapsody"),
        ("hey el fager, play Amr Diab", "Amr Diab"),
        ("can you play some jazz", "jazz"),
        ("put on Daft Punk", "Daft Punk"),
        ("play me the song Numb", "Numb"),
    ])
    def test_english_commands(self, message, query):
        assert match_play_command(message) == (query, False)

    @pytest.mark.parametrize("message,query", [
        ("شغل عمرو دياب", "عمرو دياب"),
        ("شغللي أغنية تملي معاك", "تملي معاك"),
    ])
    def test_arabic_commands(self, message, query):
        assert match_play_command(message) == (query, True)

    def test_arabizi_command(self):
        assert match_play_command("sha3al cairokee") == ("cairokee", False)

    @pytest.mark.parametrize("message", [
        "play it",                     # no query
        "play it again",               # a replay, not a search
        "play some music",             # too vague to search for
        "play the next track",         # a skip
        "what's playing",              # a status question
        "playing music now",           # not a command
        "play the video on youtube",   # not Spotify
        "pause the music",
        "play",
        "what do you know about me",
    ])
    def test_falls_through_to_the_model(self, message):
        assert match_play_command(message) is None


class TestBrainFastPath:
    def _brain(self):
        from core.brain import Brain
        return Brain(profile={})

    def test_play_command_never_calls_the_api(self):
        brain = self._brain()
        with patch.object(brain.client.messages, "create") as create, \
             patch("tools.spotify_tool.play_music",
                   return_value="Playing: Blinding Lights by The Weeknd") as play:
            reply = brain.chat("play Blinding Lights")
        create.assert_not_called()
        play.assert_called_once_with("Blinding Lights", arabic=False)
        assert reply == "Playing: Blinding Lights by The Weeknd"

    def test_arabic_play_command_is_flagged_arabic(self):
        brain = self._brain()
        with patch.object(brain.client.messages, "create") as create, \
             patch("tools.spotify_tool.play_music", return_value="بشغّل: كذا") as play:
            brain.chat("شغل عمرو دياب")
        create.assert_not_called()
        play.assert_called_once_with("عمرو دياب", arabic=True)

    def test_other_requests_still_reach_the_api(self):
        brain = self._brain()
        block = MagicMock()
        block.type = "text"
        block.text = "It's 3:45 PM."
        response = MagicMock()
        response.stop_reason = "end_turn"
        response.content = [block]
        with patch.object(brain.client.messages, "create", return_value=response) as create:
            reply = brain.chat("what time is it")
        create.assert_called_once()
        assert reply == "It's 3:45 PM."


class TestDeviceCache:
    def _fake_client(self):
        sp = MagicMock()
        sp.devices.return_value = {"devices": [
            {"id": "dev1", "name": "Mo's PC", "is_active": True},
        ]}
        sp.search.return_value = {"tracks": {"items": [
            {"name": "Numb", "uri": "spotify:track:1",
             "artists": [{"name": "Linkin Park"}]},
        ]}}
        return sp

    def test_device_looked_up_once_across_plays(self):
        sp = self._fake_client()
        with patch.object(sp_tool, "SPOTIFY_AVAILABLE", True), \
             patch.object(sp_tool, "get_spotify", return_value=sp):
            sp_tool.play_music("numb")
            sp_tool.play_music("numb")
        assert sp.devices.call_count == 1
        assert sp.start_playback.call_count == 2

    def test_stale_device_is_reprobed_once(self):
        from spotipy.exceptions import SpotifyException
        sp = self._fake_client()
        sp.start_playback.side_effect = [
            SpotifyException(404, -1, "Device not found"),
            None,
        ]
        sp_tool._device_id = "gone"
        with patch.object(sp_tool, "SPOTIFY_AVAILABLE", True), \
             patch.object(sp_tool, "get_spotify", return_value=sp):
            result = sp_tool.play_music("numb")
        assert sp.start_playback.call_count == 2
        assert sp.start_playback.call_args.kwargs["device_id"] == "dev1"
        assert "Numb" in result

    def test_arabic_reply_for_arabic_request(self):
        sp = self._fake_client()
        with patch.object(sp_tool, "SPOTIFY_AVAILABLE", True), \
             patch.object(sp_tool, "get_spotify", return_value=sp):
            result = sp_tool.play_music("تملي معاك", arabic=True)
        assert result.startswith("بشغّل")


class TestFastPathErrorHandling:
    def test_tool_errors_fall_through_to_the_model(self):
        """A bracketed result means nothing played — Claude should phrase it."""
        from core.brain import Brain
        brain = Brain(profile={})
        block = MagicMock()
        block.type = "text"
        block.text = "Spotify isn't set up yet, Mo."
        response = MagicMock()
        response.stop_reason = "end_turn"
        response.content = [block]
        with patch.object(brain.client.messages, "create", return_value=response) as create, \
             patch("tools.spotify_tool.play_music",
                   return_value="[Spotify Premium required for playback control]"):
            reply = brain.chat("play Blinding Lights")
        create.assert_called_once()
        assert reply == "Spotify isn't set up yet, Mo."

    def test_nothing_found_is_answered_directly(self):
        from core.brain import Brain
        brain = Brain(profile={})
        with patch.object(brain.client.messages, "create") as create, \
             patch("tools.spotify_tool.play_music",
                   return_value="Nothing found for 'asdfgh'"):
            reply = brain.chat("play asdfgh")
        create.assert_not_called()
        assert reply == "Nothing found for 'asdfgh'"
