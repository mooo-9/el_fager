"""
El Fager — Main entry point.

Threading model:
  Main thread    : PyQt6 event loop
  Daemon thread  : pystray (Win32 message loop — blocks indefinitely)
  Background hook: keyboard hotkey fires in bg thread →
                   HotkeySignaler (QObject) emits signal →
                   Qt auto-queues delivery to main thread
  Per-invocation : PipelineWorker (QThread) runs voice loop
"""

import json
import os
import sys
import threading
import winreg
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import pygame.mixer
import pystray
from PIL import Image, ImageDraw

import keyboard
from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from core.brain import Brain
from core.memory import Memory
from core.scheduler import ElFagerScheduler
from core.voice_in import VoiceInput
from core.voice_out import VoiceOutput
from core.wake_word import WakeWordListener
from ui.overlay import OverlayWindow


# ──────────────────────────────────────────────────────────────────────────────
# Hotkey bridge
# The `keyboard` library fires its callbacks in a background thread.
# Emitting a Qt signal from a non-Qt thread is safe — Qt will queue the
# delivery and process it in the receiver's thread (the main thread here).
# ──────────────────────────────────────────────────────────────────────────────


class HotkeySignaler(QObject):
    triggered = pyqtSignal()
    analyze_triggered = pyqtSignal()
    memory_query_triggered = pyqtSignal()
    memory_clear_triggered = pyqtSignal()
    wake_word_detected = pyqtSignal()


# ──────────────────────────────────────────────────────────────────────────────
# Tray icon
# ──────────────────────────────────────────────────────────────────────────────


def _make_tray_image() -> Image.Image:
    """Create a 64×64 RGBA tray icon — cyan ring on dark background."""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([4, 4, 60, 60], fill=(10, 10, 15, 255))
    draw.ellipse([10, 10, 54, 54], fill=(100, 200, 255, 255))
    draw.ellipse([18, 18, 46, 46], fill=(10, 10, 15, 255))
    draw.ellipse([26, 26, 38, 38], fill=(100, 200, 255, 255))
    return img


# ──────────────────────────────────────────────────────────────────────────────
# Windows startup registration
# ──────────────────────────────────────────────────────────────────────────────


def _register_startup():
    """Add El Fager to Windows HKCU startup registry so it runs on login."""
    try:
        exe = sys.executable
        script = str(Path(__file__).resolve())
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE,
        )
        winreg.SetValueEx(key, "ElFager", 0, winreg.REG_SZ, f'"{exe}" "{script}"')
        winreg.CloseKey(key)
    except Exception as e:
        print(f"[El Fager] Startup registration failed (non-fatal): {e}")


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────


def main():
    # Qt must own the main thread.
    # setQuitOnLastWindowClosed(False) is critical — the overlay hides (not closes),
    # and without this Qt would quit the app when the overlay is dismissed.
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("El Fager")

    # Load profile
    profile_path = Path(__file__).parent / "profile.json"
    profile = json.loads(profile_path.read_text(encoding="utf-8"))

    # Initialize audio mixer (pygame.mixer only, NOT pygame.init() — avoids
    # SDL display subsystem which conflicts with Qt on some Windows setups)
    pygame.mixer.init()

    # Ensure data directories exist before any component needs them
    os.makedirs("data", exist_ok=True)
    os.makedirs("data/chroma", exist_ok=True)
    os.makedirs("data/conversations", exist_ok=True)

    # Core components
    voice_in = VoiceInput()          # Whisper loads in background daemon thread
    voice_out = VoiceOutput()
    memory = Memory()
    brain = Brain(profile, memory)   # memory reference passed for tool dispatch + facts injection

    # App window
    overlay = OverlayWindow(voice_in, brain, voice_out, memory)

    # Set window icon (generate .ico once, then reuse)
    _icon_path = Path("data/el_fager.ico")
    if not _icon_path.exists():
        _icon_img = _make_tray_image().resize((256, 256), Image.LANCZOS)
        _icon_img.save(str(_icon_path), format="ICO", sizes=[(256,256),(64,64),(32,32),(16,16)])
    overlay.setWindowIcon(QIcon(str(_icon_path)))

    # ── Hotkey bridge ──────────────────────────────────────────────────────
    signaler = HotkeySignaler()
    signaler.triggered.connect(overlay.toggle)
    signaler.analyze_triggered.connect(overlay.analyze_screen)
    signaler.memory_query_triggered.connect(overlay.query_memory)

    def _on_memory_clear():
        from PyQt6.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            None,
            "Clear Memory",
            "Clear all El Fager's memory? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            memory.clear_all()
            QMessageBox.information(None, "El Fager", "Memory cleared.")

    signaler.memory_clear_triggered.connect(_on_memory_clear)
    keyboard.add_hotkey("ctrl+space", signaler.triggered.emit)
    print("[El Fager] Hotkey Ctrl+Space registered.")

    # ── Wake word listener ─────────────────────────────────────────────────
    wake_listener = WakeWordListener(on_detected=signaler.wake_word_detected.emit)
    signaler.wake_word_detected.connect(overlay.wake_word_activate)
    overlay.set_wake_listener(wake_listener)
    wake_listener.start()

    # ── System tray ────────────────────────────────────────────────────────
    def on_tray_open(icon, item):
        signaler.triggered.emit()

    def on_tray_analyze(icon, item):
        signaler.analyze_triggered.emit()

    def on_tray_memory_query(icon, item):
        signaler.memory_query_triggered.emit()

    def on_tray_memory_clear(icon, item):
        signaler.memory_clear_triggered.emit()

    def on_tray_wake_toggle(icon, item):
        if not wake_listener.available:
            return
        if wake_listener._running:
            wake_listener.stop()
            print("[El Fager] Wake word paused via tray.")
        else:
            wake_listener.start()
            print("[El Fager] Wake word resumed via tray.")

    def on_tray_quit(icon, item):
        wake_listener.stop()
        icon.stop()
        app.quit()

    def _wake_word_label(item):
        if not wake_listener.available:
            return "Wake Word: unavailable"
        return "Wake Word: ON" if wake_listener._running else "Wake Word: OFF"

    def on_tray_activate(icon, button):
        """Double-click or left-click on tray icon toggles the window."""
        signaler.triggered.emit()

    tray = pystray.Icon(
        name="el_fager",
        icon=_make_tray_image(),
        title="El Fager",
        menu=pystray.Menu(
            pystray.MenuItem("Open  (Ctrl+Space)", on_tray_open),
            pystray.MenuItem("Analyze Screen", on_tray_analyze),
            pystray.MenuItem("Memory", pystray.Menu(
                pystray.MenuItem("What do you know about me?", on_tray_memory_query),
                pystray.MenuItem("Clear all memory", on_tray_memory_clear),
            )),
            pystray.MenuItem(
                _wake_word_label,
                on_tray_wake_toggle,
                enabled=lambda item: wake_listener.available,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", on_tray_quit),
        ),
    )

    # pystray.run() blocks — must live in a daemon thread
    tray_thread = threading.Thread(target=tray.run, daemon=True)
    tray_thread.start()
    print("[El Fager] System tray active.")

    # ── Windows startup entry ──────────────────────────────────────────────
    _register_startup()

    # ── Reminder checker ──────────────────────────────────────────────────
    from tools.reminder_tool import check_reminders
    reminder_timer = QTimer()
    reminder_timer.setInterval(30_000)  # every 30 seconds
    reminder_timer.timeout.connect(check_reminders)
    reminder_timer.start()

    # ── Clipboard history monitor ─────────────────────────────────────────────
    from tools.clipboard_history_tool import start_clipboard_monitor
    start_clipboard_monitor()

    # ── Proactive scheduler ───────────────────────────────────────────────────
    from core.scheduler import _set_instance
    from core.defaults import seed_default_schedules
    seed_default_schedules()           # no-op if schedules already exist

    scheduler = ElFagerScheduler()
    _set_instance(scheduler)          # share the live instance with all tool code
    try:
        scheduler.set_speak_callback(voice_out.speak)
    except Exception:
        pass
    scheduler.start()

    # ── Proactive engine (condition-based, autonomous checks) ─────────────────
    from core.proactive import ProactiveEngine
    proactive = ProactiveEngine(speak_fn=voice_out.speak, memory=memory, brain_fn=brain.chat)
    proactive.start()

    # ── Macro speak callback (enables mid-macro TTS announcements) ────────────
    from tools.macro_tool import set_speak_callback as _macro_speak_cb
    _macro_speak_cb(voice_out.speak)
    from tools.trading_tool import set_trading_speak_callback as _trading_speak_cb, start_trading_engine as _start_trading
    _trading_speak_cb(voice_out.speak)
    _start_trading()   # auto-start paper trading on every launch

    # ── Daily briefing ────────────────────────────────────────────────────────
    from core.briefing import already_briefed_today, mark_briefed_today, get_briefing_prompt

    def _run_daily_briefing():
        if already_briefed_today():
            return
        mark_briefed_today()
        overlay.run_briefing(get_briefing_prompt())

    QTimer.singleShot(3000, _run_daily_briefing)

    # Show window on startup — El Fager is now a persistent app, not a popup
    overlay.show()

    print("[El Fager] Running. Press Ctrl+Space to activate.")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
