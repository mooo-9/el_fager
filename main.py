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
from pathlib import Path

# Force line-buffered stdout so print() inside Qt callbacks flushes immediately
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

from dotenv import load_dotenv

load_dotenv()

# ── WebEngine must be configured before QApplication is created ────────────
# Force software rendering — avoids GPU process crashes on machines without
# proper OpenGL virtualization (common on laptops with hybrid graphics).
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--no-sandbox"
os.environ["QTWEBENGINE_DISABLE_SANDBOX"] = "1"

import pygame.mixer
import pystray
from PIL import Image, ImageDraw

import keyboard
# QWebEngineWidgets MUST be imported before QApplication is instantiated.
from PyQt6.QtWebEngineWidgets import QWebEngineView  # noqa: F401 — side-effect import
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
    hud_triggered = pyqtSignal()
    cockpit_triggered = pyqtSignal()
    command_center_triggered = pyqtSignal()
    analyze_triggered = pyqtSignal()
    memory_query_triggered = pyqtSignal()
    memory_clear_triggered = pyqtSignal()
    wake_word_detected = pyqtSignal()
    second_launch = pyqtSignal()      # the desktop icon, clicked again


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
# Main
# ──────────────────────────────────────────────────────────────────────────────


_INSTANCE_MUTEX = None  # kept alive at module level so GC doesn't release it


# A second launch hands off to the running instance through this event rather
# than dying quietly. Auto-reset, so each click wakes the waiter exactly once.
_SHOW_EVENT_NAME = "ElFagerShowRequested"


def _signal_running_instance() -> bool:
    """Ask the instance that owns the mutex to show itself. True if it heard."""
    import ctypes
    EVENT_MODIFY_STATE = 0x0002
    handle = ctypes.windll.kernel32.OpenEventW(EVENT_MODIFY_STATE, False,
                                               _SHOW_EVENT_NAME)
    if not handle:
        return False
    try:
        return bool(ctypes.windll.kernel32.SetEvent(handle))
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def _watch_for_second_launch(signaler) -> None:
    """Wait on the show event and raise the surface when a second launch asks.

    Clicking the desktop icon while El Fager was already running used to start
    a process that found the mutex, showed a toast telling Mo to go and find
    the tray himself, and exited. Under pythonw there is no console either, so
    the icon simply looked broken. Now the running instance comes forward.
    """
    import ctypes
    import threading

    handle = ctypes.windll.kernel32.CreateEventW(None, False, False,
                                                 _SHOW_EVENT_NAME)
    if not handle:
        return

    def wait_loop():
        while True:
            # INFINITE wait; the thread is a daemon and dies with the process.
            if ctypes.windll.kernel32.WaitForSingleObject(handle, 0xFFFFFFFF) != 0:
                return
            signaler.second_launch.emit()

    threading.Thread(target=wait_loop, daemon=True).start()


def _acquire_instance_lock() -> None:
    """Exit immediately if another El Fager process is already running."""
    global _INSTANCE_MUTEX
    import ctypes
    _INSTANCE_MUTEX = ctypes.windll.kernel32.CreateMutexW(None, True, "ElFagerSingleInstance")
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        print("[El Fager] Already running — asking that instance to show itself.")
        if not _signal_running_instance():
            # The mutex is held but nothing is listening: an older build, or a
            # process wedged mid-shutdown. Say so rather than exiting silently.
            try:
                from winotify import Notification
                Notification(
                    app_id="El Fager",
                    title="El Fager",
                    msg="Already running, but not responding. Check the system tray.",
                    duration="short",
                ).show()
            except Exception:
                pass
        sys.exit(0)


def main():
    _acquire_instance_lock()

    # Qt must own the main thread.
    # setQuitOnLastWindowClosed(False) is critical — the overlay hides (not closes),
    # and without this Qt would quit the app when the overlay is dismissed.
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("El Fager")

    # Design fonts are bundled (OFL) and registered here, never fetched at
    # runtime. Falls back to Segoe UI if the files are missing.
    from ui import theme, tokens
    if theme.register_fonts():
        _app_font = app.font()
        _app_font.setFamilies([tokens.FONT_UI, "Segoe UI"])
        app.setFont(_app_font)

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

    # Sound cues ride the staging + progress registries — they already
    # report exactly what happened.
    from core import sound
    sound.wire()

    # ── Windows icon ───────────────────────────────────────────────────────
    _icon_path = Path("data/el_fager.ico")
    if not _icon_path.exists():
        _icon_img = _make_tray_image().resize((256, 256), Image.LANCZOS)
        _icon_img.save(str(_icon_path), format="ICO", sizes=[(256,256),(64,64),(32,32),(16,16)])

    # ── Primary window: native compact assistant ───────────────────────────
    overlay = OverlayWindow(voice_in, brain, voice_out, memory)
    overlay.setWindowIcon(QIcon(str(_icon_path)))

    # ── Optional rich HUD: constructed lazily on first request ─────────────
    # QWebEngine (Chromium) is heavy — it must not spin up at startup.
    _hud_ref: list = [None]
    _cockpit_ref: list = [None]

    # ── Hotkey bridge ──────────────────────────────────────────────────────
    signaler = HotkeySignaler()
    signaler.triggered.connect(overlay.toggle)       # Ctrl+Space → assistant
    signaler.analyze_triggered.connect(overlay.analyze_screen)
    signaler.memory_query_triggered.connect(overlay.query_memory)

    def _on_second_launch():
        """The desktop icon, clicked while El Fager was already running.

        present(), not toggle(): clicking an app's icon means "come here",
        and toggle would hide the window if it happened to be open already.
        """
        overlay.present()
        overlay.raise_()
        overlay.activateWindow()

    signaler.second_launch.connect(_on_second_launch)
    _watch_for_second_launch(signaler)

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
    # Two ways in for each surface. Ctrl+Space is the design's canonical
    # summon; the F12 pair is for the hand that's already on the top row.
    # (Fn itself cannot be bound — it never leaves the keyboard's firmware,
    # so Windows and the keyboard library never see it.)
    for combo, emit, surface in (
        ("ctrl+space", signaler.triggered.emit, "overlay"),
        ("ctrl+f12", signaler.triggered.emit, "overlay"),
        ("ctrl+shift+space", signaler.command_center_triggered.emit, "Command Center"),
        ("ctrl+shift+f12", signaler.command_center_triggered.emit, "Command Center"),
    ):
        try:
            keyboard.add_hotkey(combo, emit)
            print(f"[El Fager] Hotkey {combo} registered ({surface}).")
        except Exception as e:
            # Another app owning a combo must not stop El Fager from starting.
            print(f"[El Fager] Hotkey {combo} unavailable ({e}); the others still work.")

    # ── Wake word listener ─────────────────────────────────────────────────
    wake_listener = WakeWordListener(on_detected=signaler.wake_word_detected.emit)

    def _on_wake_word():
        """Which surface answers when you call it.

        Settings key `wake_surface`: "overlay" (default — the fast native
        path, one frame to visible) or "cockpit" (the design's primary
        surface, at the cost of building Chromium on the first wake). The
        cockpit blooms whenever it is already up, whichever is configured.
        """
        cockpit = _cockpit_ref[0]
        try:
            from ui.overlay import _load_settings
            surface = str(_load_settings().get("wake_surface", "overlay")).lower()
        except Exception:
            surface = "overlay"

        if surface == "cockpit":
            _get_cockpit().wake_word_activate()
            return
        overlay.wake_word_activate()
        if cockpit is not None and cockpit.isVisible():
            cockpit.wake_word_activate()   # already up: bloom, don't summon

    signaler.wake_word_detected.connect(_on_wake_word)
    overlay.set_wake_listener(wake_listener)  # also builds the overlay UI

    def _get_hud():
        """Construct the full-screen JARVIS HUD on first use (main thread only)."""
        if _hud_ref[0] is None:
            from ui.hud_window import HudWindow
            hud = HudWindow(voice_in, brain, voice_out, memory)
            hud.setWindowIcon(QIcon(str(_icon_path)))
            hud.set_wake_listener(wake_listener)
            _hud_ref[0] = hud
        return _hud_ref[0]

    def _get_cockpit():
        """The design's primary full-screen surface. Also lazy — its orb is
        the one QWebEngine instance El Fager runs."""
        if _cockpit_ref[0] is None:
            from ui.cockpit import CockpitWindow
            cockpit = CockpitWindow(voice_in, brain, voice_out, memory)
            cockpit.setWindowIcon(QIcon(str(_icon_path)))
            cockpit.set_wake_listener(wake_listener)
            # Its view pill hands the screen to the Command Center. The
            # cockpit closes itself first, so toggle() can only open.
            cockpit.knowledge_requested.connect(
                lambda: _get_command_center().toggle())
            _cockpit_ref[0] = cockpit
        return _cockpit_ref[0]

    # Started only now: _on_wake_word can reach for the cockpit, so the
    # listener must not be able to fire before that closure exists.
    wake_listener.start()

    # HUD opens from the tray; pystray callbacks run off the main thread, so
    # marshal construction through a Qt signal.
    signaler.hud_triggered.connect(lambda: _get_hud().toggle())
    signaler.cockpit_triggered.connect(lambda: _get_cockpit().toggle())
    # The overlay's expand button: small surface → big one. open(), not
    # toggle() — the overlay has already hidden itself, so there is nothing
    # for a second press to fold back into.
    overlay.expand_requested.connect(lambda: _get_cockpit().open())

    # ── Command center: native shell, constructed lazily on first open ─────
    _cc_ref: list = [None]

    def _get_command_center():
        if _cc_ref[0] is None:
            from ui.command_center import CommandCenterWindow
            cc = CommandCenterWindow(voice_in, brain, voice_out, memory, wake_listener)
            cc.setWindowIcon(QIcon(str(_icon_path)))
            _cc_ref[0] = cc
        return _cc_ref[0]

    signaler.command_center_triggered.connect(lambda: _get_command_center().toggle())

    # ── System tray ────────────────────────────────────────────────────────
    def on_tray_open(icon, item):
        signaler.triggered.emit()

    def on_tray_hud(icon, item):
        """Open the optional full-screen JARVIS HUD (lazily constructed)."""
        signaler.hud_triggered.emit()

    def on_tray_cockpit(icon, item):
        """Open the Cockpit — the design's primary full-screen surface."""
        signaler.cockpit_triggered.emit()

    def on_tray_command_center(icon, item):
        """Open the today-at-a-glance command center (lazily constructed)."""
        signaler.command_center_triggered.emit()

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
            pystray.MenuItem("Open Assistant  (Ctrl+Space)", on_tray_open),
            pystray.MenuItem("Open Command Center", on_tray_command_center),
            pystray.MenuItem("Open Cockpit", on_tray_cockpit),
            pystray.MenuItem("Open JARVIS HUD (legacy)", on_tray_hud),
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

    # ── Background services (deferred past first paint) ────────────────────
    # None of these are needed in the first seconds; starting them via a
    # singleShot lets the event loop begin and the assistant window paint
    # before scheduler/proactive/dashboard imports and threads spin up.
    _services: dict = {}

    def _start_background_services():
        # Reminder checker
        from tools.reminder_tool import check_reminders
        reminder_timer = QTimer()
        reminder_timer.setInterval(30_000)  # every 30 seconds
        reminder_timer.timeout.connect(check_reminders)
        reminder_timer.start()
        _services["reminder_timer"] = reminder_timer

        # Clipboard history monitor
        from tools.clipboard_history_tool import start_clipboard_monitor
        start_clipboard_monitor()

        # Proactive scheduler
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
        _services["scheduler"] = scheduler

        # Proactive engine (condition-based, autonomous checks)
        from core.proactive import ProactiveEngine
        # brain_fn MUST be chat_background: proactive runs in a daemon thread and
        # must never splice its turns into the voice pipeline's live conversation.
        proactive = ProactiveEngine(speak_fn=voice_out.speak, memory=memory, brain_fn=brain.chat_background)

        def _notify_hud(scene, prefix, highlight, suffix, tag):
            """Forward proactive banners to the HUD only if it has been opened."""
            hud = _hud_ref[0]
            if hud is not None:
                hud.notify_hud(scene, prefix, highlight, suffix, tag)

        proactive.set_hud_notify(_notify_hud)
        proactive.start()
        _services["proactive"] = proactive

        # Macro speak callback (enables mid-macro TTS announcements)
        from tools.macro_tool import set_speak_callback as _macro_speak_cb
        _macro_speak_cb(voice_out.speak)

        # Read-only LAN dashboard (phone-viewable status page)
        from core.dashboard import start_dashboard
        start_dashboard()

        print("[El Fager] Background services started.")

    QTimer.singleShot(1500, _start_background_services)

    # ── Startup health check (daemon thread, ~10 s after launch) ───────────
    def _startup_health_check():
        problems = []

        key = os.getenv("ANTHROPIC_API_KEY", "").strip()
        if not key or key.startswith("sk-ant-xxx"):
            problems.append("ANTHROPIC_API_KEY missing — the brain cannot answer")
        else:
            try:
                import anthropic
                anthropic.Anthropic().models.list()  # free auth probe
            except anthropic.AuthenticationError:
                problems.append("Anthropic API key invalid — check .env")
            except Exception:
                pass  # network blips are not startup-fatal

        if not os.getenv("GROQ_API_KEY", "").strip():
            problems.append("GROQ_API_KEY not set — slower local Whisper + Edge TTS in use")

        if getattr(memory, "degraded", False):
            problems.append("Vector memory failed to load (facts still work)")

        if not problems:
            print("[El Fager] Health check: all critical services OK.")
            return
        msg = " | ".join(problems)
        print(f"[El Fager] Health check: {msg}")
        try:
            from winotify import Notification
            Notification(
                app_id="El Fager",
                title="El Fager health check",
                msg=msg[:256],
                duration="long",
            ).show()
        except Exception:
            pass

    QTimer.singleShot(
        10_000,
        lambda: threading.Thread(target=_startup_health_check, daemon=True).start(),
    )

    # Launching is now a deliberate act (Desktop shortcut) — not a login
    # autostart — so show the assistant. The daily briefing is NOT auto-run;
    # it stays on the 7:30am schedule and the Command Center's Briefing button.
    # First run only: an unnamed profile means we have never met.
    if not profile.get("name", "").strip():
        from ui.onboarding import OnboardingWindow
        _onboarding = OnboardingWindow(voice_in, voice_out, wake_listener)
        _onboarding.finished.connect(overlay.present)
        _onboarding.open()
    else:
        overlay.present()

    print("[El Fager] Running. Press Ctrl+Space to activate.")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
