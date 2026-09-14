"""Reading Liked Songs has its own Spotify login, apart from playback's.

Adding user-library-read to playback's scope would make spotipy find the
saved token short of a scope and reopen the browser login on the next
"play …" — a voice turn left waiting on a web page. The library login lives
in its own cache, is granted once by a script Mo runs, and El Fager itself
only ever uses a token already saved: never a browser.
"""
import pytest

from tools import spotify_tool


class TestPlaybackIsUntouched:
    def test_playbacks_scope_is_what_its_saved_token_was_granted(self):
        assert set(spotify_tool.SCOPE.split()) == {
            "user-read-playback-state", "user-modify-playback-state",
            "user-read-currently-playing", "user-read-private"}

    def test_the_library_uses_its_own_cache_and_scope(self):
        assert spotify_tool.LIBRARY_SCOPE == "user-library-read"
        assert spotify_tool.LIBRARY_CACHE != "data/.spotify_cache"


class TestNeverABrowser:
    def test_with_no_saved_library_login_it_returns_none_quietly(self, monkeypatch, tmp_path):
        monkeypatch.setattr(spotify_tool, "SPOTIFY_AVAILABLE", True)
        monkeypatch.setattr(spotify_tool, "LIBRARY_CACHE", str(tmp_path / "missing_cache"))
        monkeypatch.setenv("SPOTIFY_CLIENT_ID", "id")
        monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", "secret")
        import webbrowser
        monkeypatch.setattr(webbrowser, "open", lambda *a, **k: pytest.fail("opened a browser"))
        assert spotify_tool.get_library_client() is None

    def test_without_spotify_set_up_it_returns_none(self, monkeypatch):
        monkeypatch.setattr(spotify_tool, "SPOTIFY_AVAILABLE", False)
        assert spotify_tool.get_library_client() is None

    def test_with_a_saved_library_login_it_builds_a_client(self, monkeypatch, tmp_path):
        import json
        import time
        cache = tmp_path / "library_cache"
        cache.write_text(json.dumps({
            "access_token": "tok", "token_type": "Bearer", "expires_in": 3600,
            "scope": "user-library-read", "expires_at": int(time.time()) + 3600,
            "refresh_token": "ref"}), encoding="utf-8")
        monkeypatch.setattr(spotify_tool, "SPOTIFY_AVAILABLE", True)
        monkeypatch.setattr(spotify_tool, "LIBRARY_CACHE", str(cache))
        monkeypatch.setenv("SPOTIFY_CLIENT_ID", "id")
        monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", "secret")
        assert spotify_tool.get_library_client() is not None


class TestTheLoginScript:
    def test_the_script_asks_for_exactly_the_library_scope(self):
        from pathlib import Path
        source = Path("scripts/spotify_library_login.py").read_text(encoding="utf-8")
        assert "LIBRARY_SCOPE" in source and "LIBRARY_CACHE" in source
        assert "open_browser=True" in source
