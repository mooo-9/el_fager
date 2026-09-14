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
import json
import os
import queue
import re
import threading
import wave as _wave
from collections import Counter
from pathlib import Path

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

# Loudness for the Cockpit's sphere to swell with while it listens: at the
# floor it is still, at full it swells most. The floor sits under
# RMS_THRESHOLD (-40 dBFS) so speech always moves it; full is a raised voice
# close to the mic.
LEVEL_FLOOR_DB = -50.0
LEVEL_FULL_DB = -20.0

# Hallucination guards.
# El Fager listens in English only, so transcription is forced to English.
# Because the decode is forced, the backend echoes "en" back and the language
# check is only a backstop against a backend that ignores the request — the
# real filter on noise is NO_SPEECH_MAX.
TRANSCRIBE_LANGUAGE = "en"
NO_SPEECH_MAX = 0.6  # drop segments Whisper itself flags as probable non-speech

# A decode stuck in a loop over music or noise repeats one short phrase:
# "I'm sorry. I'm sorry. I'm sorry." Whisper's compression-ratio check misses
# these — zlib barely compresses a sentence this short. So count it directly:
# a transcript is a loop when most of its words belong to a 3-word phrase that
# occurs 3+ times. Over the logged transcripts, real speech tops out at 0.31
# ("how are you … How are you, Fager? How are you?") and loops start at 0.46.
LOOP_PHRASE_WORDS = 3
LOOP_MIN_REPEATS = 3
LOOP_COVERAGE_MAX = 0.4

_BACKEND_GROQ   = "groq"
_BACKEND_FASTER = "faster_whisper"
_BACKEND_OPENAI = "openai_whisper"


_PROFILE = Path("profile.json")
_CONTACTS = Path("data/contacts.json")
_SETTINGS = Path("data/settings.json")

# Whisper keeps only the last 224 tokens of a prompt, and a long one crowds
# out the audio it is meant to help. ~600 characters stays well inside that.
BIAS_PROMPT_MAX_CHARS = 600

# (mtimes of the files it is built from, prompt built from them)
_BIAS_CACHE: "tuple | None" = None


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _vocabulary() -> "list[str]":
    """Every name Whisper should know, in priority order: Settings →
    voice_vocabulary, then names learned from songs played and kept, then
    Spotify Liked Songs. Case-insensitive repeats dropped."""
    try:
        by_hand = _read_json(_SETTINGS).get("voice_vocabulary", []) or []
    except Exception:
        by_hand = []
    try:
        from core import voice_learned
        learned = voice_learned.names()
    except Exception:
        learned = []
    try:
        from core import voice_liked
        liked = voice_liked.names()
    except Exception:
        liked = []
    out, seen = [], set()
    for word in [*by_hand, *learned, *liked]:
        word = str(word).strip()
        if word and word.lower() not in seen:
            seen.add(word.lower())
            out.append(word)
    return out


# ── Correcting near-misses of known names ─────────────────────────────────────
# Even with a name in the hint, Whisper writes what it hears: "Abusif" for
# Abyusif, "Hussain Yasser" for Hussein Yasser. A stretch of the transcript
# close enough to a known name becomes the name. Tuned against a real Groq run
# (12 of 17 misses repaired) and all 670 of Mo's logged sentences, where it
# changed only 5 — each a real fix. 0.75 also turned "RZA", a real artist, into
# Erzaa; below that, everyday phrases start turning into names.
NAME_MATCH_MIN = 0.8
NAME_MIN_LETTERS = 5           # "TRRR" would match "Try"
_SELF = ("I", "I'm", "I'll", "I'd", "I've")


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _correct_names(text: str, vocabulary: "list[str]") -> str:
    """Replace near-misses of vocabulary names in a transcript with the names.

    Only a stretch Whisper itself capitalised is considered — it capitalises
    what it takes for a name, and leaves "at the end of the day" lowercase, so
    that phrase never becomes The Weeknd. A stretch already holding the exact
    name is left alone, and of close candidates the one nearest the name's
    length wins, so "Eby Yusif" becomes Abyusif rather than "Eby Abyusif".
    """
    from difflib import SequenceMatcher

    names = [n for n in vocabulary if len(_squash(n)) >= NAME_MIN_LETTERS]
    tokens = list(re.finditer(r"[A-Za-z0-9']+", text))
    if not names or not tokens:
        return text

    def plain(span) -> str:
        return " ".join(t.group(0) for t in span).lower()

    def named(span) -> bool:
        return any(t is not tokens[0] and t.group(0) not in _SELF and t.group(0)[0].isupper()
                   for t in span)

    found = []                                   # (score, start, end, name)
    for name in names:
        target, words = _squash(name), name.split()
        exact = " ".join(words).lower()
        candidates = []
        for size in sorted({max(1, len(words) - 1), len(words), len(words) + 1}):
            for i in range(len(tokens) - size + 1):
                span = tokens[i:i + size]
                if any(plain(span[a:b]) == exact
                       for a in range(size) for b in range(a + 1, size + 1)):
                    continue                     # the name is already there
                if not named(span):
                    continue
                raw = _squash(text[span[0].start():span[-1].end()])
                matcher = SequenceMatcher(None, raw, target)
                # Cheap upper bounds first: most stretches are nowhere near.
                if matcher.real_quick_ratio() < NAME_MATCH_MIN or matcher.quick_ratio() < NAME_MATCH_MIN:
                    continue
                score = matcher.ratio()
                if score >= NAME_MATCH_MIN:
                    candidates.append((score, abs(len(raw) - len(target)), span, raw))
        if not candidates:
            continue
        top = max(c[0] for c in candidates)
        close = [c for c in candidates if c[0] >= top - 0.05]
        close.sort(key=lambda c: (c[1], -c[0]))  # nearest the name's length
        score, _, span, _ = close[0]
        found.append((score, span[0].start(), span[-1].end(), name))

    found.sort(reverse=True)
    kept = []
    for score, start, end, name in found:
        if all(end <= a or start >= b for _, a, b, _ in kept):
            kept.append((score, start, end, name))
    for _, start, end, name in sorted(kept, key=lambda k: k[1], reverse=True):
        text = text[:start] + name + text[end:]
    return text


def _bias_prompt() -> str:
    """A sample utterance in the style we want back.

    Whisper's `prompt` is not an instruction — it is treated as text preceding
    the audio, and the decode continues its style and vocabulary. So this is
    written as a real sentence Mo might say, carrying the proper nouns Whisper
    otherwise guesses at, and punctuated the way a transcript should read.

    Built from the profile, the contacts, the names in Settings →
    `voice_vocabulary` — the artists, songs and channels Mo asks for, which
    Whisper otherwise spells as English ("Estanna" came back as "stand") — and
    after them the names learned from songs El Fager played and Mo kept, then
    the names from Mo's Spotify Liked Songs.
    Rebuilt when any of those files changes, so an edit applies on the next
    utterance; kept short, because a long prompt crowds out the audio.
    """
    global _BIAS_CACHE
    try:
        from core import voice_learned, voice_liked
        voice_learned.names()                  # may promote a kept song first
        name_stamps = (_mtime(voice_learned._FILE), _mtime(voice_liked._FILE))
    except Exception:
        name_stamps = (0.0, 0.0)
    stamp = (_mtime(_PROFILE), _mtime(_CONTACTS), _mtime(_SETTINGS), *name_stamps)
    if _BIAS_CACHE is not None and _BIAS_CACHE[0] == stamp:
        return _BIAS_CACHE[1]

    names: list[str] = []
    try:
        profile = _read_json(_PROFILE)
        for key in ("name", "full_name"):
            value = (profile.get(key) or "").strip()
            if value and value not in names:
                names.append(value)
    except Exception:
        pass
    try:
        contacts = _read_json(_CONTACTS)
        for person in list(contacts)[:8]:
            person = str(person).strip()
            if person and person.lower() != "test user" and person not in names:
                names.append(person)
    except Exception:
        pass

    who = ", ".join(names[:6]) if names else "Mo"
    prompt = (
        f"Hey El Fager, remind {who} about the review at 4 PM, "
        f"check my Todoist and my Obsidian notes, and tell me what's on my calendar."
    )

    vocabulary = _vocabulary()
    if vocabulary:
        head = prompt[:-1] + ", then play "
        kept = []
        for word in vocabulary:              # the start of the list wins the room
            if len(head) + len(", ".join(kept + [word])) + 1 > BIAS_PROMPT_MAX_CHARS:
                break
            kept.append(word)
        if kept:
            prompt = head + ", ".join(kept) + "."

    _BIAS_CACHE = (stamp, prompt)
    return prompt


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
    text = " ".join(kept).strip()
    if _is_repetition_loop(text):
        print(f"[El Fager] Dropped a looped transcript: {text[:80]!r}")
        return ""
    return text


def _is_repetition_loop(text: str) -> bool:
    """True when most of the words sit inside a phrase repeated LOOP_MIN_REPEATS+
    times. Checked on the joined text: a loop often spans segments."""
    words = re.findall(r"[\w']+", text.lower())
    n = LOOP_PHRASE_WORDS
    phrases = [tuple(words[i:i + n]) for i in range(len(words) - n + 1)]
    counts = Counter(phrases)
    looped = set()
    for i, phrase in enumerate(phrases):
        if counts[phrase] >= LOOP_MIN_REPEATS:
            looped.update(range(i, i + n))
    return bool(words) and len(looped) / len(words) > LOOP_COVERAGE_MAX


def speech_level(chunk: np.ndarray) -> float:
    """How loud one slice of mic audio is, 0..1, on a decibel scale so a
    quiet voice still moves the sphere and a loud one cannot overshoot."""
    if chunk.size == 0:
        return 0.0
    rms = float(np.sqrt(np.mean(np.square(chunk, dtype=np.float64))))
    if rms <= 0.0:
        return 0.0
    db = 20.0 * np.log10(rms)
    return float(min(1.0, max(0.0, (db - LEVEL_FLOOR_DB) / (LEVEL_FULL_DB - LEVEL_FLOOR_DB))))


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

    def record_audio(self, start_timeout_sec: float | None = None,
                     on_level=None) -> "np.ndarray | None":
        """
        Record until the speaker is truly done talking.
        Uses Silero VAD if loaded, otherwise falls back to RMS silence detection.
        start_timeout_sec: give up (return None) if speech hasn't started within
        this many seconds — used by conversation mode's follow-up window.
        on_level: called with speech_level() of every chunk as it arrives, on
        this (the recording) thread.
        """
        self._stop_flag.clear()
        if self._vad_model is not None:
            return self._record_vad(start_timeout_sec, on_level)
        return self._record_rms(start_timeout_sec, on_level)

    def _record_vad(self, start_timeout_sec: float | None = None,
                    on_level=None) -> "np.ndarray | None":
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
                if on_level:
                    on_level(speech_level(chunk))

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

    def _record_rms(self, start_timeout_sec: float | None = None,
                    on_level=None) -> "np.ndarray | None":
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
                if on_level:
                    on_level(speech_level(chunks[-1]))
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
            text = self._transcribe_groq(audio)
        elif self._backend == _BACKEND_FASTER:
            text = self._transcribe_faster(audio)
        else:
            text = self._transcribe_openai(audio)
        if not text:
            return text
        try:
            return _correct_names(text, _vocabulary())   # "Abusif" → Abyusif
        except Exception:
            return text                                   # a correction never costs the words

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
