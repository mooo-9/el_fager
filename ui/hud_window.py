"""
El Fager — Full-screen JARVIS HUD window (optional rich surface).

The native OverlayWindow is the primary surface (Ctrl+Space). This window
is constructed lazily by main.py the first time it's requested from the
tray — QWebEngine/Chromium never spins up at startup.

Lifecycle
---------
  Boot scene (3.8 s auto-advance) → Standby scene (idle)
  Tray → "Open JARVIS HUD" → show + go to Voice scene + start pipeline
  Escape          → hide (go back to tray)
  Pipeline done   → show contextual data scene for 6 s → Standby

Scene routing (mirrors the DC component's route() method)
---------------------------------------------------------
  Voice query about screen/code      → Vision scene (3)
  Voice query about email/messages   → Inbox scene (6)
  Voice query about calendar/tasks   → Agenda scene (7)
  Voice query about memory/journal   → Memory scene (8)
  Voice query about briefing/weather → Briefing scene (9)
  Voice query about food/calories    → Nutrition scene (10)
  Voice query about gym/workout      → Gym scene (11)
  Everything else                    → stays on Voice scene (2)

Real data wired
---------------
  Telemetry (CPU/RAM/Net) — every 2 s via psutil
  Proactive banner — event-driven from ProactiveEngine
"""

from __future__ import annotations

import psutil

_SHUTDOWN_GRACE_MS = 3000   # a fetcher parked in a network call
_TERMINATE_GRACE_MS = 1000
from PyQt6.QtCore import QPropertyAnimation, Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout

from ui.hud_web import (
    HudWebView,
    SCENE_BOOT, SCENE_STANDBY, SCENE_VOICE, SCENE_VISION,
    SCENE_DEVICES, SCENE_INBOX, SCENE_AGENDA,
    SCENE_MEMORY, SCENE_BRIEFING, SCENE_FOOD, SCENE_GYM,
)


class HudWindow(QWidget):
    """Full-screen frameless window containing the JARVIS HUD."""

    text_submitted = pyqtSignal(str)

    # Thread-safe channel: ProactiveEngine daemon thread → Qt main thread
    _proactive_signal = pyqtSignal(int, str, str, str, str)

    def __init__(self, voice_in, brain, voice_out, memory):
        super().__init__()
        self.voice_in = voice_in
        self.brain = brain
        self.voice_out = voice_out
        self.memory = memory

        self._worker = None
        self._current_state = "idle"
        self._wake_listener = None
        self._mic_muted = False
        self._last_transcript = ""

        self._setup_window()
        self._build_ui()
        self._setup_timers()
        # Nothing else ever interrupts the two background fetchers, so without
        # this Qt destroys them mid-run at teardown and the process aborts —
        # which watchdog.classify_exit() reads as a crash and restarts.
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.shutdown)

        # Wire the thread-safe proactive channel
        self._proactive_signal.connect(self._apply_proactive)

    # ------------------------------------------------------------------ #
    #  Window                                                              #
    # ------------------------------------------------------------------ #

    def _setup_window(self):
        screen = QApplication.primaryScreen().availableGeometry()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setStyleSheet("background: #03090e;")
        self.setWindowTitle("El Fager")
        self.setGeometry(screen)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._hud = HudWebView(self)
        self._hud.ready.connect(self._on_hud_ready)
        layout.addWidget(self._hud)

    def shutdown(self) -> None:
        """Stop the background fetchers so the process can exit with code 0.

        Both loops poll isInterruptionRequested() once a second, so the usual
        case returns almost at once; the grace period covers a thread parked in
        a network fetch. Terminating after that is safe — both are read-only
        fetchers — and beats the abort that destroying a running QThread causes.
        """
        for thread in (getattr(self, "_market_updater", None),
                       getattr(self, "_scene_hub", None)):
            if thread is None or not thread.isRunning():
                continue
            thread.requestInterruption()
            if thread.wait(_SHUTDOWN_GRACE_MS):
                continue
            thread.terminate()
            thread.wait(_TERMINATE_GRACE_MS)

    def _setup_timers(self):
        # 2-second telemetry push
        self._telemetry_timer = QTimer(self)
        self._telemetry_timer.setInterval(2000)
        self._telemetry_timer.timeout.connect(self._push_telemetry)
        self._telemetry_timer.start()

        # 30-second devices banner refresh (system health changes quickly)
        self._devices_timer = QTimer(self)
        self._devices_timer.setInterval(30_000)
        self._devices_timer.timeout.connect(self._push_devices_banner)
        self._devices_timer.start()

        # Scene data hub — briefing/inbox/agenda/memory/food/gym (every 5 min)
        from ui.hud_scene_hub import HudSceneHub
        self._scene_hub = HudSceneHub(self)
        self._scene_hub.briefing_ready.connect(
            lambda p, h, s, t: self._hud.push_proactive(SCENE_BRIEFING, p, h, s, t))
        self._scene_hub.inbox_ready.connect(
            lambda p, h, s, t: self._hud.push_proactive(SCENE_INBOX, p, h, s, t))
        self._scene_hub.agenda_ready.connect(
            lambda p, h, s, t: self._hud.push_proactive(SCENE_AGENDA, p, h, s, t))
        self._scene_hub.memory_ready.connect(
            lambda p, h, s, t: self._hud.push_proactive(SCENE_MEMORY, p, h, s, t))
        # devices banner handled by 30-second _push_devices_banner timer
        self._scene_hub.nutrition_ready.connect(
            lambda p, h, s, t: self._hud.push_proactive(SCENE_FOOD, p, h, s, t))
        self._scene_hub.nutrition_data.connect(self._on_nutrition_data)
        self._scene_hub.gym_ready.connect(
            lambda p, h, s, t: self._hud.push_proactive(SCENE_GYM, p, h, s, t))
        self._scene_hub.start()

    # ------------------------------------------------------------------ #
    #  HUD bridge                                                          #
    # ------------------------------------------------------------------ #

    def _on_hud_ready(self):
        """Called once the React component is mounted and _elf is live.
        The DC component handles Boot→Standby internally via componentDidMount.
        """

    def _push_telemetry(self):
        try:
            cpu = int(psutil.cpu_percent())
            ram = int(psutil.virtual_memory().percent)
            net = round(psutil.net_io_counters().bytes_sent / 1_000_000, 1)
            self._hud.push_telemetry(cpu, ram, net)
        except Exception:
            pass

    def _push_devices_banner(self):
        try:
            cpu  = psutil.cpu_percent(interval=0)
            ram  = psutil.virtual_memory()
            disk = psutil.disk_usage("C:\\")
            ram_gb  = ram.used  / (1024 ** 3)
            tot_gb  = ram.total / (1024 ** 3)
            free_gb = disk.free / (1024 ** 3)
            self._hud.push_proactive(
                SCENE_DEVICES,
                f"CPU {cpu:.0f}%  ·  RAM ",
                f"{ram_gb:.1f}/{tot_gb:.0f} GB",
                f"  ·  {free_gb:.0f} GB free",
                "SYSTEM",
            )
        except Exception:
            pass

    @pyqtSlot(int, int, int, int, int, int, int, int)
    def _on_nutrition_data(
        self,
        kcal: int, protein: int, carbs: int, fat: int,
        logged_kcal: int, logged_protein: int, logged_carbs: int, logged_fat: int):
        self._hud.push_nutrition(
            kcal, protein, carbs, fat,
            logged_kcal, logged_protein, logged_carbs, logged_fat,
        )

    # ------------------------------------------------------------------ #
    #  Proactive banner (thread-safe wiring from ProactiveEngine)          #
    # ------------------------------------------------------------------ #

    def notify_hud(self, scene: int, prefix: str, highlight: str, suffix: str, tag: str):
        """
        Thread-safe entry point called from the ProactiveEngine daemon thread.
        Marshals the update to the Qt main thread via a queued signal.
        """
        self._proactive_signal.emit(scene, prefix, highlight, suffix, tag)

    @pyqtSlot(int, str, str, str, str)
    def _apply_proactive(self, scene: int, prefix: str, highlight: str, suffix: str, tag: str):
        self._hud.push_proactive(scene, prefix, highlight, suffix, tag)

    # ------------------------------------------------------------------ #
    #  Wake listener wiring (called from main.py)                         #
    # ------------------------------------------------------------------ #

    def set_wake_listener(self, listener):
        self._wake_listener = listener

    # ------------------------------------------------------------------ #
    #  Show / hide                                                         #
    # ------------------------------------------------------------------ #

    def toggle(self):
        if self.isVisible():
            self._close_hud()
        else:
            self._open_hud()

    def _open_hud(self):
        self.setWindowOpacity(0.0)
        self.show()
        self._fade(1.0)
        self._hud.goto_scene(SCENE_VOICE)
        # A worker from a previous open may still be unwinding - show the HUD
        # anyway, just don't stack a second pipeline on top of it.
        if not self._mic_muted and not (self._worker and self._worker.isRunning()):
            self._start_pipeline()

    def _close_hud(self):
        if self._worker and self._worker.isRunning():
            # PipelineWorker overrides run(), so quit() has no event loop to
            # exit and wait() would freeze the Qt main thread for its full
            # timeout. Signal the worker and let it unwind in the background.
            self.voice_in.stop_recording()
            self.voice_out.stop()
        self._fade(0.0, then_hide=True)
        self._current_state = "idle"

    def _fade(self, to: float, then_hide: bool = False):
        anim = QPropertyAnimation(self, b"windowOpacity")
        anim.setDuration(160)
        anim.setStartValue(self.windowOpacity())
        anim.setEndValue(to)
        if then_hide:
            anim.finished.connect(self.hide)
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        self._fade_anim = anim

    def wake_word_activate(self):
        if self._worker and self._worker.isRunning():
            return
        if self._mic_muted:
            return
        self.setWindowOpacity(0.0)
        self.show()
        self._fade(1.0)
        self._hud.goto_scene(SCENE_VOICE)
        self._start_pipeline()

    # ------------------------------------------------------------------ #
    #  Pipeline                                                            #
    # ------------------------------------------------------------------ #

    def _start_pipeline(self, text_input: "str | None" = None):
        from core.pipeline import PipelineWorker

        self._worker = PipelineWorker(
            self.voice_in,
            self.brain,
            self.voice_out,
            self.memory,
            text_input=text_input,
        )
        self._worker.state_update.connect(self.on_state_update)
        self._worker.done.connect(self.on_pipeline_done)
        self._worker.error.connect(self.on_error)

        if self._wake_listener:
            self._worker.started.connect(self._wake_listener.pause)
            self._worker.done.connect(self._wake_listener.resume)
            self._worker.error.connect(
                lambda _: self._wake_listener.resume() if self._wake_listener else None
            )

        self._worker.start()

    def analyze_screen(self):
        if self._worker and self._worker.isRunning():
            return
        if not self.isVisible():
            self.setWindowOpacity(0.0)
            self.show()
            self._fade(1.0)
        self._hud.goto_scene(SCENE_VISION)
        self._hud.push_proactive(SCENE_VISION, "Capturing screen — ", "analysis in progress", "", "WATCHING")
        self._start_pipeline(text_input="what's on my screen")

    def query_memory(self):
        if self._worker and self._worker.isRunning():
            return
        if not self.isVisible():
            self.setWindowOpacity(0.0)
            self.show()
            self._fade(1.0)
        self._hud.goto_scene(SCENE_MEMORY)
        self._start_pipeline(text_input="what do you know about me?")

    def run_briefing(self, prompt: str):
        if self._worker and self._worker.isRunning():
            return
        if not self.isVisible():
            self.setWindowOpacity(0.0)
            self.show()
            self._fade(1.0)
        self._hud.goto_scene(SCENE_BRIEFING)
        self._start_pipeline(text_input=prompt)

    # ------------------------------------------------------------------ #
    #  Scene routing                                                       #
    # ------------------------------------------------------------------ #

    def _route_scene_for_query(self, query: str) -> int:
        """Map a natural-language query to the most relevant HUD scene."""
        q = query.lower()
        has = lambda *ws: any(w in q for w in ws)

        if has("screen", "code", "error", "bug", "screenshot", "analyze"):
            return SCENE_VISION

        if has("email", "mail", "gmail", "whatsapp", "inbox", "message"):
            return SCENE_INBOX

        if has("remind", "calendar", "agenda", "task", "todo", "event", "schedule"):
            return SCENE_AGENDA

        if has("journal", "memory", "remember", "know about", "you know"):
            return SCENE_MEMORY

        if has("brief", "morning", "summary", "weather", "prayer", "news"):
            return SCENE_BRIEFING

        if has("eat", "food", "calorie", "macro", "protein", "meal", "diet", "water"):
            return SCENE_FOOD

        if has("workout", "gym", "train", "lift", "bench", "squat", "exercise", "reps"):
            return SCENE_GYM

        return SCENE_VOICE

    # ------------------------------------------------------------------ #
    #  State callbacks from pipeline                                       #
    # ------------------------------------------------------------------ #

    @pyqtSlot(str, str, str)
    def on_state_update(self, state: str, transcript: str, response: str):
        self._current_state = state

        if state == "listening":
            self._hud.goto_scene(SCENE_VOICE)
            self._hud.set_state({"processing": False})

        elif state == "processing":
            self._hud.set_state({"processing": True})
            if transcript:
                self._last_transcript = transcript

        elif state == "speaking":
            self._hud.set_state({"processing": False})
            heard = transcript or self._last_transcript
            if heard and response:
                # 1. Show conversation in Voice scene
                self._hud.push_voice_result(heard, response)
                # 2. After 3.5 s, navigate to the contextual data scene
                target = self._route_scene_for_query(heard)
                if target != SCENE_VOICE:
                    scene_val = target
                    QTimer.singleShot(
                        3500,
                        lambda: self._hud.goto_scene(scene_val)
                    )
                # 3. Vision scene: update banner with analysis summary
                if target == SCENE_VISION and response:
                    summary = response[:72].rstrip()
                    if len(response) > 72:
                        summary = summary.rsplit(" ", 1)[0] + "..."
                    self._hud.push_proactive(
                        SCENE_VISION, "Screen: ", summary, "", "VISION"
                    )

    @pyqtSlot()
    def on_pipeline_done(self):
        self._current_state = "idle"
        # Return to Standby after 6 s if user hasn't interacted
        QTimer.singleShot(6000, self._return_to_standby)

    @pyqtSlot(str)
    def on_error(self, message: str):
        self._current_state = "error"
        self._hud.set_state({"processing": False})

    def _return_to_standby(self):
        if self._current_state == "idle" and self.isVisible():
            self._hud.goto_scene(SCENE_STANDBY)

    # ------------------------------------------------------------------ #
    #  Keyboard                                                            #
    # ------------------------------------------------------------------ #

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Escape:
            self._close_hud()
        else:
            super().keyPressEvent(event)

    # ------------------------------------------------------------------ #
    #  Close → hide (real quit via tray)                                   #
    # ------------------------------------------------------------------ #

    def closeEvent(self, event):
        event.ignore()
        self._close_hud()
