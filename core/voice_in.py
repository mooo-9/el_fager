"""
Speech-to-text with automatic backend selection (best available wins):

  1. Groq Whisper API  — cloud GPU, < 1 s latency, free tier (set GROQ_API_KEY in .env)
  2. faster-whisper    — local, 4–6× faster than openai-whisper + int8 quantisation
  3. openai-whisper    — always installed; fallback of last resort

VAD (end-of-speech detection):
  Silero VAD neural network loads after Whisper. Replaces the old RMS timer.
  Recording stops after 1.0 s of frames the model classifies as non-speech —
  short enough to feel responsive, long enough for natural mid-sentence pauses
  (typically 200–800 ms) not to trigger an early cut-off.
"""

import io
import os
import queue
import threading
import wave as _wave
from typing import Callable
import numpy as np
import sounddevice as sd

from dotenv import load_dotenv
load_dotenv()

SAMPLE_RATE = 16000
MAX_RECORD_SECONDS = 60

# Silero VAD settings
VAD_CHUNK = 512           # 32 ms at 16 kHz — required frame size
SPEECH_THRESHOLD = 0.5    # probability above which a frame counts as speech
END_SILENCE_SEC = 1.0     # seconds of continuous non-speech before stopping
TRAIL_KEEP_SEC = 0.4      # keep a short tail so Whisper sees the sentence boundary

# RMS fallback settings (if Silero VAD fails to load)
RMS_CHUNK_SEC = 0.1
RMS_THRESHOLD = 0.01
RMS_SILENCE_SEC = 1.5     # RMS can't tell soft speech from silence — keep a margin

# Hallucination guards.
# El Fager listens in English only, so transcription is forced to English.
# Because the decode is forced, the backend echoes "en" back and the language
# check is only a backstop against a backend that ignores the request — the
# real filter on noise is NO_SPEECH_MAX.
TRANSCRIBE_LANGUAGE = "en"
NO_SPEECH_MAX = 0.6  # drop segments Whisper itself flags as probable non-speech

_BACKEND_GROQ   = "groq"
_BACKEND_FASTER = "faster_whisper"
_BACKEND_OPENAI = "openai_whisper"


_BIAS_CACHE: "str | None" = None


def _bias_prompt() -> str:
    """A sample utterance in the style we want back.

    Whisper's `prompt` is not an instruction — it is treated as text preceding
    the audio, and the decode continues its style and vocabulary. So this is
    written as a real sentence Mo might say, carrying the proper nouns Whisper
    otherwise guesses at, and punctuated the way a transcript should read.

    Built from the profile and contacts so it stays true as those change, and
    kept short: the prompt window is small and long ones crowd out the audio.
    """
    global _BIAS_CACHE
    if _BIAS_CACHE is not None:
        return _BIAS_CACHE

    names: list[str] = []
    try:
        import json
        from pathlib import Path
        profile = json.loads(Path("profile.json").read_text(encoding="utf-8"))
        for key in ("name", "full_name"):
            value = (profile.get(key) or "").strip()
            if value and value not in names:
                names.append(value)
    except Exception:
        pass
    try:
        import json
        from pathlib import Path
        contacts = json.loads(Path("data/contacts.json").read_text(encoding="utf-8"))
        for person in list(contacts)[:8]:
            person = str(person).strip()
            if person and person.lower() != "test user" and person not in names:
                names.append(person)
    except Exception:
        pass

    who = ", ".join(names[:6]) if names else "Mo"
    _BIAS_CACHE = (
        f"Hey El Fager, remind {who} about the review at 4 PM, "
        f"check my Todoist and my Obsidian notes, and tell me what's on my calendar."
    )
    return _BIAS_CACHE


def _numpy_to_wav_bytes(audio: np.ndarray, sr: int = SAMPLE_RATE) -> bytes:
    """Convert float32 mono numpy array → 16-bit PCM WAV bytes (stdlib only)."""
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
    buf = io.BytesIO()
    with _wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm.tobytes())
    return buf.getvalue()


def _is_english(language: "str | None") -> bool:
    """Backends disagree on how to name a language: Groq's verbose_json says
    "English", faster-whisper says "en", others say "en-US". Comparing the raw
    value against "en" silently discarded every utterance from Groq — the
    normalisation here is the whole point of the function.

    Unknown or missing is treated as English: the decode was forced to English,
    so a backend that declines to say is not evidence of anything else.
    """
    if not language:
        return True
    head = language.strip().lower().replace("_", "-").split("-")[0]
    return head in {"en", "eng", "english"}


def _join_speech_segments(language: str | None,
                          segments: "list[tuple[str, float | None]]") -> str:
    """
    Join (text, no_speech_prob) segments into a transcript, dropping segments
    Whisper flags as probable non-speech.

    `language` must be what the backend actually *reported*, not the constant
    we asked it for — pass the constant and the check below compares "en" to
    "en" and can never fire. It is a backstop for a backend that ignores the
    forced language, not the main hallucination filter; that job belongs to
    NO_SPEECH_MAX, since a decode forced to English cannot report anything else.
    """
    if not _is_english(language):
        return ""
    kept = [t.strip() for t, p in segments
            if t.strip() and (p is None or p < NO_SPEECH_MAX)]
    return " ".join(kept).strip()


def _normalise(audio: np.ndarray) -> np.ndarray:
    """Peak-normalise to 90 % FS so quiet recordings are easier to transcribe."""
    peak = np.abs(audio).max()
    if peak > 0:
        audio = audio / peak * 0.9
    return audio.astype(np.float32)


class VoiceInput:
    def __init__(self):
        self._whisper   = None          # faster-whisper or openai-whisper model
        self._vad_model = None          # Silero VAD
        self._backend   = _BACKEND_OPENAI
        self._model_ready = threading.Event()
        self._stop_flag   = threading.Event()

        threading.Thread(target=self._load_models, daemon=True).start()

    # ── Model loading ──────────────────────────────────────────────────────────

    def _load_models(self):
        groq_key = os.getenv("GROQ_API_KEY", "").strip()

        # ── 1. Try Groq API (cloud GPU, < 1 s, free tier) ─────────────────────
        if groq_key and not groq_key.startswith("gsk_xxx"):
            try:
                from groq import Groq  # noqa: F401 — just verify importable
                self._backend = _BACKEND_GROQ
                self._model_ready.set()
                print("[El Fager] Transcription: Groq Whisper API (cloud, < 1 s).")
                self._load_vad()
                return
            except ImportError:
                print("[El Fager] groq package not installed — falling back to local.")

        # ── 2. Try faster-whisper (local, 4–6× speed, int8) ───────────────────
        model_name = os.getenv("WHISPER_MODEL", "large-v3-turbo")
        try:
            from faster_whisper import WhisperModel
            print(f"[El Fager] Loading faster-whisper '{model_name}' on CPU (int8)…")
            self._whisper = WhisperModel(
                model_name,
                device="cpu",
                compute_type="int8",
            )
            self._backend = _BACKEND_FASTER
            self._model_ready.set()
            print(f"[El Fager] faster-whisper '{model_name}' ready.")
            self._load_vad()
            return
        except ImportError:
            print("[El Fager] faster-whisper not installed — using openai-whisper.")
        except Exception as e:
            print(f"[El Fager] faster-whisper failed ({e}) — falling back.")

        # ── 3. openai-whisper (always installed) ───────────────────────────────
        import whisper
        print(f"[El Fager] Loading openai-whisper '{model_name}' on CPU…")
        self._whisper = whisper.load_model(model_name, device="cpu")
        self._backend = _BACKEND_OPENAI
        self._model_ready.set()
        print(f"[El Fager] openai-whisper '{model_name}' ready.")
        self._load_vad()

    def _load_vad(self):
        """Load Silero VAD after the ASR model (best-effort)."""
        try:
            import torch
            vad, _ = torch.hub.load(
                repo_or_dir="snakers4/silero-vad",
                model="silero_vad",
                force_reload=False,
                trust_repo=True,
            )
            vad.eval()
            self._vad_model = vad
            print("[El Fager] Silero VAD ready — smart end-of-speech active.")
        except Exception as e:
            print(f"[El Fager] Silero VAD unavailable, RMS fallback active: {e}")

    # ── Public API ─────────────────────────────────────────────────────────────

    def is_ready(self) -> bool:
        return self._model_ready.is_set()

    def wait_until_ready(self, timeout: float = 180) -> bool:
        return self._model_ready.wait(timeout=timeout)

    def stop_recording(self):
        self._stop_flag.set()

    # ── Recording ──────────────────────────────────────────────────────────────

    def record_audio(
        self,
        on_chunk: "Callable[[float], None] | None" = None,
        start_timeout_sec: float | None = None,
    ) -> "np.ndarray | None":
        """
        Record until the speaker is truly done talking.
        Uses Silero VAD if loaded, otherwise falls back to RMS silence detection.
        on_chunk, if given, is called with a 0.0-1.0 amplitude estimate per chunk
        (from the recording thread — safe to bridge into a Qt signal).
        start_timeout_sec: give up (return None) if speech hasn't started within
        this many seconds — used by conversation mode's follow-up window.
        """
        self._stop_flag.clear()
        if self._vad_model is not None:
            return self._record_vad(on_chunk, start_timeout_sec)
        return self._record_rms(on_chunk, start_timeout_sec)

    def _record_vad(
        self,
        on_chunk: "Callable[[float], None] | None" = None,
        start_timeout_sec: float | None = None,
    ) -> "np.ndarray | None":
        """
        Neural end-of-speech via Silero VAD.
        Stops only after END_SILENCE_SEC of frames the model says aren't speech.
        Mid-sentence pauses (200–800 ms) never trigger a stop.
        """
        import torch

        end_frames  = int(END_SILENCE_SEC * SAMPLE_RATE / VAD_CHUNK)
        trail_frames = int(TRAIL_KEEP_SEC  * SAMPLE_RATE / VAD_CHUNK)
        max_frames  = int(MAX_RECORD_SECONDS * SAMPLE_RATE / VAD_CHUNK)
        start_frames = (int(start_timeout_sec * SAMPLE_RATE / VAD_CHUNK)
                        if start_timeout_sec else None)

        chunks: list[np.ndarray] = []
        aq: queue.Queue = queue.Queue(maxsize=200)

        def _cb(indata, frames, t, s):
            if not self._stop_flag.is_set():
                try:
                    aq.put_nowait(indata.copy().flatten())
                except queue.Full:
                    pass

        speech_started = False
        consec_silence = 0
        self._vad_model.reset_states()

        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            blocksize=VAD_CHUNK,
            callback=_cb,
        ):
            while not self._stop_flag.is_set() and len(chunks) < max_frames:
                try:
                    chunk = aq.get(timeout=0.1)
                except queue.Empty:
                    continue

                chunks.append(chunk)
                if on_chunk is not None:
                    rms = float(np.sqrt(np.mean(chunk ** 2)))
                    on_chunk(min(1.0, rms * 6.0))

                with torch.no_grad():
                    prob = self._vad_model(
                        torch.from_numpy(chunk).float().unsqueeze(0),
                        SAMPLE_RATE,
                    ).item()

                if prob >= SPEECH_THRESHOLD:
                    speech_started = True
                    consec_silence = 0
                elif speech_started:
                    consec_silence += 1
                    if consec_silence >= end_frames:
                        break
                elif start_frames is not None and len(chunks) >= start_frames:
                    break  # follow-up window expired with no speech

        if self._stop_flag.is_set() or not speech_started:
            return None

        # Trim most trailing silence; keep a short tail for Whisper
        trim = max(len(chunks) - end_frames + trail_frames, 1)
        return np.concatenate(chunks[:trim]).flatten()

    def _record_rms(
        self,
        on_chunk: "Callable[[float], None] | None" = None,
        start_timeout_sec: float | None = None,
    ) -> "np.ndarray | None":
        """RMS fallback — 2.5 s silence window, 100 ms chunks."""
        chunk_size = int(SAMPLE_RATE * RMS_CHUNK_SEC)
        silence_needed = int(RMS_SILENCE_SEC / RMS_CHUNK_SEC)
        max_chunks = int(MAX_RECORD_SECONDS / RMS_CHUNK_SEC)
        start_chunks = (int(start_timeout_sec / RMS_CHUNK_SEC)
                        if start_timeout_sec else None)

        chunks: list[np.ndarray] = []
        consec_silence = 0
        speech_started = False

        def _cb(indata, frames, t, s):
            chunks.append(indata.copy())

        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            blocksize=chunk_size,
            callback=_cb,
        ):
            while not self._stop_flag.is_set() and len(chunks) < max_chunks:
                sd.sleep(int(RMS_CHUNK_SEC * 1000))
                if not chunks:
                    continue
                rms = float(np.sqrt(np.mean(chunks[-1] ** 2)))
                if on_chunk is not None:
                    on_chunk(min(1.0, rms * 6.0))
                if rms >= RMS_THRESHOLD:
                    speech_started = True
                    consec_silence = 0
                elif speech_started:
                    consec_silence += 1
                if speech_started and consec_silence >= silence_needed:
                    break
                if (not speech_started and start_chunks is not None
                        and len(chunks) >= start_chunks):
                    break  # follow-up window expired with no speech

        if self._stop_flag.is_set() or not speech_started:
            return None

        return np.concatenate(chunks, axis=0).flatten()

    # ── Transcription ──────────────────────────────────────────────────────────

    def transcribe(self, audio: np.ndarray) -> str:
        """
        Convert float32 numpy audio → text using the best available backend.
        Transcription is forced to English. Segments Whisper flags as probable
        non-speech are dropped; a decode that comes back tagged as some other
        language is dropped too, though a backend honouring the forced language
        will not produce one.
        """
        if audio is None or len(audio) < SAMPLE_RATE * 0.3:
            return ""

        audio = _normalise(audio)

        if self._backend == _BACKEND_GROQ:
            return self._transcribe_groq(audio)
        if self._backend == _BACKEND_FASTER:
            return self._transcribe_faster(audio)
        return self._transcribe_openai(audio)

    def _transcribe_groq(self, audio: np.ndarray) -> str:
        try:
            from core import groq_client
            client = groq_client.get()
            if client is None:
                raise RuntimeError("no Groq key configured")
            wav = _numpy_to_wav_bytes(audio)
            result = client.audio.transcriptions.create(
                model="whisper-large-v3-turbo",
                file=("audio.wav", wav),
                response_format="verbose_json",
                language=TRANSCRIBE_LANGUAGE,
                prompt=_bias_prompt(),
            )
            raw_segments = getattr(result, "segments", None) or []
            segments = [
                (
                    (s.get("text", "") if isinstance(s, dict) else getattr(s, "text", "")),
                    (s.get("no_speech_prob") if isinstance(s, dict) else getattr(s, "no_speech_prob", None)),
                )
                for s in raw_segments
            ]
            if not segments:  # API variant without segment detail
                segments = [(getattr(result, "text", "") or "", None)]
            detected = getattr(result, "language", None)
            return _join_speech_segments(detected or TRANSCRIBE_LANGUAGE, segments)
        except Exception as e:
            print(f"[El Fager] Groq transcription error: {e}")
            # Graceful degradation: fall back to local if available
            if self._whisper is not None:
                if self._backend == _BACKEND_FASTER:
                    return self._transcribe_faster(audio)
                return self._transcribe_openai(audio)
            return ""

    def _transcribe_faster(self, audio: np.ndarray) -> str:
        segments, info = self._whisper.transcribe(
            audio,
            language=TRANSCRIBE_LANGUAGE,
            initial_prompt=_bias_prompt(),
            beam_size=5,
            best_of=5,
            temperature=0.0,
            condition_on_previous_text=False,
            vad_filter=False,  # we handle VAD ourselves
        )
        pairs = [(s.text, getattr(s, "no_speech_prob", None)) for s in segments]
        return _join_speech_segments(
            getattr(info, "language", None) or TRANSCRIBE_LANGUAGE, pairs)

    def _transcribe_openai(self, audio: np.ndarray) -> str:
        result = self._whisper.transcribe(
            audio,
            language=TRANSCRIBE_LANGUAGE,
            initial_prompt=_bias_prompt(),
            task="transcribe",
            fp16=False,
            temperature=0.0,
            condition_on_previous_text=False,
        )
        pairs = [(s.get("text", ""), s.get("no_speech_prob"))
                 for s in result.get("segments", [])]
        if not pairs:
            pairs = [(result.get("text", ""), None)]
        return _join_speech_segments(
            result.get("language") or TRANSCRIBE_LANGUAGE, pairs)
