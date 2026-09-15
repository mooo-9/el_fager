"""Let El Fager read your Spotify Liked Songs — run this once.

    python scripts/spotify_library_login.py

It opens Spotify's approval page in your browser asking for one permission,
"user-library-read" (read your saved songs). Approve it, and the login is
saved to data/.spotify_library_cache. El Fager then reads your Liked Songs
once a day to learn the artist and song names you say, so Whisper spells them.

Playback's own login is separate and is not touched.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.chdir(Path(__file__).resolve().parent.parent)

from tools.spotify_tool import LIBRARY_CACHE, LIBRARY_SCOPE, SPOTIFY_AVAILABLE  # noqa: E402


def main() -> int:
    if not SPOTIFY_AVAILABLE:
        print("Spotify isn't set up: add SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET to .env.")
        return 1
    import spotipy
    from spotipy.oauth2 import SpotifyOAuth

    auth = SpotifyOAuth(
        client_id=os.getenv("SPOTIFY_CLIENT_ID"),
        client_secret=os.getenv("SPOTIFY_CLIENT_SECRET"),
        redirect_uri=os.getenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback"),
        scope=LIBRARY_SCOPE,
        cache_path=LIBRARY_CACHE,
        open_browser=True,
    )
    print("Opening Spotify in your browser — approve reading your saved songs.")
    client = spotipy.Spotify(auth_manager=auth)
    total = client.current_user_saved_tracks(limit=1)["total"]
    print(f"Done. El Fager can read your Liked Songs ({total} songs).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
