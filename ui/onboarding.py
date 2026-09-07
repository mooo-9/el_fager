"""
El Fager — Onboarding.

Four steps with the orb present from frame one, changing hue as you move
through them: Name → voice calibration → skill permissions → wake-word test.
Continue gates on completion, and it ends with the assistant speaking rather
than with a tour.

Each step touches the real thing it claims to: the name is written to
profile.json (where the brain reads it), calibration records through
core.voice_in and transcribes what you actually said, and the wake-word test
listens on the real wake listener. Nothing here is a mime of a setup step.

The staging rule appears in step 3 without a toggle, because it does not have
one — anything that leaves the machine stages first, always.
"""

import json
import threading
from pathlib import Path

from PyQt6.QtCore import Qt, QUrl, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ui import theme, tokens
from ui.overlay import _load_settings, _save_settings
from ui.settings import Toggle
from core import atomic

_PROFILE = Path("profile.json")
_ORB_PAGE = Path(__file__).parent / "assets" / "cockpit_orb.html"

# The orb's hue carries the step, so progress is legible without reading.
_STEP_STATE = ("idle", "listening", "thinking", "speaking")
_TEST_LINE = "Good morning, El Fager."


def _mono(size: int, color: str, tracking: float = 1.2) -> str:
    return (
        f"color: {color}; font-family: {theme.FONT_MONO}; font-size: {size}px;"
        f" letter-spacing: {tracking}px; background: transparent; border: none;"
    )


def _title(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"color: {tokens.CK_TEXT_HI}; font-family: {theme.FONT};"
        f" font-size: 28px; font-weight: 500; background: transparent;"
    )
    return lbl


def _body(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setStyleSheet(
        f"color: {tokens.CK_TEXT_MID}; font-family: {theme.FONT};"
        f" font-size: 15px; background: transparent;"
    )
    return lbl


class OnboardingWindow(QWidget):
    """Four steps, gated. Ends by speaking, not by dismissing."""

    finished = pyqtSignal()
    calibrated = pyqtSignal(str)
    wake_heard = pyqtSignal()

    def __init__(self, voice_in=None, voice_out=None, wake_listener=None, parent=None):
        super().__init__(parent)
        self.voice_in = voice_in
        self.voice_out = voice_out
        self.wake_listener = wake_listener
        self._step = 0
        self._voice_locked = False
        self._wake_passed = False
        self._orb = None
        self._orb_ready = False
        self._build_ui()
        self.calibrated.connect(self._on_calibrated)
        self.wake_heard.connect(self._on_wake_heard)
        self._show_step(0)

    # ------------------------------------------------------------------ #

    def _build_ui(self):
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setWindowTitle("El Fager — Setup")
        self.setStyleSheet(f"background: {tokens.CK_VOID};")
        self.resize(900, 620)

        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)

        # the orb sits above the steps, present from frame one
        self._orb_host = QWidget()
        self._orb_host.setFixedHeight(230)
        self._orb_host.setStyleSheet(f"background: {tokens.CK_VOID};")
        orb_layout = QVBoxLayout(self._orb_host)
        orb_layout.setContentsMargins(0, 0, 0, 0)
        col.addWidget(self._orb_host)

        body = QWidget()
        body.setStyleSheet("background: transparent;")
        body_col = QVBoxLayout(body)
        body_col.setContentsMargins(64, 8, 64, 28)
        body_col.setSpacing(20)

        self._steps = QStackedWidget()
        self._steps.setStyleSheet("background: transparent;")
        self._steps.addWidget(self._step_name())
        self._steps.addWidget(self._step_voice())
        self._steps.addWidget(self._step_permissions())
        self._steps.addWidget(self._step_wake())
        body_col.addWidget(self._steps, 1)

        foot = QHBoxLayout()
        self._dots = QLabel("")
        self._dots.setStyleSheet(_mono(11, tokens.CK_TEXT_FAINT, 3))
        foot.addWidget(self._dots)
        foot.addStretch()
        self._continue = QPushButton("Continue")
        self._continue.setCursor(Qt.CursorShape.PointingHandCursor)
        self._continue.clicked.connect(self._advance)
        foot.addWidget(self._continue)
        body_col.addLayout(foot)
        col.addWidget(body, 1)

    # ── steps ─────────────────────────────────────────────────────────────

    def _step_name(self) -> QWidget:
        page = QWidget()
        page.setStyleSheet("background: transparent;")
        c = QVBoxLayout(page)
        c.setSpacing(14)
        c.addWidget(_title("What should I call you?"))
        c.addWidget(_body("It goes in your profile — I use it when I talk to you."))
        self._name = QLineEdit()
        self._name.setPlaceholderText("Mo")
        self._name.setFixedWidth(320)
        self._name.setStyleSheet(
            f"QLineEdit {{ background: {tokens.CK_CARD}; color: {tokens.CK_TEXT_HI};"
            f" border: 1px solid {tokens.CK_HAIRLINE}; border-radius: {tokens.R2}px;"
            f" padding: 10px 14px; font-family: {theme.FONT}; font-size: 15px; }}"
            f"QLineEdit:focus {{ border-color: {tokens.CK_STATE['listening']}; }}"
        )
        self._name.setText(self._existing_name())
        self._name.textChanged.connect(lambda _: self._paint_gate())
        c.addWidget(self._name)
        c.addStretch()
        return page

    def _step_voice(self) -> QWidget:
        page = QWidget()
        page.setStyleSheet("background: transparent;")
        c = QVBoxLayout(page)
        c.setSpacing(14)
        c.addWidget(_title("Say this, in both languages."))
        line = QLabel(_TEST_LINE)
        line.setStyleSheet(
            f"color: {tokens.CK_TEXT_HI}; font-family: {theme.FONT};"
            f" font-size: 21px; background: {tokens.CK_CARD};"
            f" border: 1px solid {tokens.CK_HAIRLINE}; border-radius: {tokens.R3}px;"
            f" padding: 16px 20px;"
        )
        line.setWordWrap(True)
        c.addWidget(line)

        row = QHBoxLayout()
        self._listen_btn = QPushButton("Listen")
        self._listen_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._listen_btn.clicked.connect(self._calibrate)
        self._style_button(self._listen_btn)
        row.addWidget(self._listen_btn)
        self._voice_receipt = QLabel("")
        self._voice_receipt.setStyleSheet(_mono(11, tokens.OK, 1.4))
        row.addWidget(self._voice_receipt)
        row.addStretch()
        c.addLayout(row)
        c.addStretch()
        return page

    def _step_permissions(self) -> QWidget:
        page = QWidget()
        page.setStyleSheet("background: transparent;")
        c = QVBoxLayout(page)
        c.setSpacing(14)
        c.addWidget(_title("What may I touch?"))
        settings = _load_settings()

        self._perm_wake = Toggle(settings.get("wake_word_enabled", True))
        self._perm_wake.toggled.connect(
            lambda v: self._save_setting("wake_word_enabled", v))
        c.addWidget(self._perm_row("Wake word", "LISTEN FOR “HEY FAGER”", self._perm_wake))

        cues = settings.get("sound_cues", True)
        self._perm_cues = Toggle(cues if isinstance(cues, bool) else True)
        self._perm_cues.toggled.connect(lambda v: self._save_setting("sound_cues", v))
        c.addWidget(self._perm_row("Sound cues", "SPEAK IN TONES, NOT JUST WORDS",
                                   self._perm_cues))

        # the staging rule has no off switch
        rule = QLabel(
            "Anything that leaves this machine — a message, a mail, an "
            "invite — is staged for you to look at first. That one has no "
            "off switch."
        )
        rule.setWordWrap(True)
        # A wrapped label only gets its full height if the layout is told to
        # ask for it; without this the rule truncated mid-sentence.
        policy = rule.sizePolicy()
        policy.setHeightForWidth(True)
        policy.setVerticalPolicy(QSizePolicy.Policy.MinimumExpanding)
        rule.setSizePolicy(policy)
        rule.setMinimumHeight(84)
        rule.setStyleSheet(
            f"color: {tokens.CK_TEXT_MID}; font-family: {theme.FONT}; font-size: 14px;"
            f" background: {tokens.CK_CARD}; border-radius: {tokens.R3}px;"
            f" border-left: 2px solid {tokens.CK_STATE['speaking']}; padding: 14px 16px;"
        )
        c.addWidget(rule)
        c.addStretch()
        return page

    def _step_wake(self) -> QWidget:
        page = QWidget()
        page.setStyleSheet("background: transparent;")
        c = QVBoxLayout(page)
        c.setSpacing(14)
        c.addWidget(_title("Now call me."))
        c.addWidget(_body("Say “hey Fager” out loud. I'll answer when I hear it."))
        row = QHBoxLayout()
        self._wake_receipt = QLabel("WAITING…")
        self._wake_receipt.setStyleSheet(_mono(11, tokens.CK_TEXT_LOW, 1.4))
        row.addWidget(self._wake_receipt)
        row.addStretch()
        skip = QPushButton("Skip — no mic right now")
        skip.setCursor(Qt.CursorShape.PointingHandCursor)
        skip.setStyleSheet(
            f"QPushButton {{ {_mono(10, tokens.CK_TEXT_LOW)} padding: 6px 10px; }}"
            f"QPushButton:hover {{ color: {tokens.CK_TEXT_HI}; }}"
        )
        skip.clicked.connect(self._skip_wake)
        row.addWidget(skip)
        c.addLayout(row)
        c.addStretch()
        return page

    def _perm_row(self, name: str, note: str, control: QWidget) -> QWidget:
        wrap = QWidget()
        wrap.setStyleSheet("background: transparent;")
        line = QHBoxLayout(wrap)
        line.setContentsMargins(0, 0, 0, 0)
        text = QVBoxLayout()
        text.setSpacing(3)
        label = QLabel(name)
        label.setStyleSheet(
            f"color: {tokens.CK_TEXT_HI}; font-family: {theme.FONT};"
            f" font-size: 15px; background: transparent;")
        text.addWidget(label)
        text.addWidget(QLabel(note, styleSheet=_mono(10, tokens.CK_TEXT_FAINT)))
        line.addLayout(text, 1)
        line.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)
        return wrap

    # ── behaviour ─────────────────────────────────────────────────────────

    def _existing_name(self) -> str:
        try:
            return json.loads(_PROFILE.read_text(encoding="utf-8")).get("name", "")
        except Exception:
            return ""

    def _save_name(self):
        name = self._name.text().strip()
        try:
            profile = json.loads(_PROFILE.read_text(encoding="utf-8"))
            profile["name"] = name
            atomic.write(_PROFILE,
                json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    def _save_setting(self, key: str, value):
        settings = _load_settings()
        settings[key] = value
        _save_settings(settings)

    def _calibrate(self):
        """Record and transcribe for real — a mimed check would prove nothing."""
        self._listen_btn.setEnabled(False)
        self._voice_receipt.setText("LISTENING…")
        self._voice_receipt.setStyleSheet(_mono(11, tokens.CK_STATE["listening"], 1.4))

        def run():
            heard = ""
            try:
                audio = self.voice_in.record_audio()
                if audio is not None:
                    # Coerced: anything but a str here would raise on emit and
                    # strand the step with its button disabled.
                    heard = str(self.voice_in.transcribe(audio) or "")
            except Exception:
                heard = ""
            self.calibrated.emit(heard)

        threading.Thread(target=run, daemon=True).start()

    @pyqtSlot(str)
    def _on_calibrated(self, heard: str):
        self._listen_btn.setEnabled(True)
        if heard.strip():
            self._voice_locked = True
            self._voice_receipt.setText("VOICE LOCKED")
            self._voice_receipt.setStyleSheet(_mono(11, tokens.OK, 1.4))
        else:
            self._voice_receipt.setText("DIDN'T CATCH THAT — TRY AGAIN")
            self._voice_receipt.setStyleSheet(_mono(11, tokens.CK_STATE["error"], 1.4))
        self._paint_gate()

    def _arm_wake_test(self):
        listener = self.wake_listener
        if listener is None:
            return
        try:
            listener.on_detected = self.wake_heard.emit
            if not getattr(listener, "_running", False):
                listener.start()
        except Exception:
            pass

    @pyqtSlot()
    def _on_wake_heard(self):
        self._wake_passed = True
        self._wake_receipt.setText("HEARD YOU")
        self._wake_receipt.setStyleSheet(_mono(11, tokens.OK, 1.4))
        self._paint_gate()

    def _skip_wake(self):
        self._wake_passed = True
        self._wake_receipt.setText("SKIPPED — TEST IT ANY TIME FROM SETTINGS")
        self._wake_receipt.setStyleSheet(_mono(11, tokens.CK_TEXT_LOW, 1.4))
        self._paint_gate()

    def can_continue(self) -> bool:
        """Continue gates on the step actually being done."""
        if self._step == 0:
            return bool(self._name.text().strip())
        if self._step == 1:
            return self._voice_locked
        if self._step == 3:
            return self._wake_passed
        return True

    def _paint_gate(self):
        ready = self.can_continue()
        self._continue.setEnabled(ready)
        self._continue.setText("Finish" if self._step == 3 else "Continue")
        self._continue.setStyleSheet(
            f"QPushButton {{ color: {tokens.CK_TEXT_ON_FILL if ready else tokens.CK_TEXT_LOW};"
            f" background: {tokens.CK_STATE['listening'] if ready else tokens.CK_CARD};"
            f" border: none; border-radius: {tokens.R2}px; padding: 9px 22px;"
            f" font-family: {theme.FONT}; font-size: 14px; font-weight: 500; }}"
        )
        self._dots.setText(" ".join("•" if i == self._step else "·" for i in range(4)))

    def _advance(self):
        if not self.can_continue():
            return
        if self._step == 0:
            self._save_name()
        if self._step == 3:
            self._finish()
            return
        self._show_step(self._step + 1)

    def _show_step(self, index: int):
        self._step = index
        self._steps.setCurrentIndex(index)
        self._push_orb(_STEP_STATE[index])
        if index == 3:
            self._arm_wake_test()
        self._paint_gate()

    def _finish(self):
        """It ends with the assistant speaking, not with a tour."""
        try:
            if self.voice_out is not None:
                self.voice_out.speak("At your service.")
        except Exception:
            pass
        self.finished.emit()
        self.hide()

    # ── the orb ───────────────────────────────────────────────────────────

    def _ensure_orb(self):
        if self._orb is not None:
            return
        from PyQt6.QtWebEngineWidgets import QWebEngineView

        self._orb = QWebEngineView()
        self._orb.setStyleSheet(f"background: {tokens.CK_VOID};")
        self._orb.loadFinished.connect(self._on_orb_loaded)
        self._orb.load(QUrl.fromLocalFile(str(_ORB_PAGE.resolve())))
        self._orb_host.layout().addWidget(self._orb)

    def _on_orb_loaded(self, ok: bool):
        self._orb_ready = bool(ok)
        self._push_orb(_STEP_STATE[self._step])

    def _push_orb(self, state: str):
        if self._orb and self._orb_ready:
            self._orb.page().runJavaScript(
                f"window.orb && window.orb.setState('{state}')")

    def open(self):
        self._ensure_orb()
        screen = QApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            self.move(area.center().x() - self.width() // 2,
                      area.center().y() - self.height() // 2)
        self.show()
        self.raise_()
        self.activateWindow()

    def _style_button(self, btn: QPushButton):
        btn.setStyleSheet(
            f"QPushButton {{ color: {tokens.CK_TEXT_HI}; background: {tokens.CK_CARD};"
            f" border: 1px solid {tokens.CK_HAIRLINE}; border-radius: {tokens.R2}px;"
            f" padding: 8px 18px; font-family: {theme.FONT}; font-size: 14px; }}"
            f"QPushButton:hover {{ border-color: "
            f"{tokens.rgba(tokens.CK_STATE['listening'], 0.45)}; }}"
            f"QPushButton:disabled {{ color: {tokens.CK_TEXT_LOW}; }}"
        )
