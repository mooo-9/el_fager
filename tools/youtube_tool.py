"""
YouTube transcript fetcher — Phase 5B.
Fetches captions/auto-generated transcripts via youtube-transcript-api.
Claude then summarises, explains, or answers questions about the content.
"""

import re


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
    language — preferred language code (e.g. 'en', 'ar'); auto-detects if omitted
    """
    try:
        from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled
    except ImportError:
        return "[youtube-transcript-api not installed — run: pip install youtube-transcript-api]"

    video_id = _extract_video_id(url)
    if not video_id:
        return f"Could not extract a YouTube video ID from: {url}"

    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
    except TranscriptsDisabled:
        return f"Transcripts are disabled for this video ({video_id})."
    except Exception as e:
        return f"[YouTube error: {e}]"

    # Preference order: requested language, then English, then Arabic, then any
    candidates = []
    if language:
        candidates.append([language])
    candidates += [["en"], ["ar"], ["a.en"], ["a.ar"]]

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
        entries = transcript.fetch()
    except Exception as e:
        return f"[Could not fetch transcript: {e}]"

    text = " ".join(e["text"].replace("\n", " ") for e in entries)

    MAX_CHARS = 14_000
    truncated = ""
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS]
        truncated = f"\n\n[Transcript truncated at {MAX_CHARS:,} characters — {len(entries)} total segments]"

    return (
        f"YouTube transcript [{lang_label}] — video ID: {video_id} "
        f"({len(entries)} segments):\n\n{text}{truncated}"
    )
