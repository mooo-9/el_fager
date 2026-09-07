"""
El Fager — barge-in.

Talking over the assistant has to interrupt it. An assistant you cannot cut
off is a voice form, not a voice interface: you sit through a wrong answer to
the end before you can correct it.

The hard part is not detecting speech — it is telling *whose* speech it is.
The speaker bleeds into the microphone, the assistant's own voice is speech,
and no VAD can separate the two. So this does not ask "is that speech". It
measures the room during the first moments of playback, when the only thing
audible is the assistant, and trips only on energy well clear of that floor:

  * on headphones the floor is near silence, so it is very sensitive
  * on speakers the floor is the bleed itself, so it takes a raised voice —
    which is the right trade, because the alternative is the assistant
    interrupting itself mid-sentence

Deliberately RMS-only and Qt-free: it runs on the playback thread's clock,
must add no latency to speaking, and the neural VAD is busy being loaded for
the recogniser.
"""

import os
import threading

import numpy as np

SAMPLE_RATE = 16000
_CHUNK = 1600                 # 100 ms at 16 kHz

_CALIBRATE_SEC = 0.6          # measure the bleed before arming
_TRIP_RATIO = 2.2             # how far above the floor counts as you
_TRIP_SEC = 0.3               # sustained, so a cough or a keyboard doesn't
_ABS_FLOOR = 0.012            # never arm below this: silence must stay silent


class BargeInMonitor:
    """Open while the assistant speaks. `tripped` is set when you talk over it.

    Usage is a context manager so the stream can never outlive the utterance:

        with BargeInMonitor() as monitor:
            voice_out.speak_stream(chunks, should_stop=monitor.tripped.is_set)
        if monitor.tripped.is_set():
            ...
    """

    def __init__(self, ratio: float = _TRIP_RATIO, trip_sec: float = _TRIP_SEC,
                 calibrate_sec: float = _CALIBRATE_SEC):
        self.tripped = threading.Event()
        self._ratio = ratio
        self._trip_frames = max(1, int(trip_sec * SAMPLE_RATE / _CHUNK))
        self._calibrate_frames = max(1, int(calibrate_sec * SAMPLE_RATE / _CHUNK))
        self._stream = None
        self._levels: list[float] = []
        self._floor: "float | None" = None
        self._loud_run = 0
        self.peak = 0.0            # kept for diagnosis, not for decisions

    # ── The decision, separated from the audio device so it can be tested ──

    def feed(self, level: float) -> None:
        """One frame's RMS. Calibrates first, then watches for you."""
        if self.tripped.is_set():
            return
        self.peak = max(self.peak, level)
        if self._floor is None:
            self._levels.append(level)
            if len(self._levels) >= self._calibrate_frames:
                # The loudest the assistant got while we listened, floored so
                # a silent room can't arm a hair trigger.
                self._floor = max(max(self._levels), _ABS_FLOOR)
            return
        if level > self._floor * self._ratio:
            self._loud_run += 1
            if self._loud_run >= self._trip_frames:
                self.tripped.set()
        else:
            self._loud_run = 0

    # ── The device ─────────────────────────────────────────────────────────

    def start(self) -> "BargeInMonitor":
        # Imported here, not at module scope: opening PortAudio is a real
        # side effect, and feed() — the part worth testing — needs no device.
        import sounddevice as sd

        def _cb(indata, frames, time_info, status):
            try:
                self.feed(float(np.sqrt(np.mean(np.square(indata[:, 0])))))
            except Exception:
                pass          # a bad frame must never break playback

        try:
            self._stream = sd.InputStream(
                samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                blocksize=_CHUNK, callback=_cb,
            )
            self._stream.start()
        except Exception as e:
            # No mic, or it is busy. Speaking must continue regardless — the
            # cost is only that this utterance cannot be interrupted.
            print(f"[El Fager] barge-in unavailable: {e}")
            self._stream = None
        return self

    def stop(self) -> None:
        stream, self._stream = self._stream, None
        if stream is None:
            return
        try:
            stream.stop()
            stream.close()
        except Exception:
            pass

    def __enter__(self) -> "BargeInMonitor":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()


def enabled() -> bool:
    """Settings → Voice → Barge-in. On by default, per the design."""
    import json
    from pathlib import Path

    # The suite runs headless and must never open the microphone; PortAudio
    # takes the whole process down with it when there is no device.
    if os.getenv("EL_FAGER_TEST_MODE"):
        return False
    try:
        settings = json.loads(
            Path("data/settings.json").read_text(encoding="utf-8"))
    except Exception:
        return True
    return bool(settings.get("barge_in", True))
