"""
Pomodoro / focus timer — Phase 5C.
Uses threading.Timer (stdlib) + winotify (already installed) for Windows toasts.
No new packages required.
"""

import threading
import time

# label → threading.Timer
_timers: dict[str, threading.Timer] = {}
# label → (start_ts, duration_seconds)
_meta: dict[str, tuple[float, int]] = {}


def start_pomodoro(minutes: int = 25, label: str = "Focus session") -> str:
    """
    Start a countdown timer. Shows a Windows toast notification when done.
    minutes — duration (default 25)
    label   — name for this session (used in the notification and for cancelling)
    """
    seconds = minutes * 60

    def _done():
        _timers.pop(label, None)
        _meta.pop(label, None)
        try:
            from winotify import Notification, audio
            toast = Notification(
                app_id="El Fager",
                title="⏰ Pomodoro Complete!",
                msg=f"{label} ({minutes} min) is done — take a break!",
                duration="long",
            )
            toast.set_audio(audio.Default, loop=False)
            toast.show()
        except Exception as e:
            print(f"[El Fager] Pomodoro toast error: {e}")

    # Cancel any existing timer with the same label
    if label in _timers:
        _timers[label].cancel()

    t = threading.Timer(seconds, _done)
    t.daemon = True
    _timers[label] = t
    _meta[label] = (time.time(), seconds)
    t.start()

    end_str = time.strftime("%H:%M", time.localtime(time.time() + seconds))
    return (
        f"Started {minutes}-minute Pomodoro: '{label}'.\n"
        f"I'll send a notification at {end_str} when it's done. Stay focused!"
    )


def stop_pomodoro(label: str = None) -> str:
    """
    Cancel a running Pomodoro timer.
    label — which timer to cancel; cancels all if omitted.
    """
    if not _timers:
        return "No active Pomodoro timers."

    if label:
        if label in _timers:
            _timers[label].cancel()
            del _timers[label]
            _meta.pop(label, None)
            return f"Cancelled Pomodoro: '{label}'."
        return f"No timer named '{label}'. Active: {', '.join(_timers.keys())}"

    names = list(_timers.keys())
    for t in _timers.values():
        t.cancel()
    _timers.clear()
    _meta.clear()
    return f"Cancelled {len(names)} timer(s): {', '.join(names)}."


def list_pomodoros() -> str:
    """List all active Pomodoro timers with time remaining."""
    if not _timers:
        return "No active Pomodoro timers."

    lines = ["Active Pomodoro timers:\n"]
    now = time.time()
    for label, (start, duration) in _meta.items():
        remaining = max(0, int(duration - (now - start)))
        m, s = divmod(remaining, 60)
        lines.append(f"  • {label}: {m}m {s}s remaining")
    return "\n".join(lines)
