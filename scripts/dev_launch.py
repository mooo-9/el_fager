"""Launch El Fager headless on Linux, for inspection in a container.

Stubs only the Windows-specific surfaces — winreg, pystray, keyboard and
ctypes.windll — so the rest (Qt, the brain, the scheduler, the HUD, the
dashboard) runs for real. Not a test double for Windows behaviour: it is a
way to watch startup and shutdown actually happen somewhere they otherwise
cannot.

    xvfb-run -a python scripts/dev_launch.py [seconds]

Exits with the app's own code, so an abnormal shutdown is visible as one.
"""
import os, sys, types, ctypes, threading, traceback, faulthandler
from pathlib import Path

ROOT = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, ROOT)
os.chdir(ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-harness-not-a-real-key")

FINDINGS = []

# ── winreg: Windows registry ────────────────────────────────────────────────
winreg = types.ModuleType("winreg")
for _h in ("HKEY_CURRENT_USER", "HKEY_LOCAL_MACHINE", "HKEY_CLASSES_ROOT",
           "HKEY_USERS", "HKEY_CURRENT_CONFIG"):
    setattr(winreg, _h, 0)
winreg.KEY_SET_VALUE = winreg.KEY_ALL_ACCESS = winreg.KEY_READ = 0
for name in ("OpenKey", "SetValueEx", "CloseKey", "DeleteValue", "QueryValueEx"):
    setattr(winreg, name, lambda *a, **k: (_ for _ in ()).throw(OSError("stubbed winreg")))
sys.modules["winreg"] = winreg

# ── pystray: system tray ────────────────────────────────────────────────────
pystray = types.ModuleType("pystray")
class _Icon:
    def __init__(self, *a, **k): self.visible = False
    def run(self):
        FINDINGS.append("tray: Icon.run() reached (would block on Win32 loop)")
        threading.Event().wait()      # mimic the blocking message loop
    def stop(self): pass
class _MenuItem:
    def __init__(self, *a, **k): pass
class _Menu:
    SEPARATOR = object()
    def __init__(self, *a, **k): pass
pystray.Icon, pystray.MenuItem, pystray.Menu = _Icon, _MenuItem, _Menu
sys.modules["pystray"] = pystray

# ── keyboard: global hotkeys ────────────────────────────────────────────────
kb = types.ModuleType("keyboard")
kb._hotkeys = {}
def _add_hotkey(combo, cb, *a, **k):
    kb._hotkeys[combo] = cb
    return combo
kb.add_hotkey = _add_hotkey
kb.remove_hotkey = lambda *a, **k: None
kb.wait = lambda *a, **k: threading.Event().wait()
kb.is_pressed = lambda *a, **k: False
sys.modules["keyboard"] = kb

# ── ctypes.windll: the single-instance mutex ────────────────────────────────
class _K32:
    def CreateMutexW(self, *a): return 1
    def OpenMutexW(self, *a): return 0
    def CloseHandle(self, *a): return 1
    def GetLastError(self): return 0
class _WinDLL:
    kernel32 = _K32()
    user32 = _K32()
ctypes.windll = _WinDLL()

# ── go ──────────────────────────────────────────────────────────────────────
faulthandler.dump_traceback_later(30, exit=True)
timeout = float(sys.argv[1]) if len(sys.argv) > 1 else 12.0
try:
    import main as elfager
except Exception:
    print("!! IMPORT FAILED"); traceback.print_exc(); sys.exit(2)
print("== main.py imported clean ==")

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

def _probe():
    """Poke the running app the way a user would."""
    import urllib.request
    try:
        with urllib.request.urlopen("http://127.0.0.1:8765/", timeout=3) as r:
            body = r.read(400).decode("utf-8", "replace")
        FINDINGS.append(f"dashboard GET / -> HTTP {r.status}, NO AUTH, {len(body)}+ bytes")
    except Exception as e:
        FINDINGS.append(f"dashboard GET / -> {type(e).__name__}: {e}")
    cb = kb._hotkeys.get("ctrl+space")
    if cb:
        try:
            cb()
            FINDINGS.append("hotkey ctrl+space: fired without raising")
        except Exception as e:
            FINDINGS.append(f"hotkey ctrl+space RAISED: {type(e).__name__}: {e}")
    else:
        FINDINGS.append(f"hotkey ctrl+space NOT registered (have {sorted(kb._hotkeys)})")


_real_exec = QApplication.exec
def _exec(self):
    print(f"== event loop reached; running {timeout}s ==")
    QTimer.singleShot(int(timeout * 1000), self.quit)
    QTimer.singleShot(1500, _probe)
    rc = _real_exec()
    print("== event loop exited cleanly ==")
    return rc
QApplication.exec = _exec

try:
    elfager.main()
except SystemExit as e:
    print(f"== SystemExit({e.code}) ==")
except Exception:
    print("!! main() RAISED"); traceback.print_exc(); sys.exit(3)

print(f"== hotkeys registered: {sorted(kb._hotkeys)} ==")
for f in FINDINGS:
    print("   note:", f)
