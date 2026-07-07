"""
El Fager — native compact assistant (the default surface).

W3 hybrid-UI rewrite: this window is the one El Fager opens on Ctrl+Space —
a single fast native-Qt card with the conversation, live state, and text
input. No QWebEngine, no mode cycling; the rich full-screen HUD lives in
ui/hud_window.py and is constructed lazily on demand (tray menu).

Visuals come from ui/theme.py (layered dark palette, warm copper accent,
distinct listening / thinking / speaking state colors).
"""

import json
from pathlib import Path

from PyQt6.QtCore import (
    QEvent,
    QPropertyAnimation,
    Qt,
    QTimer,
    pyqtSignal,
    pyqtSlot,
)
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QKeyEvent,
    QPainter,
    QPen,
)
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ui import theme

_SETTINGS_FILE = Path("data/settings.json")
_MAX_HISTORY = 15


def _load_settings() -> dict:
    if _SETTINGS_FILE.exists():
        try:
            return json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "model": "claude-sonnet-4-6",
        "tts_backend": "edge",
        "voice_en": "en-US-GuyNeural",
        "voice_ar": "ar-EG-ShakirNeural",
        "wake_word_enabled": True,
        "theme": "dark",
        "local_llm_fallback": True,
        "ollama_model": "llama3.2",
    }


def _save_settings(data: dict) -> None:
    _SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _SETTINGS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ──────────────────────────────────────────────────────────────────────────────
# State ring — pulses in the current state's color
# ──────────────────────────────────────────────────────────────────────────────

class RingCanvas(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(24, 24)
        self._angle = 0.0
        self._spinning = False
        self._color = QColor(theme.STATE_COLORS["idle"])

    def set_state_color(self, state: str):
        self._color = QColor(theme.STATE_COLORS.get(state, theme.TEXT_MUTED))
        self.update()

    def start_spin(self):
        self._spinning = True
        self.update()

    def stop_spin(self):
        self._spinning = False
        self._angle = 0.0
        self.update()

    def tick(self):
        if self._spinning:
            self._angle = (self._angle + 12) % 360
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy = 12, 12
        r = 8

        if self._spinning:
            # Background ring
            dim = QColor(self._color)
            dim.setAlpha(45)
            pen = QPen(dim)
            pen.setWidth(3)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawEllipse(cx - r, cy - r, r * 2, r * 2)

            # Spinning arc
            bright = QColor(self._color)
            bright.setAlpha(230)
            pen2 = QPen(bright)
            pen2.setWidth(3)
            pen2.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen2)
            p.drawArc(cx - r, cy - r, r * 2, r * 2, int(-self._angle * 16), 100 * 16)
        else:
            # Static small dot
            p.setPen(Qt.PenStyle.NoPen)
            dot = QColor(self._color)
            dot.setAlpha(150)
            p.setBrush(QBrush(dot))
            p.drawEllipse(cx - 4, cy - 4, 8, 8)


# ──────────────────────────────────────────────────────────────────────────────
# Bubble message widget
# ──────────────────────────────────────────────────────────────────────────────

class MessageBubble(QWidget):
    def __init__(self, role: str, text: str, timestamp: str = "", parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)

        is_user = (role == "user")
        if is_user:
            layout.addStretch()

        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setMaximumWidth(460)
        lbl.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        if timestamp:
            lbl.setToolTip(timestamp)

        lbl.setStyleSheet(theme.BUBBLE_USER if is_user else theme.BUBBLE_ASSISTANT)

        layout.addWidget(lbl)
        if not is_user:
            layout.addStretch()


# ──────────────────────────────────────────────────────────────────────────────
# Settings dialog
# ──────────────────────────────────────────────────────────────────────────────

class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("El Fager Settings")
        self.setMinimumWidth(360)
        self.setStyleSheet(theme.DIALOG)

        self._settings = _load_settings()
        form = QFormLayout(self)
        form.setSpacing(10)
        form.setContentsMargins(16, 16, 16, 16)

        self._model_combo = QComboBox()
        self._model_combo.addItems(["claude-sonnet-4-6", "claude-opus-4-8", "claude-haiku-4-5-20251001"])
        self._model_combo.setCurrentText(self._settings.get("model", "claude-sonnet-4-6"))
        form.addRow("Model:", self._model_combo)

        self._tts_combo = QComboBox()
        self._tts_combo.addItems(["edge", "groq"])
        self._tts_combo.setCurrentText(self._settings.get("tts_backend", "edge"))
        form.addRow("TTS backend:", self._tts_combo)

        self._voice_en_combo = QComboBox()
        for v in ["en-US-GuyNeural", "en-US-JennyNeural", "en-GB-RyanNeural", "en-AU-WilliamNeural"]:
            self._voice_en_combo.addItem(v)
        self._voice_en_combo.setCurrentText(self._settings.get("voice_en", "en-US-GuyNeural"))
        form.addRow("Voice (EN):", self._voice_en_combo)

        self._voice_ar_combo = QComboBox()
        for v in ["ar-EG-ShakirNeural", "ar-EG-SalmaNeural", "ar-SA-HamedNeural"]:
            self._voice_ar_combo.addItem(v)
        self._voice_ar_combo.setCurrentText(self._settings.get("voice_ar", "ar-EG-ShakirNeural"))
        form.addRow("Voice (AR):", self._voice_ar_combo)

        self._wake_check = QCheckBox("Enable wake word")
        self._wake_check.setChecked(self._settings.get("wake_word_enabled", True))
        form.addRow("Wake word:", self._wake_check)

        self._theme_combo = QComboBox()
        self._theme_combo.addItems(["dark", "darker", "oled"])
        self._theme_combo.setCurrentText(self._settings.get("theme", "dark"))
        form.addRow("Theme:", self._theme_combo)

        self._fallback_check = QCheckBox("Use local LLM when offline")
        self._fallback_check.setChecked(self._settings.get("local_llm_fallback", True))
        form.addRow("Local fallback:", self._fallback_check)

        self._ollama_combo = QComboBox()
        self._ollama_combo.setEditable(True)
        for m in ["llama3.2:1b", "llama3.2", "llama3.1", "mistral", "phi3"]:
            self._ollama_combo.addItem(m)
        self._ollama_combo.setCurrentText(self._settings.get("ollama_model", "llama3.2"))
        form.addRow("Ollama model:", self._ollama_combo)

        # Ollama status indicator
        self._ollama_status = QLabel("checking…")
        self._ollama_status.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 11px;")
        form.addRow("Ollama status:", self._ollama_status)
        self._check_ollama_status()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save_and_accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _check_ollama_status(self):
        try:
            from core.local_llm import is_ollama_running
            import threading
            def _check():
                running = is_ollama_running()
                # Use QTimer.singleShot to update label from the main thread
                from PyQt6.QtCore import QTimer
                if running:
                    QTimer.singleShot(0, lambda: (
                        self._ollama_status.setText("Online ✓"),
                        self._ollama_status.setStyleSheet(f"color: {theme.SPEAKING}; font-size: 11px;"),
                    ))
                else:
                    QTimer.singleShot(0, lambda: (
                        self._ollama_status.setText("Offline — install from ollama.ai"),
                        self._ollama_status.setStyleSheet(f"color: {theme.ERROR}; font-size: 11px;"),
                    ))
            threading.Thread(target=_check, daemon=True).start()
        except Exception:
            pass

    def _save_and_accept(self):
        self._settings.update({
            "model": self._model_combo.currentText(),
            "tts_backend": self._tts_combo.currentText(),
            "voice_en": self._voice_en_combo.currentText(),
            "voice_ar": self._voice_ar_combo.currentText(),
            "wake_word_enabled": self._wake_check.isChecked(),
            "theme": self._theme_combo.currentText(),
            "local_llm_fallback": self._fallback_check.isChecked(),
            "ollama_model": self._ollama_combo.currentText(),
        })
        _save_settings(self._settings)
        self.accept()


# ──────────────────────────────────────────────────────────────────────────────
# Main overlay window
# ──────────────────────────────────────────────────────────────────────────────

class OverlayWindow(QWidget):
    text_submitted = pyqtSignal(str)

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
        self._history: list[tuple[str, str]] = []  # (role, text)

    def set_wake_listener(self, listener):
        self._wake_listener = listener
        self._setup_window()
        self._build_ui()
        self._setup_timers()
        self._apply_theme()

    # ------------------------------------------------------------------ #
    #  Window setup                                                        #
    # ------------------------------------------------------------------ #

    def _setup_window(self):
        # FramelessWindowHint keeps our custom look; removing Tool makes it
        # appear in the taskbar and respond to Alt+Tab like a real app.
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setWindowTitle("El Fager")
        self.setMinimumSize(480, 540)

        # Restore saved geometry or default to bottom-center
        settings = _load_settings()
        geom = settings.get("window_geometry")
        if geom and len(geom) == 4:
            self.setGeometry(*geom)
        else:
            self.resize(560, 700)
            screen = QApplication.primaryScreen().availableGeometry()
            self.move(
                (screen.width() - 560) // 2,
                screen.height() - 720,
            )

        self._drag_start = None
        self._drag_origin = None

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(0)

        self._card = QWidget(self)
        self._card.setObjectName("card")
        outer.addWidget(self._card)

        inner = QVBoxLayout(self._card)
        inner.setContentsMargins(16, 12, 16, 14)
        inner.setSpacing(8)

        inner.addLayout(self._build_header())

        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet(theme.SEPARATOR)
        inner.addWidget(sep)

        # ── Conversation history ──────────────────────────────────────
        self._history_scroll = QScrollArea()
        self._history_scroll.setWidgetResizable(True)
        self._history_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._history_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._history_scroll.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._history_scroll.setMinimumHeight(200)
        self._history_scroll.setStyleSheet(theme.SCROLL_AREA)

        self._history_container = QWidget()
        self._history_container.setStyleSheet("background: transparent;")
        self._history_layout = QVBoxLayout(self._history_container)
        self._history_layout.setContentsMargins(0, 4, 0, 4)
        self._history_layout.setSpacing(4)
        self._history_layout.addStretch()
        self._history_scroll.setWidget(self._history_container)
        inner.addWidget(self._history_scroll)

        # ── Active transcript ─────────────────────────────────────────
        self._transcript_label = QLabel("")
        self._transcript_label.setWordWrap(True)
        self._transcript_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._transcript_label.setStyleSheet(theme.TRANSCRIPT_LABEL)
        self._transcript_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self._transcript_label.setVisible(False)
        inner.addWidget(self._transcript_label)

        # ── Status bar ───────────────────────────────────────────────
        self._status_bar = QLabel("")
        self._status_bar.setStyleSheet(theme.STATUS_BAR)
        self._status_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_bar.setVisible(False)
        inner.addWidget(self._status_bar)

        # ── Separator ─────────────────────────────────────────────────
        sep2 = QWidget()
        sep2.setFixedHeight(1)
        sep2.setStyleSheet(theme.SEPARATOR)
        inner.addWidget(sep2)

        # ── Input ─────────────────────────────────────────────────────
        input_row = QHBoxLayout()
        input_row.setSpacing(6)

        self._text_input = QLineEdit()
        self._text_input.setPlaceholderText("Type here or just speak...")
        self._text_input.setStyleSheet(theme.TEXT_INPUT)
        self._text_input.returnPressed.connect(self._on_text_entered)
        self._text_input.installEventFilter(self)
        input_row.addWidget(self._text_input)
        inner.addLayout(input_row)

        # ── Quick action strip ────────────────────────────────────────
        actions_row = QHBoxLayout()
        actions_row.setSpacing(4)
        actions_row.addStretch()

        self._mic_btn = QPushButton("Mic")
        self._mic_btn.setToolTip("Mute/unmute mic")
        self._mic_btn.setStyleSheet(theme.BTN_GHOST)
        self._mic_btn.clicked.connect(self._toggle_mute)
        actions_row.addWidget(self._mic_btn)

        stop_btn = QPushButton("Stop")
        stop_btn.setToolTip("Stop speaking")
        stop_btn.setStyleSheet(theme.BTN_GHOST)
        stop_btn.clicked.connect(self._stop_tts)
        actions_row.addWidget(stop_btn)

        clear_btn = QPushButton("Clear")
        clear_btn.setToolTip("Clear conversation history")
        clear_btn.setStyleSheet(theme.BTN_GHOST)
        clear_btn.clicked.connect(self._clear_history)
        actions_row.addWidget(clear_btn)

        settings_btn = QPushButton("Settings")
        settings_btn.setToolTip("Settings")
        settings_btn.setStyleSheet(theme.BTN_GHOST)
        settings_btn.clicked.connect(self._open_settings)
        actions_row.addWidget(settings_btn)

        inner.addLayout(actions_row)

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)

        self._ring = RingCanvas(self._card)
        row.addWidget(self._ring)

        name_lbl = QLabel("EL FAGER")
        name_lbl.setStyleSheet(theme.HEADER_TITLE)
        row.addWidget(name_lbl)
        row.addStretch()

        self._status_label = QLabel("Ready")
        self._status_label.setStyleSheet(theme.STATUS_LABEL)
        row.addWidget(self._status_label)
        row.addSpacing(4)

        min_btn = QPushButton("─")
        min_btn.setFixedSize(22, 20)
        min_btn.setStyleSheet(theme.BTN_GHOST)
        min_btn.setToolTip("Hide")
        min_btn.clicked.connect(self._hide)
        row.addWidget(min_btn)

        minimize_btn = QPushButton("□")
        minimize_btn.setFixedSize(22, 20)
        minimize_btn.setStyleSheet(theme.BTN_GHOST)
        minimize_btn.setToolTip("Minimize")
        minimize_btn.clicked.connect(self.showMinimized)
        row.addWidget(minimize_btn)

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(22, 20)
        close_btn.setStyleSheet(theme.BTN_CLOSE)
        close_btn.setToolTip("Close")
        close_btn.clicked.connect(self._hide)
        row.addWidget(close_btn)

        return row

    def _apply_theme(self):
        settings = _load_settings()
        self._card.setStyleSheet(theme.card_style(settings.get("theme", "dark")))

    def _setup_timers(self):
        # Ring animation tick — only runs while a turn is in flight
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(30)
        self._anim_timer.timeout.connect(self._ring.tick)

        # Status bar polling every second (two tiny local JSON reads)
        self._status_poll_timer = QTimer(self)
        self._status_poll_timer.setInterval(1000)
        self._status_poll_timer.timeout.connect(self._update_status_bar)
        self._status_poll_timer.start()

    # ------------------------------------------------------------------ #
    #  Conversation history bubbles                                        #
    # ------------------------------------------------------------------ #

    def _add_bubble(self, role: str, text: str):
        from datetime import datetime
        self._history.append((role, text))
        if len(self._history) > _MAX_HISTORY:
            self._history.pop(0)
            # Rebuild all bubbles
            self._rebuild_bubbles()
            return
        ts = datetime.now().strftime("%H:%M")
        bubble = MessageBubble(role, text[:500], ts, self._history_container)
        # Insert before the trailing stretch
        count = self._history_layout.count()
        self._history_layout.insertWidget(count - 1, bubble)
        # Scroll to bottom
        QTimer.singleShot(50, self._scroll_to_bottom)

    def _rebuild_bubbles(self):
        # Remove all except stretch
        while self._history_layout.count() > 1:
            item = self._history_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for role, text in self._history:
            bubble = MessageBubble(role, text[:500], "", self._history_container)
            count = self._history_layout.count()
            self._history_layout.insertWidget(count - 1, bubble)
        QTimer.singleShot(50, self._scroll_to_bottom)

    def _scroll_to_bottom(self):
        sb = self._history_scroll.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _clear_history(self):
        self._history.clear()
        while self._history_layout.count() > 1:
            item = self._history_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    # ------------------------------------------------------------------ #
    #  Live status bar                                                     #
    # ------------------------------------------------------------------ #

    def _update_status_bar(self):
        indicators = []

        # Pomodoro
        try:
            pom_file = Path("data/pomodoro_active.json")
            if pom_file.exists():
                data = json.loads(pom_file.read_text(encoding="utf-8"))
                if data.get("active"):
                    from datetime import datetime
                    end_ts = data.get("end_time")
                    if end_ts:
                        end = datetime.fromisoformat(end_ts)
                        remaining = int((end - datetime.now()).total_seconds())
                        if remaining > 0:
                            m, s = divmod(remaining, 60)
                            label = data.get("label", "Focus")
                            indicators.append(f"⏱ {label} {m}:{s:02d}")
        except Exception:
            pass

        # Focus mode
        try:
            focus_file = Path("data/focus_mode.json")
            if focus_file.exists():
                data = json.loads(focus_file.read_text(encoding="utf-8"))
                if data.get("active"):
                    indicators.append("🔴 Focus ON")
        except Exception:
            pass

        # Offline / local LLM
        try:
            if getattr(self.brain, "_offline_mode", False):
                indicators.append("☁️ Offline")
        except Exception:
            pass

        if indicators:
            self._status_bar.setText("  ·  ".join(indicators))
            self._status_bar.setVisible(True)
        else:
            self._status_bar.setVisible(False)

    # ------------------------------------------------------------------ #
    #  Quick actions                                                       #
    # ------------------------------------------------------------------ #

    def _toggle_mute(self):
        self._mic_muted = not self._mic_muted
        self._mic_btn.setText("Muted" if self._mic_muted else "Mic")
        try:
            if self._mic_muted:
                self.voice_in.stop_recording()
            # Un-mute just happens naturally at next pipeline start
        except Exception:
            pass

    def _stop_tts(self):
        try:
            self.voice_out.stop()
        except Exception:
            pass

    def _open_settings(self):
        dlg = SettingsDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._apply_theme()
            settings = _load_settings()
            # Propagate model change to brain
            new_model = settings.get("model", "claude-sonnet-4-6")
            if hasattr(self.brain, "_model"):
                self.brain._model = new_model
            # Propagate TTS/voice changes to voice_out
            if hasattr(self.voice_out, "apply_settings"):
                self.voice_out.apply_settings(settings)
            # Propagate wake word toggle
            if self._wake_listener is not None and hasattr(self._wake_listener, "available"):
                should_run = settings.get("wake_word_enabled", True)
                if should_run and not getattr(self._wake_listener, "_running", False):
                    self._wake_listener.start()
                elif not should_run and getattr(self._wake_listener, "_running", False):
                    self._wake_listener.stop()

    # ------------------------------------------------------------------ #
    #  State management                                                    #
    # ------------------------------------------------------------------ #

    @pyqtSlot(str, str, str)
    def on_state_update(self, state: str, transcript: str, response: str):
        self._current_state = state
        self._ring.set_state_color(state)
        self._status_label.setStyleSheet(
            f"color: {theme.STATE_COLORS.get(state, theme.TEXT_SECONDARY)};"
            f" font-size: 11px; font-family: {theme.FONT};"
        )

        if state == "listening":
            self._status_label.setText("Listening...")
            self._transcript_label.setVisible(False)
            self._text_input.setEnabled(False)
            self._anim_timer.start()
            self._ring.start_spin()

        elif state == "processing":
            # Keep ring spinning during thinking; also starts it for text-mode
            # turns where the listening state is skipped entirely.
            self._anim_timer.start()
            self._ring.start_spin()
            self._status_label.setText("Thinking...")
            if transcript and transcript != "Transcribing...":
                self._transcript_label.setText(f'"{transcript}"')
                self._transcript_label.setVisible(True)
                self._add_bubble("user", transcript)
            else:
                self._transcript_label.setText(transcript)
                self._transcript_label.setVisible(bool(transcript))

        elif state == "speaking":
            self._anim_timer.stop()
            self._ring.stop_spin()
            self._status_label.setText("Speaking...")
            if transcript:
                self._transcript_label.setText(f'"{transcript}"')
                self._transcript_label.setVisible(True)
            if response:
                self._add_bubble("assistant", response)
                self._transcript_label.setVisible(False)

    @pyqtSlot(str)
    def on_error(self, message: str):
        self._current_state = "error"
        self._ring.set_state_color("error")
        self._anim_timer.stop()
        self._ring.stop_spin()
        self._status_label.setText("Error")
        self._status_label.setStyleSheet(
            f"color: {theme.ERROR}; font-size: 11px; font-family: {theme.FONT};"
        )
        self._transcript_label.setText(message)
        self._transcript_label.setVisible(True)
        self._text_input.setEnabled(True)
        self._text_input.setFocus()

    @pyqtSlot()
    def on_pipeline_done(self):
        self._text_input.setEnabled(True)
        if self._current_state == "speaking":
            self._text_input.clear()
            self._set_ready()
            QTimer.singleShot(800, self._auto_restart_listen)
        elif self._current_state == "listening":
            self._anim_timer.stop()
            self._ring.stop_spin()
            self._set_ready()

    def _set_ready(self):
        self._status_label.setText("Ready")
        self._status_label.setStyleSheet(theme.STATUS_LABEL)
        self._ring.set_state_color("idle")

    def _auto_restart_listen(self):
        if self.isVisible() and not (self._worker and self._worker.isRunning()):
            if not self._mic_muted:
                self._reset_ui()
                self._start_pipeline()

    # ------------------------------------------------------------------ #
    #  Toggle / show / hide                                               #
    # ------------------------------------------------------------------ #

    def toggle(self):
        if self.isVisible():
            if self._worker and self._worker.isRunning():
                self._hide()
            else:
                self._reset_ui()
                self._start_pipeline()
        else:
            self._show_and_start()

    def wake_word_activate(self):
        if self._worker and self._worker.isRunning():
            return
        if self._mic_muted:
            return
        self._reset_ui()
        self.show()
        self._fade_in()
        self._start_pipeline()

    def _show_and_start(self):
        if self._worker and self._worker.isRunning():
            return
        self._reset_ui()
        # Show immediately and start the mic in the same tick — the fade
        # animates in parallel, so launch-to-listening isn't gated on it.
        self.show()
        self._fade_in()
        if not self._mic_muted:
            self._start_pipeline()

    def _fade_in(self):
        self.setWindowOpacity(0.0)
        anim = QPropertyAnimation(self, b"windowOpacity")
        anim.setDuration(120)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        self._fade_anim = anim

    def _hide(self):
        self._anim_timer.stop()
        self._ring.stop_spin()
        if self._worker and self._worker.isRunning():
            self.voice_in.stop_recording()
            self.voice_out.stop()
            self._worker.quit()
            self._worker.wait(2000)
        self.hide()
        self._current_state = "idle"

    def _reset_ui(self):
        self._set_ready()
        self._transcript_label.setVisible(False)
        self._text_input.setEnabled(True)
        self._text_input.clear()

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
            self._worker.error.connect(lambda _: self._wake_listener.resume() if self._wake_listener else None)

        self._worker.start()

    def analyze_screen(self):
        if self._worker and self._worker.isRunning():
            return
        self._reset_ui()
        self.show()
        self._start_pipeline(text_input="what's on my screen")

    def query_memory(self):
        if self._worker and self._worker.isRunning():
            return
        self._reset_ui()
        self.show()
        self._start_pipeline(text_input="what do you know about me?")

    def run_briefing(self, prompt: str):
        if self._worker and self._worker.isRunning():
            return
        self._reset_ui()
        self.show()
        self._start_pipeline(text_input=prompt)

    def _on_text_entered(self):
        text = self._text_input.text().strip()
        if not text or (self._worker and self._worker.isRunning()):
            return
        self._text_input.setEnabled(False)
        self._start_pipeline(text_input=text)

    # ------------------------------------------------------------------ #
    #  Keyboard                                                            #
    # ------------------------------------------------------------------ #

    def eventFilter(self, obj, event):
        if obj is self._text_input and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                self._hide()
                return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Escape:
            self._hide()
        else:
            super().keyPressEvent(event)

    # ------------------------------------------------------------------ #
    #  Window dragging (frameless window moves by dragging the header)    #
    # ------------------------------------------------------------------ #

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.globalPosition().toPoint()
            self._drag_origin = self.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (
            event.buttons() == Qt.MouseButton.LeftButton
            and self._drag_start is not None
            and self._drag_origin is not None
        ):
            delta = event.globalPosition().toPoint() - self._drag_start
            self.move(self._drag_origin + delta)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_start = None
        self._drag_origin = None
        super().mouseReleaseEvent(event)

    # ------------------------------------------------------------------ #
    #  Close → hide to tray (real quit is via tray menu)                  #
    # ------------------------------------------------------------------ #

    def closeEvent(self, event):
        event.ignore()
        self._save_geometry()
        self.hide()

    def _save_geometry(self):
        settings = _load_settings()
        g = self.geometry()
        settings["window_geometry"] = [g.x(), g.y(), g.width(), g.height()]
        _save_settings(settings)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        p.fillRect(self.rect(), Qt.GlobalColor.transparent)
