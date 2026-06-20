"""
Distraction blocker (Focus Mode) — Phase 6F.
Temporarily adds entries to the Windows hosts file to block distracting sites.
Requires El Fager to be running as Administrator.

WARNING: Modifies C:\\Windows\\System32\\drivers\\etc\\hosts.
A backup is saved to data/hosts_backup.txt before any change.
"""

import ctypes
import os
import shutil
import threading
from datetime import datetime
from pathlib import Path

HOSTS_PATH = Path(r"C:\Windows\System32\drivers\etc\hosts")
BACKUP_PATH = Path("data/hosts_backup.txt")
MARKER_START = "# === El Fager Focus Mode START ==="
MARKER_END   = "# === El Fager Focus Mode END ==="

DEFAULT_BLOCKED = [
    "youtube.com", "www.youtube.com",
    "facebook.com", "www.facebook.com",
    "instagram.com", "www.instagram.com",
    "twitter.com", "www.twitter.com",
    "x.com", "www.x.com",
    "tiktok.com", "www.tiktok.com",
    "reddit.com", "www.reddit.com",
    "9gag.com", "www.9gag.com",
    "snapchat.com", "www.snapchat.com",
]

_restore_timer: threading.Timer | None = None


def _is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _block_entries(sites: list[str]) -> str:
    return (
        f"\n{MARKER_START}\n"
        + "\n".join(f"127.0.0.1  {s}" for s in sites)
        + f"\n{MARKER_END}\n"
    )


def _remove_block():
    """Remove the focus-mode block from the hosts file."""
    try:
        content = HOSTS_PATH.read_text(encoding="utf-8")
        start = content.find(MARKER_START)
        end   = content.find(MARKER_END)
        if start != -1 and end != -1:
            cleaned = content[:start] + content[end + len(MARKER_END):].lstrip("\n")
            HOSTS_PATH.write_text(cleaned, encoding="utf-8")
    except Exception as e:
        print(f"[El Fager] Focus mode restore error: {e}")


def enable_focus_mode(hours: float = 2.0, sites: list = None) -> str:
    """
    Block distracting websites for a set number of hours.
    Requires El Fager to be running as Administrator.
    """
    global _restore_timer

    if not _is_admin():
        return (
            "Focus mode requires Administrator rights.\n"
            "Right-click El Fager shortcut → 'Run as administrator', then try again."
        )

    blocked = sites if sites else DEFAULT_BLOCKED

    # Check if already active
    try:
        content = HOSTS_PATH.read_text(encoding="utf-8")
        if MARKER_START in content:
            return "Focus mode is already active. Use disable_focus_mode to end it early."
    except Exception:
        pass

    # Backup
    BACKUP_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(HOSTS_PATH, BACKUP_PATH)
    except Exception as e:
        return f"Could not back up hosts file: {e}"

    # Write blocks
    try:
        with open(HOSTS_PATH, "a", encoding="utf-8") as f:
            f.write(_block_entries(blocked))
    except PermissionError:
        return "Permission denied writing hosts file — run El Fager as Administrator."
    except Exception as e:
        return f"[Focus mode error: {e}]"

    # Schedule automatic restoration
    if _restore_timer:
        _restore_timer.cancel()

    def _auto_restore():
        _remove_block()
        try:
            from winotify import Notification
            Notification(
                app_id="El Fager",
                title="Focus Mode ended",
                msg=f"Sites unblocked after {hours}h. Great work!",
                duration="long",
            ).show()
        except Exception:
            pass

    _restore_timer = threading.Timer(hours * 3600, _auto_restore)
    _restore_timer.daemon = True
    _restore_timer.start()

    end_time = datetime.now().strftime("%H:%M")
    from datetime import timedelta
    end_dt = datetime.now() + timedelta(hours=hours)
    end_str = end_dt.strftime("%H:%M")

    return (
        f"Focus mode ON for {hours}h (until {end_str}).\n"
        f"Blocked {len(blocked)} sites: YouTube, Facebook, Instagram, TikTok, Reddit, and more.\n"
        f"Use disable_focus_mode to end early."
    )


def disable_focus_mode() -> str:
    """Immediately unblock all sites and cancel the restore timer."""
    global _restore_timer

    if not _is_admin():
        return "Requires Administrator rights to modify the hosts file."

    if _restore_timer:
        _restore_timer.cancel()
        _restore_timer = None

    try:
        content = HOSTS_PATH.read_text(encoding="utf-8")
        if MARKER_START not in content:
            return "Focus mode is not currently active."
    except Exception as e:
        return f"[Focus mode error: {e}]"

    _remove_block()
    return "Focus mode OFF — all sites unblocked."
