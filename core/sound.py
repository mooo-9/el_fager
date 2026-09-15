"""
El Fager — the sound cues.

Seven cues, each a distinct timbre so they are recognisable eyes-closed.
Synthesised at runtime exactly as specified in the handoff's sound section
(the recipes mirror "El Fager Sound Cues.dc.html"), so no audio assets ship
with the app and nothing is ever fetched.

Three voices:
  note()  — additive pluck: fundamental + detuned unisons + octave + fifth,
            through a lowpass that opens on the attack and closes on decay
  fm()    — sine carrier with a sine modulator, mod depth decaying → metallic
  noise() — bandpassed noise burst for transients and knocks

Chain: each voice → soft-knee compressor → master 0.9, plus a convolver
reverb send (≈0.9s decaying-noise impulse, wet ≈0.16). Every cue is ≤400ms.

Mix rules, enforced in play():
  * no cue while TTS is speaking — except error, which always cuts through
  * every cue category can be switched off in settings
"""

import json
import math
from pathlib import Path

import numpy as np

SR = 44100
_SETTINGS = Path("data/settings.json")

_cache: dict[str, np.ndarray] = {}
_sounds: dict = {}


# ── voices ──────────────────────────────────────────────────────────────────

def _env(n: int, atk: float, dur: float) -> np.ndarray:
    """ADSR ≈ 8ms attack → decay to 0.55 sustain → exponential release."""
    t = np.arange(n) / SR
    a = max(atk, 1e-4)
    env = np.where(t < a, t / a, 0.55 + 0.45 * np.exp(-(t - a) * 12))
    return env * np.exp(-t / max(dur * 0.55, 1e-3))


def _lowpass_sweep(x: np.ndarray, f_open: float, f_close: float) -> np.ndarray:
    """One-pole lowpass whose cutoff slides from f_open to f_close."""
    n = len(x)
    cutoffs = np.linspace(f_open, f_close, n)
    alpha = 1.0 - np.exp(-2.0 * math.pi * np.clip(cutoffs, 20, SR / 2.2) / SR)
    out = np.empty(n, dtype=np.float64)
    y = 0.0
    for i in range(n):
        y += alpha[i] * (x[i] - y)
        out[i] = y
    return out


def note(freq: float, dur: float = 0.32, peak: float = 0.5,
         bright: float = 1.0, atk: float = 0.008, click: float = 0.0) -> np.ndarray:
    """Additive pluck — the warm, woody voice."""
    n = int(SR * dur)
    t = np.arange(n) / SR
    sig = np.sin(2 * math.pi * freq * t)
    sig += 0.5 * np.sin(2 * math.pi * freq * 1.002 * t)      # detuned unisons
    sig += 0.5 * np.sin(2 * math.pi * freq * 0.997 * t)
    sig += 0.18 * bright * np.sin(2 * math.pi * freq * 2 * t)          # octave
    sig += 0.08 * bright * np.sin(2 * math.pi * freq * 3 * t)   # fifth + octave
    sig /= 2.26
    sig = _lowpass_sweep(sig, freq * 5 * bright, freq * 1.6)
    sig *= _env(n, atk, dur)
    if click > 0:
        burst = int(SR * 0.006)
        sig[:burst] += click * np.random.uniform(-1, 1, burst) * np.linspace(1, 0, burst)
    return sig * peak


def fm(freq: float, dur: float = 0.3, peak: float = 0.5, ratio: float = 2.0,
       index: float = 1.5, atk: float = 0.006, click: float = 0.0) -> np.ndarray:
    """Sine carrier, sine modulator — the glassy, hollow voice."""
    n = int(SR * dur)
    t = np.arange(n) / SR
    depth = freq * index * (0.15 + 0.85 * np.exp(-t / max(dur * 0.4, 1e-3)))
    mod = np.sin(2 * math.pi * freq * ratio * t) * depth
    sig = np.sin(2 * math.pi * freq * t + mod / max(freq, 1e-6) * 6)
    sig *= _env(n, atk, dur)
    if click > 0:
        burst = int(SR * 0.005)
        sig[:burst] += click * np.random.uniform(-1, 1, burst) * np.linspace(1, 0, burst)
    return sig * peak


def noise(dur: float = 0.02, peak: float = 0.15,
          center: float = 1200.0, q: float = 3.0) -> np.ndarray:
    """Bandpassed noise burst — transients and knocks."""
    n = max(int(SR * dur), 8)
    raw = np.random.uniform(-1, 1, n)
    bw = max(center / max(q, 0.5), 30.0)
    low = _lowpass_sweep(raw, center + bw, center + bw)
    band = low - _lowpass_sweep(low, max(center - bw, 20), max(center - bw, 20))
    band *= np.exp(-np.arange(n) / SR / max(dur * 0.4, 1e-4))
    return band * peak


# ── chain ───────────────────────────────────────────────────────────────────

def _mix(*layers: tuple[np.ndarray, float]) -> np.ndarray:
    """Lay voices onto one buffer at their offsets (seconds)."""
    total = max(int(SR * off) + len(buf) for buf, off in layers)
    out = np.zeros(total, dtype=np.float64)
    for buf, off in layers:
        start = int(SR * off)
        out[start:start + len(buf)] += buf
    return out


def _compress(x: np.ndarray, threshold_db: float = -20.0, knee: float = 22.0,
              ratio: float = 3.0, attack: float = 0.003,
              release: float = 0.18) -> np.ndarray:
    """Soft-knee compressor, matching the spec's settings."""
    eps = 1e-9
    level_db = 20 * np.log10(np.abs(x) + eps)
    over = level_db - threshold_db
    # soft knee: ease the gain reduction in over `knee` dB around the threshold
    knee_blend = np.clip((over + knee / 2) / max(knee, eps), 0, 1)
    reduction_db = knee_blend * over * (1 - 1 / ratio)
    reduction_db = np.maximum(reduction_db, 0)

    atk_c = math.exp(-1 / (SR * max(attack, 1e-5)))
    rel_c = math.exp(-1 / (SR * max(release, 1e-5)))
    smoothed = np.empty_like(reduction_db)
    env = 0.0
    for i, target in enumerate(reduction_db):
        coeff = atk_c if target > env else rel_c
        env = coeff * env + (1 - coeff) * target
        smoothed[i] = env
    return x * (10 ** (-smoothed / 20))


def _reverb(x: np.ndarray, wet: float = 0.16, decay: float = 0.9) -> np.ndarray:
    """Convolver send with a decaying-noise impulse (~0.9s)."""
    n = int(SR * decay)
    t = np.linspace(0, 1, n)
    impulse = np.random.uniform(-1, 1, n) * (1 - t) ** 3.2
    tail = np.convolve(x, impulse)[:len(x) + n] / (n ** 0.5)
    out = np.zeros(len(tail))
    out[:len(x)] = x
    return out * (1 - wet) + tail * wet


def _finish(sig: np.ndarray) -> np.ndarray:
    sig = _compress(sig)
    sig = _reverb(sig)
    peak = float(np.max(np.abs(sig))) or 1.0
    return (sig / peak) * 0.9          # master 0.9


# ── the seven cues ──────────────────────────────────────────────────────────

def _summon():   # glassy FM bell rising a fifth
    return _mix((fm(587.33, 0.26, 0.5, 3.5, 2.2), 0.0),
                (fm(880.00, 0.24, 0.42, 3.5, 1.8), 0.08))


def _heard():    # dry mallet tick
    return _mix((noise(0.012, 0.16, 2400, 2.5), 0.0),
                (note(1568, 0.12, 0.10, bright=1.8), 0.0))


def _step():     # hollow woodblock
    return _mix((noise(0.02, 0.14, 800, 4), 0.0),
                (note(392, 0.18, 0.28, bright=0.55), 0.0))


def _resolved():  # warm dark plucked fifth + tail
    return _mix((note(146.83, 0.38, 0.45), 0.0),
                (note(220.00, 0.34, 0.34), 0.01),
                (note(293.66, 0.30, 0.14), 0.02))


def _armed():    # hollow FM, unresolved suspension
    return _mix((fm(523.25, 0.26, 0.42, 2.0, 1.4), 0.0),
                (fm(698.46, 0.26, 0.34, 2.0, 1.4, atk=0.020), 0.06))


def _sent():     # clean 3-note sine arpeggio down
    return _mix((note(880, 0.14, 0.40, bright=0.6), 0.00),
                (note(698, 0.14, 0.38, bright=0.6), 0.07),
                (note(587, 0.20, 0.36, bright=0.6), 0.14))


def _error():    # two low knocks + faint tritone buzz
    return _mix((fm(155.56, 0.20, 0.45, 1.41, 1.2), 0.0),
                (fm(146.83, 0.24, 0.42, 1.41, 1.4), 0.10))


CUES = {
    "summon": _summon,
    "heard": _heard,
    "step": _step,
    "resolved": _resolved,
    "armed": _armed,
    "sent": _sent,
    "error": _error,
}


def render(name: str) -> np.ndarray:
    """The cue as a normalised mono buffer. Built once, then cached."""
    if name not in _cache:
        _cache[name] = _finish(CUES[name]())
    return _cache[name]


# ── playback ────────────────────────────────────────────────────────────────

def enabled(name: str) -> bool:
    """Every cue category is optional in Settings → Voice → Sound cues."""
    try:
        settings = json.loads(_SETTINGS.read_text(encoding="utf-8"))
    except Exception:
        return True
    cues = settings.get("sound_cues", True)
    if isinstance(cues, bool):
        return cues
    if isinstance(cues, dict):
        return bool(cues.get(name, True))
    return True


def _tts_busy() -> bool:
    try:
        import pygame.mixer
        return bool(pygame.mixer.music.get_busy())
    except Exception:
        return False


def play(name: str) -> bool:
    """Play a cue. Returns whether it actually sounded.

    No cue plays over TTS except error — a failure has to cut through.
    """
    if name not in CUES or not enabled(name):
        return False
    if name != "error" and _tts_busy():
        return False
    try:
        import pygame.sndarray
        if name not in _sounds:
            buf = render(name)
            stereo = np.repeat((buf * 32767).astype(np.int16)[:, None], 2, axis=1)
            _sounds[name] = pygame.sndarray.make_sound(np.ascontiguousarray(stereo))
        _sounds[name].play()
        return True
    except Exception:
        return False          # a missing mixer must never break a turn


def wire() -> None:
    """Attach cues to the registries that already report what happened."""
    from core import progress, staging

    def on_staging():
        action = staging.current()
        if action is not None:
            play("armed")
        elif staging.receipts():
            play("sent")

    staging.subscribe(on_staging)

    seen: dict[str, str] = {}

    def on_progress():
        for step in progress.steps():
            key = f"{step.tool}:{step.started_at.isoformat()}"
            if seen.get(key) != step.status:
                if step.status == "done":
                    play("step")
                elif step.status == "failed":
                    play("error")
                seen[key] = step.status

    progress.subscribe(on_progress)
