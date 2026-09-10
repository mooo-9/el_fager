"""
El Fager watchdog — keeps main.py alive.

Run at logon via Windows Task Scheduler (see README section or:
  schtasks /Create /SC ONLOGON /TN "El Fager Watchdog" /TR "<pythonw> <this file>"
).

Behaviour:
  - Launches `pythonw main.py` with stderr captured to data/logs/.
  - Polls the process; on exit, logs the crash and restarts it.
  - If the app exits cleanly within the first seconds (single-instance
    mutex says another El Fager is already running), the watchdog just
    keeps polling without spawning duplicates.
  - After 3 crashes within 10 minutes it stops restarting and shows a
    Windows toast so Mo knows something is structurally broken.
  - Every 15 minutes it deploys whatever CI has verified: the workflow moves
    the `verified` branch only when the suite passes on master, so anything
    reachable there has been tested. Nothing else is ever pulled.

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
CLEAN_EXIT_GRACE = 15       # exit 0 within this many seconds = "already running"
MAX_CRASHES = 3
CRASH_WINDOW_SECONDS = 600  # 10 minutes
DEPLOY_BRANCH = "verified"  # CI moves this, and only when the suite is green
UPDATE_CHECK_SECONDS = 900  # 15 minutes
STOP_GRACE_SECONDS = 10     # wait this long for a clean exit before killing

# pythonw has no console, so a bare subprocess would flash one up per git call.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


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


def _git(*args: str) -> tuple[bool, str]:
    """Run a git command in the project. Returns (succeeded, combined output)."""
    try:
        r = subprocess.run(
            ["git", *args], cwd=str(_ROOT), capture_output=True, text=True,
            timeout=120, creationflags=_NO_WINDOW,
        )
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except Exception as e:
        return False, str(e)


def _deployable_commit() -> str | None:
    """Return the commit CI has verified, when it is not the one running.

    The deploy branch is moved by the workflow and only after the suite
    passes, so reaching a commit here is what "tested" means. Any failure to
    reach GitHub returns None: no network, no deploy.
    """
    ok, _ = _git("fetch", "origin", DEPLOY_BRANCH)
    if not ok:
        return None
    ok, verified = _git("rev-parse", f"origin/{DEPLOY_BRANCH}")
    if not ok:
        return None
    ok, head = _git("rev-parse", "HEAD")
    if not ok or verified == head:
        return None
    return verified


def _sync_dependencies(old_sha: str, new_sha: str) -> None:
    """Reinstall only when the new commit actually changed requirements.txt."""
    ok, changed = _git("diff", "--name-only", old_sha, new_sha, "--", "requirements.txt")
    if not ok or not changed:
        return
    _log("requirements.txt changed; reinstalling dependencies.")
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", str(_ROOT / "requirements.txt")],
            cwd=str(_ROOT), capture_output=True, text=True, timeout=1800,
            creationflags=_NO_WINDOW,
        )
    except Exception as e:
        _log(f"Dependency install failed: {e}")


def _deploy(sha: str) -> bool:
    """Fast-forward the working copy onto a verified commit."""
    ok, dirty = _git("status", "--porcelain")
    if not ok:
        return False
    if dirty:
        # Mo is editing. His uncommitted work outranks an automatic update.
        _log("Update available but the working tree is dirty; leaving it alone.")
        return False

    ok, head = _git("rev-parse", "HEAD")
    if not ok:
        return False

    ok, out = _git("merge", "--ff-only", sha)
    if not ok:
        _log(f"Cannot fast-forward onto {sha[:8]}: {out}")
        return False

    _sync_dependencies(head, sha)
    _log(f"Deployed {sha[:8]}.")
    return True


def _deploy_if_verified() -> bool:
    sha = _deployable_commit()
    return bool(sha) and _deploy(sha)


def _stop(proc) -> None:
    """Ask El Fager to exit, then insist."""
    try:
        proc.terminate()
        proc.wait(timeout=STOP_GRACE_SECONDS)
    except Exception:
        try:
            proc.kill()
            proc.wait(timeout=STOP_GRACE_SECONDS)
        except Exception:
            pass


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
    _deploy_if_verified()  # pick up whatever landed while Mo was logged off

    while True:
        proc, stderr_file, stderr_path = _spawn()
        started = time.time()
        _log(f"Launched El Fager (pid {proc.pid}).")

        deployed = False
        next_check = time.time() + UPDATE_CHECK_SECONDS
        while proc.poll() is None:
            time.sleep(POLL_SECONDS)
            if time.time() >= next_check:
                next_check = time.time() + UPDATE_CHECK_SECONDS
                if _deploy_if_verified():
                    _log("Restarting El Fager on the new code.")
                    deployed = True
                    _stop(proc)

        uptime = time.time() - started
        code = proc.returncode
        stderr_file.close()
        if stderr_path.exists() and stderr_path.stat().st_size == 0:
            stderr_path.unlink()  # no stderr output -> no point keeping the file

        if deployed:
            # We stopped it on purpose. Not a crash, and no backoff.
            continue

        if code == 0 and uptime < CLEAN_EXIT_GRACE:
            # Single-instance mutex: another El Fager is already running.
            # Poll passively until it disappears, then take over.
            _log("El Fager already running elsewhere; watching passively.")
            time.sleep(60)
            continue

        if code == 0:
            _log(f"El Fager exited cleanly after {uptime:.0f}s. Restarting.")
        else:
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
