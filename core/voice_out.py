"""
Text-to-speech with automatic backend selection (best available wins):

  1. Groq Orpheus TTS  — neural voices, cloud GPU, < 1 s
                         English: canopylabs/orpheus-v1-english
                         Arabic:  canopylabs/orpheus-arabic-saudi
                         Requires GROQ_API_KEY + one-time terms acceptance:
                           https://console.groq.com/playground?model=canopylabs%2Forpheus-v1-english
                           https://console.groq.com/playground?model=canopylabs%2Forpheus-arabic-saudi
  2. Edge TTS          — Microsoft neural voices, free, always available

Voice customisation (.env):
  TTS_VOICE_EN  — Orpheus English voice  (default: daniel)
                  Options: autumn · diana · hannah · austin · daniel · troy
  TTS_VOICE_AR  — Orpheus Arabic voice   (default: fahad)
                  Options: fahad · sultan · noura · lulwa · aisha · abdullah

Edge TTS fallback voices:
  EDGE_VOICE_EN — default: en-US-GuyNeural
  EDGE_VOICE_AR — default: ar-EG-ShakirNeural
"""

import asyncio
import io
import os
import re
import tempfile
import time

import pygame.mixer
from dotenv import load_dotenv

load_dotenv()

# ── Orpheus voices ──────────────────────────────────────────────────────────────
ORPHEUS_MODEL_EN    = "canopylabs/orpheus-v1-english"
ORPHEUS_MODEL_AR    = "canopylabs/orpheus-arabic-saudi"
ORPHEUS_VOICE_EN    = os.getenv("TTS_VOICE_EN", "tara")
ORPHEUS_VOICE_AR    = os.getenv("TTS_VOICE_AR", "jada")

# ── Edge TTS fallback voices ────────────────────────────────────────────────────
EDGE_VOICE_EN       = os.getenv("EDGE_VOICE_EN", "en-US-GuyNeural")
EDGE_VOICE_AR       = os.getenv("EDGE_VOICE_AR", "ar-EG-ShakirNeural")

_EMOJI_RE = re.compile(
    r"[\U0001F300-\U0001F9FF\U00002600-\U000027BF\U0001FA00-\U0001FAFF"
    r"\U0000FE00-\U0000FE0F\U00002300-\U000023FF\U00002B00-\U00002BFF]+"
)


def _is_arabic(text: str) -> bool:
    """Return True when > 20 % of alphabetic chars are Arabic Unicode."""
    arabic = sum(1 for c in text if "؀" <= c <= "ۿ")
    alpha  = sum(1 for c in text if c.isalpha())
    return alpha > 0 and arabic / alpha > 0.20


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
    return text.strip()


def _play_wav_bytes(data: bytes):
    """Write WAV bytes to a temp file and play through pygame, then delete."""
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.write(data)
    tmp.close()
    _play_file(tmp.name)


def _play_file(path: str):
    """Load and play an audio file through pygame, block until done, then clean up."""
    try:
        pygame.mixer.music.load(path)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
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
        self._voice_ar: str = _s.get("voice_ar", EDGE_VOICE_AR)

    def apply_settings(self, settings: dict) -> None:
        self._backend = settings.get("tts_backend", self._backend)
        self._voice_en = settings.get("voice_en", self._voice_en)
        self._voice_ar = settings.get("voice_ar", self._voice_ar)

    def speak(self, text: str):
        text = _clean(text)
        if not text:
            return

        arabic = _is_arabic(text)
        groq_key = os.getenv("GROQ_API_KEY", "").strip()

        # ── 1. Try Groq Orpheus (skip if user chose edge in settings) ───────────
        use_groq = self._backend != "edge"
        if use_groq and groq_key and not groq_key.startswith("gsk_xxx"):
            if self._speak_groq(text, arabic):
                return

        # ── 2. Fall back to Edge TTS ─────────────────────────────────────────
        self._speak_edge(text, arabic)

    # ── Groq Orpheus ────────────────────────────────────────────────────────────

    def _speak_groq(self, text: str, arabic: bool) -> bool:
        """Returns True on success, False on any failure (caller falls through)."""
        try:
            from groq import Groq
            client = Groq(api_key=os.getenv("GROQ_API_KEY"))

            model = ORPHEUS_MODEL_AR if arabic else ORPHEUS_MODEL_EN
            voice = ORPHEUS_VOICE_AR if arabic else ORPHEUS_VOICE_EN

            response = client.audio.speech.create(
                model=model,
                voice=voice,
                input=text,
                response_format="wav",
            )
            _play_wav_bytes(response.read())
            return True

        except Exception as e:
            err = str(e)
            if "model_terms_required" in err or "terms" in err.lower():
                model_label = "Arabic" if arabic else "English"
                url = ORPHEUS_MODEL_AR if arabic else ORPHEUS_MODEL_EN
                print(
                    f"[El Fager] Groq Orpheus {model_label} TTS needs one-time terms acceptance.\n"
                    f"  → Open: https://console.groq.com/playground?model={url.replace('/', '%2F')}\n"
                    f"  → Click 'I agree', then restart El Fager.\n"
                    f"  Falling back to Edge TTS for now."
                )
            else:
                print(f"[El Fager] Groq TTS error: {e}")
            return False

    # ── Edge TTS (fallback) ─────────────────────────────────────────────────────

    def _speak_edge(self, text: str, arabic: bool):
        voice = self._voice_ar if arabic else self._voice_en
        tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        tmp.close()
        try:
            asyncio.run(self._edge_synthesize(text, tmp.name, voice))
            _play_file(tmp.name)
        except Exception as e:
            print(f"[El Fager] Edge TTS error: {e}")

    async def _edge_synthesize(self, text: str, path: str, voice: str):
        import edge_tts
        await edge_tts.Communicate(text, voice).save(path)

    def stop(self):
        try:
            pygame.mixer.music.stop()
        except Exception:
            pass
