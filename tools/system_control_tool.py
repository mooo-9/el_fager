"""
Windows system controls — Phase 6H.
  - System volume:  pycaw (pip install pycaw)
  - Screen brightness: WMI via PowerShell subprocess (no extra package)
  - Battery status: psutil
"""

import subprocess
import sys


# ── Volume ────────────────────────────────────────────────────────────────────

def _get_endpoint_volume():
    """Return the pycaw EndpointVolume interface for the default speakers."""
    from pycaw.pycaw import AudioUtilities
    return AudioUtilities.GetSpeakers().EndpointVolume


def set_system_volume(level: int) -> str:
    """Set Windows master volume. level = 0–100."""
    level = max(0, min(100, int(level)))
    try:
        _get_endpoint_volume().SetMasterVolumeLevelScalar(level / 100.0, None)
        return f"Volume set to {level}%"
    except ImportError:
        return "[pycaw not installed — run: pip install pycaw]"
    except Exception as e:
        return f"[Volume error: {e}]"


def get_system_volume() -> str:
    """Return current Windows master volume level."""
    try:
        vol = _get_endpoint_volume()
        level = int(vol.GetMasterVolumeLevelScalar() * 100)
        muted = vol.GetMute()
        return f"System volume: {'muted' if muted else f'{level}%'}"
    except ImportError:
        return "[pycaw not installed — run: pip install pycaw]"
    except Exception as e:
        return f"[Volume error: {e}]"


def mute_system() -> str:
    """Toggle system mute."""
    try:
        vol = _get_endpoint_volume()
        current = vol.GetMute()
        vol.SetMute(not current, None)
        return "Muted" if not current else "Unmuted"
    except ImportError:
        return "[pycaw not installed — run: pip install pycaw]"
    except Exception as e:
        return f"[Mute error: {e}]"


# ── Brightness ────────────────────────────────────────────────────────────────

def set_brightness(level: int) -> str:
    """Set screen brightness via WMI (works for most laptop screens). level = 0–100."""
    level = max(0, min(100, int(level)))
    try:
        result = subprocess.run(
            [
                "powershell", "-NonInteractive", "-Command",
                f"(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods)"
                f".WmiSetBrightness(1,{level})"
            ],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return f"Brightness set to {level}%"
        return f"[Brightness error: {result.stderr.strip() or 'WMI call failed'}]"
    except Exception as e:
        return f"[Brightness error: {e}]"


def get_brightness() -> str:
    """Return current screen brightness level."""
    try:
        result = subprocess.run(
            [
                "powershell", "-NonInteractive", "-Command",
                "(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightness).CurrentBrightness"
            ],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            val = result.stdout.strip()
            return f"Screen brightness: {val}%"
        return f"[Brightness error: {result.stderr.strip()}]"
    except Exception as e:
        return f"[Brightness error: {e}]"


# ── Battery ───────────────────────────────────────────────────────────────────

def get_battery_status() -> str:
    """Return current battery percentage, charging status, and estimated time remaining."""
    try:
        import psutil
        b = psutil.sensors_battery()
        if b is None:
            return "No battery detected (desktop PC or unsupported)."
        pct = b.percent
        plugged = b.power_plugged
        secs = b.secsleft

        status = "charging" if plugged else "on battery"
        msg = f"Battery: {pct:.0f}% ({status})"

        if not plugged and secs > 0 and secs != psutil.POWER_TIME_UNLIMITED:
            h, m = divmod(secs // 60, 60)
            msg += f" — ~{h}h {m}m remaining"
        elif plugged and pct < 100:
            msg += " — charging"
        elif pct >= 100:
            msg = f"Battery: full (100%, plugged in)"

        return msg
    except ImportError:
        return "[psutil not installed — run: pip install psutil]"
    except Exception as e:
        return f"[Battery error: {e}]"
