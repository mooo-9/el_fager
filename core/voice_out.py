"""
Text-to-speech with automatic backend selection (best available wins):

  1. Groq Orpheus TTS  — neural voices, cloud GPU, < 1 s
                         English: canopylabs/orpheus-v1-english
                         Requires GROQ_API_KEY + one-time terms acceptance:
                           https://console.groq.com/playground?model=canopylabs%2Forpheus-v1-english
  2. Edge TTS          — Microsoft neural voices, free, always available

Voice customisation (.env):
  TTS_VOICE_EN  — Orpheus English voice  (default: daniel)
                  Options: autumn · diana · hannah · austin · daniel · troy

Edge TTS fallback voice:
  EDGE_VOICE_EN — default: en-US-GuyNeural
"""

import asyncio
import io
import os
import re
import tempfile
import threading
import time

import pygame.mixer

# speak() is called from the voice pipeline (QThread), the ProactiveEngine
# (daemon thread), and the scheduler — pygame has ONE music channel, so
# concurrent speaks must queue instead of cutting each other off mid-sentence.
_SPEAK_LOCK = threading.Lock()
from dotenv import load_dotenv

load_dotenv()

# ── Orpheus voices ──────────────────────────────────────────────────────────────
ORPHEUS_MODEL_EN    = "canopylabs/orpheus-v1-english"
# Defaults must be valid Orpheus voices (see docstring lists) — an invalid
# voice makes every Groq TTS call fail and silently fall back to Edge.
ORPHEUS_VOICE_EN    = os.getenv("TTS_VOICE_EN", "daniel")

# ── Edge TTS fallback voice ─────────────────────────────────────────────────────
EDGE_VOICE_EN       = os.getenv("EDGE_VOICE_EN", "en-US-GuyNeural")

_EMOJI_RE = re.compile(
    r"[\U0001F300-\U0001F9FF\U00002600-\U000027BF\U0001FA00-\U0001FAFF"
    r"\U0000FE00-\U0000FE0F\U00002300-\U000023FF\U00002B00-\U00002BFF]+"
)


def _clean(text: str) -> str:
    import re as _re
    # Strip markdown headings (## Title → Title)
    text = _re.sub(r"^#{1,6}\s+", "", text, flags=_re.MULTILINE)
    # Strip bold/italic markers (**text** → text, *text* → text, __text__ → text)
    text = _re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", text)
    text = _re.sub(r"_{1,2}([^_]+)_{1,2}", r"\1", text)
    # Strip inline code backticks, keep the content (`code` → code)
    text = _re.sub(r"`{1,3}([^`]*)`{1,3}", r"\1", text)
    # Strip URLs from markdown links [label](url) → label
    text = _re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    # Strip bare URLs
    text = _re.sub(r"https?://\S+", "", text)
    # Strip blockquotes
    text = _re.sub(r"^>\s*", "", text, flags=_re.MULTILINE)
    # Strip horizontal rules
    text = _re.sub(r"^[-_*]{3,}\s*$", "", text, flags=_re.MULTILINE)
    # Strip bullet/numbered list markers (- item → item, * item → item, 1. item → item)
    text = _re.sub(r"^[\s]*[-*+]\s+", "", text, flags=_re.MULTILINE)
    text = _re.sub(r"^[\s]*\d+\.\s+", "", text, flags=_re.MULTILINE)
    # Strip remaining lone # or * characters
    text = _re.sub(r"(?<!\w)[#*_`|](?!\w)", "", text)
    # Strip emojis
    text = _EMOJI_RE.sub("", text)
    # Collapse extra blank lines and whitespace
    text = _re.sub(r"\n{3,}", "\n\n", text)
    return _speakable(text.strip())


# Written abbreviations that a reader skims but a voice stumbles over: read
# aloud, "e.g." becomes "ee gee" and "24/7" becomes "twenty four slash seven".
# Ordered longest-first so "i.e." is not eaten by a shorter rule.
_SPOKEN = (
    (r"\be\.g\.,?", "for example,"),
    (r"\bi\.e\.,?", "that is,"),
    (r"\betc\.", "and so on"),
    (r"\bvs\.?\b", "versus"),
    (r"\bapprox\.", "approximately"),
    (r"\bw/o(?=\s|$)", "without"),          # before w/, or this becomes "with o"
    (r"\bw/(?=\s)", "with"),                # \b cannot follow a slash
    (r"\b24/7\b", "twenty four seven"),
    (r"\bFYI\b", "just so you know"),
    (r"\bASAP\b", "as soon as possible"),
    (r"\s+&\s+", " and "),
    # "3-4 hours" → "3 to 4 hours", but never inside a date: the guards on both
    # sides stop 2026-08-17 becoming "2026 to 08 to 17".
    (r"(?<![\d-])(\d{1,2})\s*-\s*(\d{1,2})(?![\d-])", r"\1 to \2"),
    (r"(?<=\w)/(?=\w)", " or "),            # "yes/no" → "yes or no"
)


def _speakable(text: str) -> str:
    """Make the text sound right rather than merely look right.

    The TTS reads exactly what it is given, so anything the eye expands
    silently has to be expanded here instead.
    """
    import re as _re
    for pattern, replacement in _SPOKEN:
        text = _re.sub(pattern, replacement, text, flags=_re.IGNORECASE)
    # Ellipses read as a stumble; a comma gives the pause without the stutter.
    text = text.replace("...", ", ").replace("…", ", ")
    # An em dash gets swallowed entirely by most voices — a comma is the pause
    # it was standing in for.
    text = _re.sub(r"\s*[—–]\s*", ", ", text)
    return _re.sub(r"[ \t]{2,}", " ", text).strip()


def _play_file(path: str, should_stop=None) -> bool:
    """Load and play an audio file through pygame, block until done, then
    clean up. Returns True if it was cut short.

    should_stop: called on the 50ms poll; when it returns True the audio is
    cut immediately. This is the barge-in hook — the whole point is that it
    stops mid-word, not at the end of the sentence.
    """
    interrupted = False
    try:
        pygame.mixer.music.load(path)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            if should_stop is not None and should_stop():
                interrupted = True
                break
            time.sleep(0.05)
    finally:
        pygame.mixer.music.stop()
        try:
            pygame.mixer.music.unload()
        except Exception:
            pass
        try:
            os.unlink(path)
        except OSError:
            pass
    return interrupted


def _discard(path: str) -> None:
    """Drop a synthesised chunk that will never be played."""
    try:
        os.unlink(path)
    except OSError:
        pass


class VoiceOutput:
    """
    pygame.mixer must already be initialised by the caller (main.py).
    This class does NOT call pygame.mixer.init().
    """

    def __init__(self):
        import json as _json
        try:
            _sf = "data/settings.json"
            _s = _json.loads(open(_sf, encoding="utf-8").read()) if os.path.exists(_sf) else {}
        except Exception:
            _s = {}
        self._backend: str = _s.get("tts_backend", "auto")
        self._voice_en: str = _s.get("voice_en", EDGE_VOICE_EN)

    def apply_settings(self, settings: dict) -> None:
        self._backend = settings.get("tts_backend", self._backend)
        self._voice_en = settings.get("voice_en", self._voice_en)

    def speak(self, text: str, should_stop=None) -> bool:
        """Speak one block. Returns True if it was interrupted."""
        text = _clean(text)
        if not text:
            return False

        with _SPEAK_LOCK:
            path = self._synthesize(text)
            if path:
                return _play_file(path, should_stop)
        return False

    def speak_stream(self, sentences, should_stop=None) -> bool:
        """Speak an iterable of text chunks with synth/playback pipelining:
        while chunk N plays, chunk N+1 is already being synthesized, so
        first audio starts as soon as the first sentence is ready and there
        are no synth gaps between sentences. Holds _SPEAK_LOCK for the whole
        stream so proactive/scheduler speech can't interleave mid-reply."""
        import queue as _queue
        audio_q: "_queue.Queue[str | None]" = _queue.Queue(maxsize=2)

        def _synth_worker():
            try:
                for chunk in sentences:
                    chunk = _clean(chunk)
                    if not chunk:
                        continue
                    path = self._synthesize(chunk)
                    if path:
                        audio_q.put(path)
            finally:
                audio_q.put(None)  # end-of-stream sentinel

        with _SPEAK_LOCK:
            worker = threading.Thread(target=_synth_worker, daemon=True)
            worker.start()
            first = True
            interrupted = False
            while True:
                path = audio_q.get()
                if path is None:
                    break
                if interrupted:
                    # Talked over: the rest of the reply is no longer wanted,
                    # but the queue still has to be drained and its temp files
                    # removed, or the synth worker blocks on a full queue.
                    _discard(path)
                    continue
                if first:
                    from core import turn_profile
                    turn_profile.mark("first_audio")
                    print("[El Fager] timing: first TTS audio playing.")
                    first = False
                interrupted = _play_file(path, should_stop)
            return interrupted

    # ── Synthesis (backend selection: Groq Orpheus → Edge TTS) ──────────────────

    def _synthesize(self, text: str) -> "str | None":
        """Synthesize text to a temp audio file; return its path (None on failure)."""
        groq_key = os.getenv("GROQ_API_KEY", "").strip()

        # ── 1. Try Groq Orpheus (skip if user chose edge in settings) ───────
        use_groq = self._backend != "edge"
        if use_groq and groq_key and not groq_key.startswith("gsk_xxx"):
            path = self._synth_groq(text)
            if path:
                return path

        # ── 2. Fall back to Edge TTS ─────────────────────────────────────
        return self._synth_edge(text)

    # ── Groq Orpheus ────────────────────────────────────────────────────────────

    def _synth_groq(self, text: str) -> "str | None":
        """Returns a temp WAV path on success, None on any failure (caller falls through)."""
        try:
            from groq import Groq
            client = Groq(api_key=os.getenv("GROQ_API_KEY"))

            response = client.audio.speech.create(
                model=ORPHEUS_MODEL_EN,
                voice=ORPHEUS_VOICE_EN,
                input=text,
                response_format="wav",
            )
            tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            tmp.write(response.read())
            tmp.close()
            return tmp.name

        except Exception as e:
            err = str(e)
            if "model_terms_required" in err or "terms" in err.lower():
                url = ORPHEUS_MODEL_EN
                print(
                    f"[El Fager] Groq Orpheus English TTS needs one-time terms acceptance.\n"
                    f"  → Open: https://console.groq.com/playground?model={url.replace('/', '%2F')}\n"
                    f"  → Click 'I agree', then restart El Fager.\n"
                    f"  Falling back to Edge TTS for now."
                )
            else:
                print(f"[El Fager] Groq TTS error: {e}")
            return None

    # ── Edge TTS (fallback) ─────────────────────────────────────────────────────

    def _synth_edge(self, text: str) -> "str | None":
        voice = self._voice_en
        tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        tmp.close()
        try:
            asyncio.run(self._edge_synthesize(text, tmp.name, voice))
            return tmp.name
        except Exception as e:
            print(f"[El Fager] Edge TTS error: {e}")
            try:
                os.unlink(tmp.name)
            except OSError:
                pass
            return None

    async def _edge_synthesize(self, text: str, path: str, voice: str):
        import edge_tts
        await edge_tts.Communicate(text, voice).save(path)

    def stop(self):
        try:
            pygame.mixer.music.stop()
        except Exception:
            pass
