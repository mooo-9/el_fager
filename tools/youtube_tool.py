"""
YouTube — transcripts, search, and "latest video from <channel>".

Transcripts come from youtube-transcript-api. Search and channel lookups read
YouTube's public pages/feeds directly (no API key), and every lookup falls back
to opening the relevant YouTube page in Comet, so a "play X" always gets Mo
somewhere useful even if YouTube changes its markup.
"""

import re
import urllib.parse

import httpx

# YouTube serves a stripped page to unrecognised clients.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}
_TIMEOUT = 10

_WATCH = "https://www.youtube.com/watch?v={}"
_SEARCH_PAGE = "https://www.youtube.com/results?search_query={}"
_FEED = "https://www.youtube.com/feeds/videos.xml?channel_id={}"


def _extract_video_id(url_or_id: str) -> str | None:
    """Return the 11-char YouTube video ID from a URL or bare ID."""
    s = url_or_id.strip()
    # Bare ID
    if re.match(r"^[a-zA-Z0-9_-]{11}$", s):
        return s
    patterns = [
        r"(?:v=)([a-zA-Z0-9_-]{11})",
        r"youtu\.be/([a-zA-Z0-9_-]{11})",
        r"(?:embed|shorts)/([a-zA-Z0-9_-]{11})",
    ]
    for p in patterns:
        m = re.search(p, s)
        if m:
            return m.group(1)
    return None


def get_youtube_transcript(url: str, language: str = None) -> str:
    """
    Fetch the transcript of a YouTube video.
    url      — full YouTube URL or bare video ID
    language — preferred transcript language code; defaults to English
    """
    try:
        from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled
    except ImportError:
        return "[youtube-transcript-api not installed — run: pip install youtube-transcript-api]"

    video_id = _extract_video_id(url)
    if not video_id:
        return f"Could not extract a YouTube video ID from: {url}"

    # youtube-transcript-api 1.x replaced the classmethod API with an instance
    # one: list_transcripts() became list(). The old call raised AttributeError,
    # which the except below swallowed into a returned string — so this failed
    # silently rather than loudly.
    try:
        transcript_list = YouTubeTranscriptApi().list(video_id)
    except TranscriptsDisabled:
        return f"Transcripts are disabled for this video ({video_id})."
    except Exception as e:
        return f"[YouTube error: {e}]"

    # Preference order: requested language, then English, then any
    candidates = []
    if language:
        candidates.append([language])
    candidates += [["en"], ["a.en"]]

    transcript = None
    lang_label = "unknown"
    for langs in candidates:
        try:
            transcript = transcript_list.find_transcript(langs)
            lang_label = transcript.language
            break
        except NoTranscriptFound:
            continue

    if transcript is None:
        # Last resort: grab whatever exists
        try:
            all_t = list(transcript_list)
            if all_t:
                transcript = all_t[0]
                lang_label = transcript.language
        except Exception:
            pass

    if transcript is None:
        return f"No transcript available for video {video_id}."

    try:
        entries = list(transcript.fetch())
    except Exception as e:
        return f"[Could not fetch transcript: {e}]"

    # 1.x yields FetchedTranscriptSnippet objects, not dicts. Accept either, so
    # the tool survives the next version bump in whichever direction it goes.
    def _text(entry) -> str:
        raw = entry["text"] if isinstance(entry, dict) else getattr(entry, "text", "")
        return raw.replace("\n", " ")

    text = " ".join(_text(e) for e in entries)

    MAX_CHARS = 14_000
    truncated = ""
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS]
        truncated = f"\n\n[Transcript truncated at {MAX_CHARS:,} characters — {len(entries)} total segments]"

    return (
        f"YouTube transcript [{lang_label}] — video ID: {video_id} "
        f"({len(entries)} segments):\n\n{text}{truncated}"
    )


# ── Search ────────────────────────────────────────────────────────────────────

def _first_video(html: str) -> "tuple[str, str] | None":
    """Pull (video_id, title) for the first result out of a YouTube results page.

    YouTube embeds its data as JSON inside the page; videoRenderer entries are
    the actual videos (ads and shelves use different keys).
    """
    m = re.search(
        r'"videoRenderer":\{"videoId":"([\w-]{11})".*?'
        r'"title":\{"runs":\[\{"text":"(.*?)"\}',
        html,
        re.DOTALL,
    )
    if m:
        return m.group(1), _unescape(m.group(2))
    # Markup changed — settle for any video id so we can still open something.
    m = re.search(r'"videoId":"([\w-]{11})"', html)
    return (m.group(1), "") if m else None


def _unescape(text: str) -> str:
    """Undo the backslash escaping in YouTube's embedded JSON strings."""
    try:
        import json
        return json.loads(f'"{text}"')
    except Exception:
        return text


def youtube_search(query: str, open_it: bool = True) -> str:
    """Find the top YouTube video for a query and open it in Comet."""
    from tools.comet_tool import open_url

    encoded = urllib.parse.quote_plus(query)
    search_url = _SEARCH_PAGE.format(encoded)

    try:
        resp = httpx.get(search_url, headers=_HEADERS, timeout=_TIMEOUT,
                         follow_redirects=True)
        found = _first_video(resp.text) if resp.status_code == 200 else None
    except Exception:
        found = None

    if found is None:
        # Couldn't read the page — hand Mo the search results instead of failing.
        if open_it:
            open_url(search_url)
            return f"Opened YouTube search for '{query}' — couldn't pick the top result automatically."
        return f"[Could not read YouTube results for '{query}'] {search_url}"

    video_id, title = found
    url = _WATCH.format(video_id)
    if open_it:
        open_url(url)
        return f"Playing on YouTube: {title or url}"
    return f"{title or 'Video'} — {url}"


# ── Channels ──────────────────────────────────────────────────────────────────

def _channel_id(channel: str) -> "str | None":
    """Resolve a handle, name, URL, or bare channel ID to a UC... channel ID."""
    channel = channel.strip()

    m = re.search(r"(UC[\w-]{22})", channel)
    if m:
        return m.group(1)

    if channel.startswith("http"):
        url = channel
    else:
        handle = channel.lstrip("@").replace(" ", "")
        url = f"https://www.youtube.com/@{handle}"

    try:
        resp = httpx.get(url, headers=_HEADERS, timeout=_TIMEOUT, follow_redirects=True)
        if resp.status_code == 200:
            m = re.search(r'"(?:channelId|externalId)":"(UC[\w-]{22})"', resp.text)
            if m:
                return m.group(1)
    except Exception:
        pass
    return None


def youtube_latest(channel: str, open_it: bool = True) -> str:
    """Open the newest video from a channel. Channel can be a handle, name,
    URL, or channel ID."""
    from tools.comet_tool import open_url

    chan_id = _channel_id(channel)
    if chan_id is None:
        # Fall back to searching for the channel so Mo still lands somewhere.
        if open_it:
            open_url(_SEARCH_PAGE.format(urllib.parse.quote_plus(channel)))
            return f"Couldn't find the channel '{channel}' — opened a YouTube search instead."
        return f"[Could not resolve channel '{channel}']"

    try:
        resp = httpx.get(_FEED.format(chan_id), headers=_HEADERS, timeout=_TIMEOUT,
                         follow_redirects=True)
        if resp.status_code != 200:
            raise RuntimeError(f"feed returned {resp.status_code}")
        # The feed is newest-first; entries carry videoId and title.
        vid = re.search(r"<yt:videoId>([\w-]{11})</yt:videoId>", resp.text)
        # The first <title> is the channel's; the second is the newest video.
        titles = re.findall(r"<title>(.*?)</title>", resp.text, re.DOTALL)
        video_title = titles[1].strip() if len(titles) > 1 else ""
    except Exception as e:
        if open_it:
            open_url(f"https://www.youtube.com/channel/{chan_id}/videos")
            return f"Opened {channel}'s videos — couldn't read the feed ({e})."
        return f"[Could not read the feed for '{channel}': {e}]"

    if not vid:
        if open_it:
            open_url(f"https://www.youtube.com/channel/{chan_id}/videos")
            return f"Opened {channel}'s videos — the feed had no entries."
        return f"[No videos in the feed for '{channel}']"

    url = _WATCH.format(vid.group(1))
    if open_it:
        open_url(url)
        return f"Latest from {channel}: {video_title or url}"
    return f"{video_title or 'Latest video'} — {url}"
