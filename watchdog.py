"""
El Fager watchdog — keeps main.py alive.

Run at logon via Windows Task Scheduler (see README section or:
  schtasks /Create /SC ONLOGON /TN "El Fager Watchdog" /TR "<pythonw> <this file>"
).

Behaviour:
  - Launches `pythonw main.py` with stderr captured to data/logs/.
  - Polls the process; on a crash, logs it and restarts.
  - Exit 0 means Mo quit from the tray menu: the watchdog stops too, so
    Quit actually quits. It comes back at the next logon.
  - Exit 3 means the single-instance mutex is held by another El Fager;
    the watchdog keeps polling without spawning duplicates.
  - After 3 crashes within 10 minutes it stops restarting and shows a
    Windows toast so Mo knows something is structurally broken.

cp1252 note: keep all strings ASCII-safe (no arrows/emoji) — they end up
in console handles and toast notifications.
"""
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_LOG_DIR = _ROOT / "data" / "logs"

POLL_SECONDS = 5
ALREADY_RUNNING_EXIT = 3    # main.py's exit code when the mutex is already held
MAX_CRASHES = 3
CRASH_WINDOW_SECONDS = 600  # 10 minutes


def classify_exit(code: int) -> str:
    """Why El Fager stopped: 'already_running', 'quit', or 'crash'."""
    if code == ALREADY_RUNNING_EXIT:
        return "already_running"
    return "quit" if code == 0 else "crash"


class RestartTracker:
    """Sliding-window crash counter: give up after too many rapid crashes."""

    def __init__(self, max_crashes: int = MAX_CRASHES,
                 window_seconds: float = CRASH_WINDOW_SECONDS):
        self.max_crashes = max_crashes
        self.window_seconds = window_seconds
        self._crashes: list[float] = []

    def record_crash(self, now: float | None = None) -> None:
        self._crashes.append(time.time() if now is None else now)

    def should_give_up(self, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        self._crashes = [t for t in self._crashes
                         if now - t <= self.window_seconds]
        return len(self._crashes) >= self.max_crashes


def _log(msg: str) -> None:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().isoformat(timespec="seconds")
    line = f"[{stamp}] {msg}\n"
    with open(_LOG_DIR / "watchdog.log", "a", encoding="utf-8") as f:
        f.write(line)


def _toast(msg: str) -> None:
    try:
        from winotify import Notification
        Notification(
            app_id="El Fager Watchdog",
            title="El Fager Watchdog",
            msg=msg[:256],
            duration="long",
        ).show()
    except Exception:
        pass


def _spawn():
    """Start pythonw main.py with stderr captured to a timestamped log."""
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    stderr_path = _LOG_DIR / f"elfager-stderr-{stamp}.log"
    stderr_file = open(stderr_path, "w", encoding="utf-8")
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    exe = str(pythonw) if pythonw.exists() else sys.executable
    proc = subprocess.Popen(
        [exe, str(_ROOT / "main.py")],
        cwd=str(_ROOT),
        stderr=stderr_file,
        stdout=subprocess.DEVNULL,
    )
    return proc, stderr_file, stderr_path


def _acquire_watchdog_mutex() -> bool:
    """Single watchdog instance only. Returns False if one already runs."""
    try:
        import ctypes
        ctypes.windll.kernel32.CreateMutexW(None, True, "ElFagerWatchdogSingleInstance")
        return ctypes.windll.kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS
    except Exception:
        return True


def main() -> None:
    if not _acquire_watchdog_mutex():
        return

    tracker = RestartTracker()
    _log("Watchdog started.")

    while True:
        proc, stderr_file, stderr_path = _spawn()
        started = time.time()
        _log(f"Launched El Fager (pid {proc.pid}).")

        while proc.poll() is None:
            time.sleep(POLL_SECONDS)

        uptime = time.time() - started
        code = proc.returncode
        stderr_file.close()
        if stderr_path.exists() and stderr_path.stat().st_size == 0:
            stderr_path.unlink()  # no stderr output -> no point keeping the file

        reason = classify_exit(code)

        if reason == "already_running":
            # Single-instance mutex: another El Fager is already running.
            # Poll passively until it disappears, then take over.
            _log("El Fager already running elsewhere; watching passively.")
            time.sleep(60)
            continue

        if reason == "quit":
            # Mo chose Quit from the tray menu - do not resurrect it.
            _log(f"El Fager quit by user after {uptime:.0f}s. Watchdog stopping.")
            return

        _log(f"El Fager CRASHED (exit {code}) after {uptime:.0f}s. "
             f"Stderr: {stderr_path.name}")
        tracker.record_crash()

        if tracker.should_give_up():
            msg = (f"El Fager crashed {MAX_CRASHES} times in 10 minutes. "
                   f"Watchdog stopped. Check data/logs/.")
            _log(msg)
            _toast(msg)
            return

        time.sleep(3)  # brief pause before restart


if __name__ == "__main__":
    main()
