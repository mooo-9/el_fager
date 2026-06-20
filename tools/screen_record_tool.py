"""
Screen recording for El Fager.

Records screen as MP4 in a background thread using mss (capture) + opencv (encoding).
opencv-python-headless avoids Qt conflicts with the El Fager window.
"""

import os
import threading
import time
from datetime import datetime

_recording = False
_thread: threading.Thread = None
_output_path: str = None
_start_time: float = None
_frame_count: int = 0


def start_recording(output_path: str = None, fps: int = 15) -> str:
    """Start recording the screen to an MP4 file. Runs in background."""
    global _recording, _thread, _output_path, _start_time, _frame_count

    if _recording:
        elapsed = time.time() - _start_time
        return f"Already recording to {_output_path} (elapsed: {elapsed:.0f}s). Call stop_recording first."

    try:
        import cv2
        import mss
        import numpy as np
    except ImportError as e:
        return f"[start_recording failed: missing dependency — {e}]"

    if output_path is None:
        os.makedirs("data/recordings", exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = f"data/recordings/recording_{ts}.mp4"
    else:
        parent = os.path.dirname(output_path)
        if parent:
            os.makedirs(parent, exist_ok=True)

    _output_path = output_path
    _recording = True
    _start_time = time.time()
    _frame_count = 0

    def _record_loop():
        global _recording, _frame_count
        try:
            with mss.mss() as sct:
                monitor = sct.monitors[1]
                width = monitor["width"]
                height = monitor["height"]

                fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                writer = cv2.VideoWriter(output_path, fourcc, fps, (width, height))

                if not writer.isOpened():
                    _recording = False
                    return

                frame_interval = 1.0 / fps
                next_frame_time = time.time()

                while _recording:
                    now = time.time()
                    if now >= next_frame_time:
                        shot = sct.grab(monitor)
                        frame = np.array(shot)
                        frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
                        writer.write(frame)
                        _frame_count += 1
                        next_frame_time += frame_interval
                    else:
                        time.sleep(0.005)

                writer.release()
        except Exception:
            pass
        finally:
            _recording = False

    _thread = threading.Thread(target=_record_loop, daemon=True)
    _thread.start()
    return f"Recording started -> {output_path} ({fps} fps). Call stop_recording when done."


def stop_recording() -> str:
    """Stop recording, finalize the MP4, and return the file path."""
    global _recording, _thread, _output_path, _start_time

    if not _recording and _thread is None:
        return "No recording in progress."

    _recording = False
    if _thread and _thread.is_alive():
        _thread.join(timeout=5)

    path = _output_path
    elapsed = time.time() - _start_time if _start_time else 0
    _thread = None
    _start_time = None

    if path and os.path.exists(path):
        size_mb = os.path.getsize(path) / (1024 * 1024)
        return (
            f"Recording saved: {path}\n"
            f"Duration: {elapsed:.0f}s, Size: {size_mb:.1f} MB, Frames: {_frame_count}"
        )
    return f"Recording stopped. File: {path}"


def recording_status() -> str:
    """Check whether screen recording is currently active."""
    if _recording and _start_time:
        elapsed = time.time() - _start_time
        mins = int(elapsed // 60)
        secs = int(elapsed % 60)
        return (
            f"Recording: ACTIVE\n"
            f"Output: {_output_path}\n"
            f"Elapsed: {mins}m {secs}s\n"
            f"Frames captured: {_frame_count}"
        )
    return "Recording: not active."


def take_snapshot(output_path: str = None) -> str:
    """Save a single screenshot as PNG."""
    try:
        import mss
        from PIL import Image

        if output_path is None:
            os.makedirs("data/recordings", exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = f"data/recordings/snapshot_{ts}.png"
        else:
            parent = os.path.dirname(output_path)
            if parent:
                os.makedirs(parent, exist_ok=True)

        with mss.mss() as sct:
            monitor = sct.monitors[1]
            shot = sct.grab(monitor)
            img = Image.frombytes("RGB", shot.size, shot.rgb)
            img.save(output_path)

        size_kb = os.path.getsize(output_path) // 1024
        return f"Snapshot saved: {output_path} ({size_kb} KB)."
    except Exception as e:
        return f"[take_snapshot failed: {e}]"
