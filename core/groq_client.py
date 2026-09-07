"""
One Groq client for the process.

Constructing a client costs ~207 ms — it builds an httpx client underneath,
with the TLS and connection setup that implies. Both ends of the voice path
were building a fresh one every time: voice_in per transcription, voice_out
per *sentence* of the reply. A five-sentence answer therefore spent about a
second on nothing but client construction, against a time-to-first-token of
roughly 1.6 s.

The client is thread-safe and holds a connection pool, which is the thing
worth keeping: reusing it also reuses the warm TLS connection to Groq rather
than renegotiating one per sentence.

Built on first use rather than at import, so a run with no Groq key — or the
test suite — never pays for it.
"""
import os
import threading

_lock = threading.Lock()
_client = None


def get():
    """The shared client, or None when no usable key is configured.

    Returning None rather than raising keeps the callers' shape: both already
    fall back to a local model (STT) or Edge TTS when Groq is unavailable.
    """
    global _client
    if _client is not None:
        return _client
    key = (os.getenv("GROQ_API_KEY") or "").strip()
    if not key or key.startswith("gsk_xxx"):
        return None
    with _lock:
        if _client is None:                     # another thread may have won
            from groq import Groq
            _client = Groq(api_key=key)
    return _client


def reset() -> None:
    """Drop the cached client. For tests, and for a key change at runtime."""
    global _client
    with _lock:
        _client = None
