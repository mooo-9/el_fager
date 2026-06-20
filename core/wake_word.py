"""
Wake word listener for El Fager.

Runs as a daemon thread — listens to the mic 24/7 at low CPU (<3%).
When the configured wake word is detected, fires on_detected() callback.

Uses openwakeword with onnxruntime backend (CPU-safe, no CUDA/GPU needed).
Uses sounddevice for audio capture (already installed, no pyaudio needed).

Thread safety: on_detected must be a Qt signal emit so Qt can queue the
delivery to the main thread. Never call Qt widget methods directly from here.

AUDIO FORMAT: openwakeword's mel-spectrogram model requires int16 PCM audio
(range -32768..32767). sounddevice gives float32 in [-1, 1]. We convert
before every predict() call — skipping this causes the buffer to become all
zeros and the model never scores above threshold.
"""

import os
import queue
import threading
import time

import numpy as np


CHUNK = 1280       # 80 ms at 16 kHz — openwakeword's required frame size
RATE = 16000
COOLDOWN = 2.0     # seconds between detections to prevent double-firing


class WakeWordListener:
    """
    Listens for a wake word in the background and fires on_detected() when heard.

    on_detected — zero-argument callable; must be thread-safe (e.g. a Qt signal emit).
    """

    def __init__(self, on_detected: callable):
        self._on_detected = on_detected
        self._running = False
        self._paused = False
        self._thread: threading.Thread | None = None
        self.available = False

        enabled = os.getenv("WAKE_WORD_ENABLED", "true").lower() not in ("false", "0", "no")
        if not enabled:
            print("[El Fager] Wake word disabled (WAKE_WORD_ENABLED=false).")
            return

        model_str = os.getenv("WAKE_WORD_MODEL", "hey_jarvis")
        model_list = [m.strip() for m in model_str.split(",") if m.strip()]

        try:
            self._threshold = float(os.getenv("WAKE_WORD_THRESHOLD", "0.5"))
        except ValueError:
            self._threshold = 0.5

        try:
            import openwakeword as _oww_pkg
            from openwakeword.model import Model

            # Download built-in models that aren't on disk yet
            try:
                for mp in model_list:
                    if not os.path.isfile(mp) and mp in _oww_pkg.MODELS:
                        _oww_pkg.utils.download_models([mp])
            except Exception as e:
                print(f"[El Fager] Wake word model download warning (non-fatal): {e}")

            self._oww = Model(
                wakeword_models=model_list,
                inference_framework="onnx",
            )
            self.available = True
            # model_list may be mutated in-place by openwakeword (resolves short names to paths)
            labels = os.getenv("WAKE_WORD_MODEL", "hey_jarvis")
            print(f"[El Fager] Wake word ready — models: {labels}, threshold: {self._threshold}")
        except Exception as e:
            print(f"[El Fager] Wake word unavailable (non-fatal): {e}")
            self.available = False

    # ------------------------------------------------------------------ #
    #  Public control                                                      #
    # ------------------------------------------------------------------ #

    def start(self):
        if not self.available or self._running:
            return
        self._running = True
        self._paused = False
        self._thread = threading.Thread(target=self._listen_loop, daemon=True, name="WakeWordListener")
        self._thread.start()
        print("[El Fager] Wake word listener started.")

    def stop(self):
        self._running = False

    def pause(self):
        """Pause mic reading — call when PipelineWorker starts to avoid mic conflicts."""
        self._paused = True

    def resume(self):
        """Resume mic reading — call when PipelineWorker finishes."""
        self._paused = False

    def is_active(self) -> bool:
        return self._running and not self._paused

    # ------------------------------------------------------------------ #
    #  Listener loop (daemon thread)                                       #
    # ------------------------------------------------------------------ #

    def _listen_loop(self):
        import sounddevice as sd

        last_detection = 0.0

        while self._running:
            if self._paused:
                time.sleep(0.05)
                continue

            audio_queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=20)

            def _callback(indata: np.ndarray, frames: int, time_info, status):
                if not self._paused:
                    try:
                        audio_queue.put_nowait(indata.copy().flatten())
                    except queue.Full:
                        pass  # drop chunk rather than block

            try:
                with sd.InputStream(
                    samplerate=RATE,
                    channels=1,
                    dtype="float32",
                    blocksize=CHUNK,
                    callback=_callback,
                ):
                    while self._running and not self._paused:
                        try:
                            chunk = audio_queue.get(timeout=0.05)
                        except queue.Empty:
                            continue

                        # openwakeword's mel-spectrogram model requires int16 PCM.
                        # sounddevice gives float32 in [-1, 1]. Without this conversion
                        # the buffer becomes near-zero int16 and the model sees silence.
                        chunk_i16 = (chunk * 32767).astype(np.int16)

                        try:
                            prediction = self._oww.predict(chunk_i16)
                        except Exception:
                            continue

                        for model_name, score in prediction.items():
                            if score >= self._threshold:
                                now = time.time()
                                if now - last_detection > COOLDOWN:
                                    last_detection = now
                                    try:
                                        self._oww.reset()
                                    except Exception:
                                        pass
                                    print(f"[El Fager] Wake word detected! ({model_name}: {score:.3f})")
                                    try:
                                        self._on_detected()
                                    except Exception as e:
                                        print(f"[El Fager] Wake word callback error: {e}")
                                break

            except Exception as e:
                if self._running:
                    print(f"[El Fager] Wake word stream error (will retry): {e}")
                    time.sleep(2)
