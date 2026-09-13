"""
El Fager — the Cockpit (the design's primary surface).

Full-screen void with the Ember at its centre, corner readouts on
state-tinted hairlines, and one exchange spoken across the stage. The orb is
the only web-rendered thing in El Fager: ui/assets/cockpit_orb.html carries
the canonical tick() from "El Fager Cockpit v2.dc.html", and this window
drives it through window.orb.

Per the implementation tiers, QWebEngine is lazy and single-instance — the
view is built the first time the cockpit opens and its render loop is parked
whenever the window hides, so a cockpit in the tray costs no GPU. It is never
on the Ctrl+Space path; that surface stays native (ui/overlay.py).

Readouts come from data the app already has — the clock, and the Command
Center's local cache — so opening the cockpit never waits on the network.
"""

import calendar
import json
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QUrl, Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import (
    QApplication,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from core import progress, prose, staging
from ui import theme, tokens
from ui.overlay import _load_settings

_CACHE = Path("data/command_center_cache.json")
_ORB_PAGE = Path(__file__).parent / "assets" / "cockpit_orb.html"

# The three attention states, as readout opacity. Ambient is the orb alone;
# during an exchange the words own the stage and the readouts recede.
_ATTENTION = {"ambient": 0.0, "ready": 1.0, "exchange": 0.12}

# Settings → System offers 30s / 60s / 2m; 60 is the design's default.
_AMBIENT_DELAYS = {"30s": 30, "60s": 60, "2m": 120}
_AMBIENT_DEFAULT = 60

# Only what this surface actually honours — a map that lists a key the
# cockpit ignores is worse than no map.
_KEYS = (
    ("SPACE", "talk to it"),
    ("ENTER", "confirm what's staged"),
    ("ESC", "cancel the staged action, then close"),
    ("L", "open the trust ledger"),
    ("?", "this map"),
)

# The cockpit runs its own state names — the pipeline's "processing" is the
# design's "thinking", which is what the orb's palette is keyed to.
_ORB_STATE = {
    "idle": "idle",
    "listening": "listening",
    "processing": "thinking",
    "speaking": "speaking",
    "error": "error",
    # Talked over: the orb snaps to listening, because Mo has the floor.
    "interrupted": "listening",
}
_LABELS = {
    "idle": "IDLE",
    "listening": "LISTENING",
    "processing": "WORKING",
    "speaking": "SPEAKING",
    "error": "ERROR",
    "interrupted": "INTERRUPTED",
}


def _cached(card_id: str) -> str:
    """First meaningful line of a Command Center card, or an em dash."""
    try:
        data = json.loads(_CACHE.read_text(encoding="utf-8"))
        text = data.get("cards", {}).get(card_id, {}).get("text", "")
        for line in text.splitlines():
            if line.strip():
                return line.strip()
    except Exception:
        pass
    return "—"


def _cached_lines(card_id: str, limit: int) -> list[str]:
    """Up to `limit` meaningful lines of a card — the rails show a list where
    the old corner readouts showed one line."""
    try:
        data = json.loads(_CACHE.read_text(encoding="utf-8"))
        text = data.get("cards", {}).get(card_id, {}).get("text", "")
        return [l.strip() for l in text.splitlines() if l.strip()][:limit]
    except Exception:
        return []


def _mono(size: int, color: str, tracking: float = 1.4) -> str:
    return (
        f"color: {color}; font-family: {theme.FONT_MONO}; font-size: {size}px;"
        f" letter-spacing: {tracking}px; background: transparent;"
    )


class _Readout(QWidget):
    """A corner readout: kicker over value, on a state-tinted hairline."""

    def __init__(self, kicker: str, align_right: bool = False, parent=None):
        super().__init__(parent)
        col = QVBoxLayout(self)
        col.setContentsMargins(14, 10, 14, 10)
        col.setSpacing(4)
        self._align = (
            Qt.AlignmentFlag.AlignRight if align_right else Qt.AlignmentFlag.AlignLeft
        )

        self._kicker = QLabel(kicker)
        self._kicker.setStyleSheet(_mono(10, tokens.CK_TEXT_LOW))
        self._kicker.setAlignment(self._align)
        col.addWidget(self._kicker)

        self._value = QLabel("—")
        self._value.setWordWrap(True)
        self._value.setMaximumWidth(280)
        self._value.setStyleSheet(
            f"color: {tokens.CK_TEXT_HI}; font-family: {theme.FONT};"
            f" font-size: 15px; background: transparent;"
        )
        self._value.setAlignment(self._align)
        col.addWidget(self._value)

    def set_value(self, text: str):
        self._value.setText(text)

    def set_tint(self, color: str):
        self.setStyleSheet(
            f"_Readout {{ border-left: 1px solid {tokens.rgba(color, 0.35)}; }}"
        )

    def set_attention(self, opacity: float):
        """Readouts recede when the words matter more, and go entirely when
        the cockpit falls to ambient. An opacity effect rather than a hide,
        so nothing reflows as the stage changes."""
        effect = self.graphicsEffect()
        if not isinstance(effect, QGraphicsOpacityEffect):
            effect = QGraphicsOpacityEffect(self)
            self.setGraphicsEffect(effect)
        effect.setOpacity(opacity)


class _StateChip(QWidget):
    """Top-centre state mark: a state-tinted dot beside the state's name."""

    def __init__(self, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self._dot = QLabel("●")
        self._dot.setStyleSheet(_mono(9, tokens.CK_STATE["idle"], 0))
        row.addWidget(self._dot)
        self.label = QLabel("IDLE")
        self.label.setStyleSheet(_mono(11, tokens.CK_TEXT_MID, 2.6))
        row.addWidget(self.label)

    def set_state(self, text: str, color: str):
        self.label.setText(text)
        self._dot.setStyleSheet(_mono(9, color, 0))


class _MonthCalendar(QWidget):
    """The left rail's month grid. Today is the only lit cell — the rail is a
    place to find yourself in the month, not a calendar to work in."""

    def __init__(self, parent=None):
        super().__init__(parent)
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(8)

        self._title = QLabel("")
        self._title.setStyleSheet(_mono(11, tokens.CK_TEXT_MID, 2.4))
        col.addWidget(self._title)

        self._grid = QGridLayout()
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(2)
        self._grid.setVerticalSpacing(3)
        col.addLayout(self._grid)
        self.refresh()

    def refresh(self):
        while self._grid.count():
            item = self._grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)

        today = datetime.now()
        self._title.setText(today.strftime("%B %Y").upper())
        for c, name in enumerate(("M", "T", "W", "T", "F", "S", "S")):
            head = QLabel(name)
            head.setAlignment(Qt.AlignmentFlag.AlignCenter)
            head.setStyleSheet(_mono(9, tokens.CK_TEXT_FAINT, 0.6))
            self._grid.addWidget(head, 0, c)

        for r, week in enumerate(calendar.monthcalendar(today.year, today.month), start=1):
            for c, day in enumerate(week):
                if day == 0:
                    continue
                cell = QLabel(str(day))
                cell.setAlignment(Qt.AlignmentFlag.AlignCenter)
                cell.setFixedHeight(20)
                if day == today.day:
                    cell.setStyleSheet(
                        f"{_mono(10, tokens.CK_TEXT_ON_FILL, 0)}"
                        f" background: {tokens.EMBER}; border-radius: 4px;"
                    )
                else:
                    cell.setStyleSheet(_mono(10, tokens.CK_TEXT_LOW, 0))
                self._grid.addWidget(cell, r, c)


class _RailRow(QWidget):
    """One automation: what it is on the left, when/where it runs on the
    right. The tag is mono so the column of them lines up."""

    def __init__(self, label: str, tag: str, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 5, 0, 5)
        row.setSpacing(10)
        dot = QLabel("▪")
        dot.setStyleSheet(_mono(8, tokens.rgba(tokens.EMBER, 0.55), 0))
        row.addWidget(dot, 0, Qt.AlignmentFlag.AlignTop)
        name = QLabel(label)
        name.setWordWrap(True)
        name.setStyleSheet(
            f"color: {tokens.CK_TEXT_MID}; font-family: {theme.FONT};"
            f" font-size: 12px; background: transparent;"
        )
        row.addWidget(name, 1)
        if tag:
            chip = QLabel(tag)
            chip.setStyleSheet(_mono(9, tokens.CK_TEXT_FAINT, 0.8))
            row.addWidget(chip, 0, Qt.AlignmentFlag.AlignTop)


def _wrapped(text: str, style: str) -> QLabel:
    """A word-wrapped label that tells its layout how tall it is — wrapped
    labels clip otherwise, the trap this project has hit before."""
    label = QLabel(text)
    label.setWordWrap(True)
    label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
    policy = label.sizePolicy()
    policy.setHeightForWidth(True)
    label.setSizePolicy(policy)
    label.setStyleSheet(style)
    return label


class _Panel(QWidget):
    """A rail card: hairline border on the void, a mono kicker at the top."""

    def __init__(self, kicker: str, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            f"_Panel {{ background: {tokens.rgba(tokens.CK_PANEL, 0.72)};"
            f" border: 1px solid {tokens.CK_HAIRLINE};"
            f" border-radius: {tokens.R2}px; }}"
        )
        self.column = QVBoxLayout(self)
        self.column.setContentsMargins(16, 14, 16, 14)
        self.column.setSpacing(8)
        if kicker:
            head = QLabel(kicker)
            head.setStyleSheet(_mono(9, tokens.CK_TEXT_LOW, 2.0))
            self.column.addWidget(head)


class CockpitWindow(QWidget):
    """Full-screen primary surface. Same integration contract as the overlay."""

    staged_changed = pyqtSignal()
    progress_changed = pyqtSignal()
    # The stage's view pill. main.py owns the Command Center for the same
    # reason it owns the Cockpit — both are lazy and single-instance.
    knowledge_requested = pyqtSignal()

    def __init__(self, voice_in, brain, voice_out, memory):
        super().__init__()
        self.voice_in = voice_in
        self.brain = brain
        self.voice_out = voice_out
        self.memory = memory
        self._worker = None
        self._wake_listener = None
        self._current_state = "idle"
        self._attention = "ready"
        self._orb = None            # QWebEngineView, built on first open
        self._orb_ready = False
        # Every exchange this session as [heard, answer, interrupted, time],
        # stacked in the TRANSCRIPT panel. Memory-only and kept whole until the
        # Cockpit closes — the ledger is the durable record.
        self._exchanges: list = []

    def set_wake_listener(self, listener):
        self._wake_listener = listener
        self._setup_window()
        self._build_ui()
        self._staged_cb = self.staged_changed.emit
        staging.subscribe(self._staged_cb)
        self.staged_changed.connect(self._refresh_staged)
        self._progress_cb = self.progress_changed.emit
        progress.subscribe(self._progress_cb)
        self.progress_changed.connect(self._refresh_steps)
        self._clock = QTimer(self)
        self._clock.setInterval(1000)
        self._clock.timeout.connect(self._tick_clock)
        # Ambient: after the configured silence the readouts fade out and the
        # orb rests. Single-shot, restarted by anything that counts as life.
        self._ambient_timer = QTimer(self)
        self._ambient_timer.setSingleShot(True)
        self._ambient_timer.timeout.connect(self._go_ambient)
        self._paint_state("idle")
        self._set_attention("ready")

    # ------------------------------------------------------------------ #
    #  Window                                                              #
    # ------------------------------------------------------------------ #

    def _setup_window(self):
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setWindowTitle("El Fager — Cockpit")
        self.setStyleSheet(f"background: {tokens.CK_VOID};")
        screen = QApplication.primaryScreen()
        if screen is not None:
            self.setGeometry(screen.geometry())

    def _build_ui(self):
        # StackAll puts the native chrome over the orb without either one
        # clipping the other.
        self._stack = QStackedLayout(self)
        self._stack.setStackingMode(QStackedLayout.StackingMode.StackAll)
        self._stack.setContentsMargins(0, 0, 0, 0)

        self._orb_host = QWidget()
        self._orb_host.setStyleSheet(f"background: {tokens.CK_VOID};")
        host_layout = QVBoxLayout(self._orb_host)
        host_layout.setContentsMargins(0, 0, 0, 0)
        self._stack.addWidget(self._orb_host)

        chrome = QWidget()
        chrome.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        chrome.setStyleSheet("background: transparent;")
        self._stack.addWidget(chrome)
        self._stack.setCurrentWidget(chrome)

        # Three columns on the void: the day on the left, the exchange in the
        # middle over the orb, what it runs for you on the right. The rails
        # are fixed so the centre stage never moves as their content changes.
        outer = QHBoxLayout(chrome)
        outer.setContentsMargins(40, 32, 40, 26)
        outer.setSpacing(30)
        outer.addWidget(self._build_left_rail(), 0)

        centre = QWidget()
        centre.setStyleSheet("background: transparent;")
        grid = QVBoxLayout(centre)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(0)
        outer.addWidget(centre, 1)

        self._state_chip = _StateChip()
        chip_row = QHBoxLayout()
        chip_row.addStretch()
        chip_row.addWidget(self._state_chip)
        chip_row.addStretch()
        grid.addLayout(chip_row)
        grid.addStretch()

        # The words of an exchange live only in the TRANSCRIPT panel on the
        # right; the sphere keeps the stage. What stays here is a notice for
        # a turn that went wrong ("Nothing heard"), which is not a transcript.
        self._notice = QLabel("")
        self._notice.setWordWrap(True)
        self._notice.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._notice.setMaximumWidth(620)
        self._notice.setStyleSheet(
            f"color: {tokens.CK_TEXT_MID}; font-family: {theme.FONT};"
            f" font-size: 15px; background: transparent;"
        )
        # A data moment materialises beside the notice when the turn touched
        # something worth seeing, and leaves with the exchange.
        self._moment = QWidget()
        self._moment.setStyleSheet("background: transparent;")
        self._moment_layout = QVBoxLayout(self._moment)
        self._moment_layout.setContentsMargins(24, 0, 0, 0)
        self._moment_layout.setSpacing(6)
        self._moment.setVisible(False)

        answer_row = QHBoxLayout()
        answer_row.addStretch()
        answer_row.addWidget(self._notice)
        answer_row.addWidget(self._moment, 0, Qt.AlignmentFlag.AlignVCenter)
        answer_row.addStretch()
        grid.addLayout(answer_row)
        grid.addSpacing(20)

        # step ledger — one line per tool the turn is running
        self._steps_box = QWidget()
        self._steps_box.setStyleSheet("background: transparent;")
        self._steps_layout = QVBoxLayout(self._steps_box)
        self._steps_layout.setContentsMargins(0, 12, 0, 12)
        self._steps_layout.setSpacing(7)
        self._steps_box.setVisible(False)
        steps_row = QHBoxLayout()
        steps_row.addStretch()
        steps_row.addWidget(self._steps_box)
        steps_row.addStretch()
        grid.addLayout(steps_row)
        # the armed action anchors just above the bottom bar, never clipped
        grid.addStretch()

        self._staged = QLabel("")
        self._staged.setWordWrap(True)
        self._staged.setMaximumWidth(620)
        self._staged.setVisible(False)
        staged_row = QHBoxLayout()
        staged_row.addStretch()
        staged_row.addWidget(self._staged)
        staged_row.addStretch()
        grid.addLayout(staged_row)
        grid.addSpacing(24)

        # Under the stage: the pill naming what the stage is currently showing.
        self._view_pill = QPushButton("KNOWLEDGE VIEW")
        self._view_pill.setCursor(Qt.CursorShape.PointingHandCursor)
        self._view_pill.setStyleSheet(
            f"QPushButton {{ {_mono(10, tokens.CK_TEXT_MID, 2.2)}"
            f" background: {tokens.rgba(tokens.CK_CHIP, 0.85)};"
            f" border: 1px solid {tokens.rgba(tokens.EMBER, 0.25)};"
            f" border-radius: {tokens.R_PILL}px; padding: 7px 20px; }}"
            f"QPushButton:hover {{ color: {tokens.CK_TEXT_HI};"
            f" border-color: {tokens.rgba(tokens.EMBER, 0.55)}; }}"
        )
        self._view_pill.clicked.connect(self._open_knowledge)
        pill_row = QHBoxLayout()
        pill_row.addStretch()
        pill_row.addWidget(self._view_pill)
        pill_row.addStretch()
        grid.addLayout(pill_row)
        grid.addSpacing(18)

        # Tests and the state machine both read _state_label; it *is* the
        # chip's label, so the state is named once on screen, not twice.
        self._state_label = self._state_chip.label

        # the ledger lives on the bottom bar, per the design
        self._ledger_btn = QPushButton("LEDGER")
        self._ledger_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._ledger_btn.setStyleSheet(
            f"QPushButton {{ {_mono(10, tokens.CK_TEXT_LOW)}"
            f" border: 1px solid {tokens.rgba('#FFFFFF', 0.10)};"
            f" border-radius: 6px; padding: 5px 12px; }}"
            f"QPushButton:hover {{ color: {tokens.CK_TEXT_HI};"
            f" border-color: {tokens.rgba(tokens.CK_STATE['listening'], 0.40)}; }}"
        )
        self._ledger_btn.clicked.connect(self.open_ledger)
        ledger_row = QHBoxLayout()
        ledger_row.addStretch()
        ledger_row.addWidget(self._ledger_btn)
        ledger_row.addStretch()
        grid.addLayout(ledger_row)

        hint = QLabel("ESC CLOSE   ·   SPACE TALK   ·   ?  KEYS")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet(_mono(10, tokens.CK_TEXT_FAINT))
        grid.addWidget(hint)

        outer.addWidget(self._build_right_rail(), 0)
        self._keymap = self._build_keymap(chrome)

    # ── Rails ─────────────────────────────────────────────────────────────

    def _build_left_rail(self) -> QWidget:
        """The day: the clock, the month, what is next, what is on today."""
        rail = QWidget()
        rail.setFixedWidth(318)
        rail.setStyleSheet("background: transparent;")
        col = QVBoxLayout(rail)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(18)

        self._r_time = _Readout("TIME")
        col.addWidget(self._r_time)

        cal_panel = _Panel("")
        self._calendar = _MonthCalendar()
        cal_panel.column.addWidget(self._calendar)
        col.addWidget(cal_panel)

        self._r_next = _Readout("NEXT")
        col.addWidget(self._r_next)

        today_panel = _Panel("TODAY")
        self._today_list = QVBoxLayout()
        self._today_list.setContentsMargins(0, 0, 0, 0)
        self._today_list.setSpacing(0)
        today_panel.column.addLayout(self._today_list)
        col.addWidget(today_panel)

        # _r_today stays alive off-stage: the readout is what the ambient
        # fade and the tests drive, while the panel above is what you read.
        self._r_today = _Readout("TODAY")
        self._r_today.setVisible(False)
        col.addWidget(self._r_today)

        col.addStretch()
        return rail

    def _build_right_rail(self) -> QWidget:
        """What it runs for you, and what it just said."""
        rail = QWidget()
        rail.setFixedWidth(400)
        rail.setStyleSheet("background: transparent;")
        col = QVBoxLayout(rail)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(16)

        auto = _Panel("AUTOMATIONS")
        self._auto_list = QVBoxLayout()
        self._auto_list.setContentsMargins(0, 2, 0, 2)
        self._auto_list.setSpacing(0)
        auto.column.addLayout(self._auto_list)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self._skills_btn = QPushButton("SKILLS")
        self._skills_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._skills_btn.setStyleSheet(
            f"QPushButton {{ {_mono(9, tokens.CK_TEXT_LOW, 1.6)}"
            f" border: 1px solid {tokens.rgba('#FFFFFF', 0.10)};"
            f" border-radius: 6px; padding: 6px 14px; }}"
            f"QPushButton:hover {{ color: {tokens.CK_TEXT_HI}; }}"
        )
        self._skills_btn.clicked.connect(self.open_ledger)
        buttons.addWidget(self._skills_btn)
        buttons.addStretch()
        self._talk_btn = QPushButton("+  ASK IT")
        self._talk_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._talk_btn.setStyleSheet(
            f"QPushButton {{ {_mono(9, tokens.CK_TEXT_ON_FILL, 1.6)}"
            f" background: {tokens.EMBER}; border: none;"
            f" border-radius: 6px; padding: 6px 16px; }}"
            f"QPushButton:hover {{ background: {tokens.EMBER_BRIGHT}; }}"
        )
        self._talk_btn.clicked.connect(self._start_pipeline)
        buttons.addWidget(self._talk_btn)
        auto.column.addLayout(buttons)
        # The count belongs against the list it counts, not adrift at the foot
        # of the rail — it reads as a caption on the panel above it.
        self._r_skills = _Readout("SKILLS ONLINE", align_right=True)
        auto.column.addWidget(self._r_skills)
        col.addWidget(auto)

        # The conversation takes the rest of the rail: every exchange this
        # session stacked in one scroll, newest last, the way the reel lays
        # out its chat. An answer is set as labelled sections rather than one
        # block — the model reaches for "Academic:" style headings on a
        # summary, and reading that structure beats a wall of prose.
        reading = _Panel("TRANSCRIPT")
        self._reading_panel = reading
        self._reading_box = QWidget()
        self._reading_box.setStyleSheet("background: transparent;")
        self._reading_layout = QVBoxLayout(self._reading_box)
        self._reading_layout.setContentsMargins(0, 4, 10, 4)
        self._reading_layout.setSpacing(0)
        self._reading_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._reading_scroll = QScrollArea()
        self._reading_scroll.setWidgetResizable(True)
        self._reading_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._reading_scroll.setStyleSheet(theme.SCROLL_AREA)
        self._reading_scroll.viewport().setStyleSheet("background: transparent;")
        self._reading_scroll.setWidget(self._reading_box)
        reading.column.addWidget(self._reading_scroll, 1)

        # The reel's voice bar: who you are talking to, or what it is doing
        # right now. Clicking it does what Space does.
        self._voice_bar = QPushButton()
        self._voice_bar.setCursor(Qt.CursorShape.PointingHandCursor)
        self._voice_bar.clicked.connect(lambda _c=False: self._start_pipeline())
        reading.column.addWidget(self._voice_bar)
        col.addWidget(reading, 1)

        # The receipt ledger and the skills count close the rail out.
        self._receipts_box = QWidget()
        self._receipts_box.setStyleSheet("background: transparent;")
        self._receipts_layout = QVBoxLayout(self._receipts_box)
        self._receipts_layout.setContentsMargins(0, 0, 0, 0)
        self._receipts_layout.setSpacing(3)
        self._receipts_box.setVisible(False)
        col.addWidget(self._receipts_box)
        return rail

    def _open_knowledge(self):
        """The view pill: the Command Center is where everything it knows is
        laid out, so the pill hands the screen over to it."""
        self._close()
        self.knowledge_requested.emit()

    def _add_exchange(self, heard: str):
        """A new question joins the conversation at once, before its answer
        exists, and the panel follows it."""
        stamp = datetime.now().strftime("%I:%M %p").lstrip("0")
        self._exchanges.append([heard, "", False, stamp])
        self._reading_layout.addWidget(QWidget())      # placeholder, rendered next
        self._render_exchange(len(self._exchanges) - 1)

    def _render_exchange(self, index: int):
        """Rebuild one exchange in place: what Mo said, the answer as labelled
        sections, and the time it was asked.

        Kicker over body, the same shape as every readout on this surface, so
        a five-part summary scans instead of having to be read start to end.
        Markdown never reaches a label: it is parsed here, not displayed.
        """
        heard, answer, interrupted, stamp = self._exchanges[index]
        block = QWidget()
        block.setStyleSheet("background: transparent;")
        rows = QVBoxLayout(block)
        rows.setContentsMargins(0, 0 if index == 0 else 18, 0, 0)
        rows.setSpacing(0)

        if heard:
            rows.addWidget(_wrapped(
                heard, f"{_mono(11, tokens.CK_TEXT_LOW, 0.6)} padding: 0 0 10px 0;"))

        for n, (label, body) in enumerate(prose.sections(answer)):
            if label:
                kicker = QLabel(label.upper())
                kicker.setStyleSheet(
                    f"{_mono(9, tokens.CK_TEXT_LOW, 1.8)}"
                    f" padding: {12 if n else 0}px 0 3px 0;")
                rows.addWidget(kicker)
            rows.addWidget(_wrapped(
                body,
                f"color: {tokens.CK_TEXT_MID if label else tokens.CK_TEXT_HI};"
                f" font-family: {theme.FONT}; font-size: 13px;"
                f" background: transparent; line-height: 150%;"
                f" padding: {0 if label else (10 if n else 0)}px 0 0 0;"))

        if interrupted:
            # Talked over: the half-spoken answer stays, marked as cut short.
            cut = QLabel("INTERRUPTED")
            cut.setStyleSheet(f"{_mono(9, tokens.CK_TEXT_LOW, 1.8)} padding: 8px 0 0 0;")
            rows.addWidget(cut)

        time_label = QLabel(stamp)
        time_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        time_label.setStyleSheet(f"{_mono(9, tokens.CK_TEXT_FAINT, 0.8)} padding: 6px 0 0 0;")
        rows.addWidget(time_label)

        old = self._reading_layout.itemAt(index).widget()
        self._reading_layout.replaceWidget(old, block)
        old.setParent(None)                # not deleteLater: the old rows stay
                                           # painted over the new ones
        QTimer.singleShot(0, self._follow_latest)

    def _follow_latest(self):
        """Bring the newest exchange's first line to the top of the panel — a
        long answer is read from its start, not its end. Looked up when it
        runs: a close in the meantime may have emptied the panel."""
        count = self._reading_layout.count()
        if count:
            self._reading_layout.activate()
            self._reading_box.adjustSize()
            latest = self._reading_layout.itemAt(count - 1).widget()
            self._reading_scroll.verticalScrollBar().setValue(latest.y())

    def _refresh_rails(self):
        """Rail content, from data already on disk — never the network."""
        self._calendar.refresh()

        while self._today_list.count():
            item = self._today_list.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
        events = _cached_lines("calendar", 4)
        for line in events or ["Nothing on today."]:
            row = QLabel(line)
            row.setWordWrap(True)
            row.setStyleSheet(
                f"color: {tokens.CK_TEXT_MID if events else tokens.CK_TEXT_FAINT};"
                f" font-family: {theme.FONT}; font-size: 12px;"
                f" background: transparent; padding: 3px 0;"
            )
            self._today_list.addWidget(row)

        while self._auto_list.count():
            item = self._auto_list.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
        for label, tag in self._automations():
            self._auto_list.addWidget(_RailRow(label, tag))

    def _automations(self) -> list:
        """Scheduled skills first, then queued autonomous tasks — the things
        El Fager runs without being asked each time."""
        rows: list = []
        try:
            from core.skills.store import SkillStore
            for skill in SkillStore().list_all():
                if len(rows) >= 6:
                    break
                name = (skill.get("name") or "").strip()
                if name:
                    rows.append((name, (skill.get("schedule") or "manual").upper()[:12]))
        except Exception:
            pass
        try:
            from core.autonomous_tasks import AutonomousTaskManager
            for task in AutonomousTaskManager().list_all():
                if len(rows) >= 6:
                    break
                desc = (task.get("description") or "").strip()
                if desc:
                    rows.append((desc[:60], (task.get("status") or "queued").upper()[:12]))
        except Exception:
            pass
        return rows or [("Nothing scheduled yet.", "")]

    def _build_keymap(self, parent: QWidget) -> QWidget:
        """The `?` map. A child of the chrome so it covers the stage without
        taking a second window — Esc or `?` again puts it away."""
        panel = QWidget(parent)
        # A plain QWidget ignores a stylesheet background unless it is told to
        # style it — without this the scrim never paints and the stage below
        # reads straight through the map.
        panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        panel.setStyleSheet(f"background: {tokens.rgba(tokens.CK_VOID, 0.97)};")
        panel.setVisible(False)

        column = QVBoxLayout(panel)
        column.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.setSpacing(14)

        title = QLabel("KEYBOARD")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(_mono(11, tokens.CK_STATE["listening"], 3.0))
        column.addWidget(title)

        for key, what in _KEYS:
            row = QHBoxLayout()
            row.setSpacing(18)
            row.addStretch()
            cap = QLabel(key)
            cap.setFixedWidth(150)
            cap.setAlignment(Qt.AlignmentFlag.AlignRight)
            cap.setStyleSheet(
                f"{_mono(12, tokens.CK_TEXT_HI, 1.2)}"
                f" border: 1px solid {tokens.CK_HAIRLINE};"
                f" border-radius: {tokens.R1}px; padding: 5px 10px;"
            )
            row.addWidget(cap)
            meaning = QLabel(what)
            meaning.setFixedWidth(280)
            meaning.setStyleSheet(
                f"color: {tokens.CK_TEXT_MID}; font-family: {theme.FONT};"
                f" font-size: 14px; background: transparent;"
            )
            row.addWidget(meaning)
            row.addStretch()
            column.addLayout(row)

        foot = QLabel("IGNORED WHILE YOU'RE TYPING")
        foot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        foot.setStyleSheet(_mono(10, tokens.CK_TEXT_FAINT))
        column.addWidget(foot)
        return panel

    def toggle_keymap(self):
        # isHidden(), not isVisible(): a child of a window that isn't on
        # screen is never "visible", so isVisible() would show it forever.
        showing = self._keymap.isHidden()
        if showing:
            self._keymap.setGeometry(self.rect())
            self._keymap.raise_()
        self._keymap.setVisible(showing)

    def _ensure_orb(self):
        """Build the one QWebEngine instance, the first time it is needed."""
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
        if ok:
            self._push_orb_state(self._current_state)

    def _push_orb_state(self, state: str):
        if not (self._orb and self._orb_ready):
            return
        self._orb.page().runJavaScript(
            f"window.orb && window.orb.setState('{_ORB_STATE.get(state, 'idle')}')"
        )

    def _orb_js(self, code: str):
        if self._orb and self._orb_ready:
            self._orb.page().runJavaScript(code)

    # ------------------------------------------------------------------ #
    #  State                                                               #
    # ------------------------------------------------------------------ #

    def _paint_state(self, state: str):
        color = tokens.CK_STATE.get(_ORB_STATE.get(state, "idle"), tokens.CK_STATE["idle"])
        self._state_chip.set_state(_LABELS.get(state, state.upper()), color)
        self._state_label.setStyleSheet(_mono(11, color, 2.6))
        for readout in self._readouts():
            readout.set_tint(color)
        self._paint_voice_bar(state, color)
        self._push_orb_state(state)

    def _paint_voice_bar(self, state: str, color: str):
        """At rest it says who you are talking to; mid-turn, what it is doing."""
        busy = {"listening": "LISTENING…", "processing": "THINKING…",
                "speaking": "SPEAKING"}.get(state)
        self._voice_bar.setText(busy or "You're talking to El Fager through voice")
        font = _mono(10, tokens.CK_TEXT_HI, 1.8) if busy else (
            f"color: {tokens.CK_TEXT_MID}; font-family: {theme.FONT}; font-size: 12px;")
        self._voice_bar.setStyleSheet(
            f"QPushButton {{ {font} text-align: left; padding: 10px 14px;"
            f" background: {tokens.rgba(color if busy else '#FFFFFF', 0.08 if busy else 0.03)};"
            f" border: 1px solid {tokens.rgba(color if busy else '#FFFFFF', 0.45 if busy else 0.10)};"
            f" border-radius: 10px; }}"
            f"QPushButton:hover {{ border-color: {tokens.rgba(tokens.EMBER, 0.55)}; }}")

    # ── Attention: ambient → ready → exchange ─────────────────────────────

    def _ambient_delay_ms(self) -> int:
        """Settings → System, 'ambient_delay'. Accepts 30s / 60s / 2m or a
        plain number of seconds."""
        raw = _load_settings().get("ambient_delay", _AMBIENT_DEFAULT)
        if isinstance(raw, str):
            seconds = _AMBIENT_DELAYS.get(raw.strip().lower())
            if seconds is None:
                try:
                    seconds = int(raw.strip().rstrip("s"))
                except ValueError:
                    seconds = _AMBIENT_DEFAULT
        else:
            try:
                seconds = int(raw)
            except (TypeError, ValueError):
                seconds = _AMBIENT_DEFAULT
        return max(5, seconds) * 1000

    def _set_attention(self, level: str):
        """ambient (orb alone) · ready (readouts up) · exchange (words own it)."""
        self._attention = level
        opacity = _ATTENTION.get(level, 1.0)
        for readout in self._readouts():
            readout.set_attention(opacity)
        self._receipts_box.setVisible(
            level != "ambient" and self._receipts_layout.count() > 0)
        self._orb_js(
            f"window.orb && window.orb.setAmbient({str(level == 'ambient').lower()})")

    def _readouts(self):
        return (self._r_time, self._r_next, self._r_today, self._r_skills)

    def _go_ambient(self):
        """Ambient is the orb alone: the readouts go, and so does anything on
        the stage. The transcript is kept — it is saved until the Cockpit
        closes."""
        if self._current_state != "idle":
            return
        self._set_attention("ambient")
        self._notice.setText("")
        self._clear_data_moment()
        self._steps_box.setVisible(False)

    def _wake_attention(self, level: str = "ready"):
        """Anything that counts as life: a key, an exchange, a wake word."""
        if self._attention != level:
            self._set_attention(level)
        self._ambient_timer.start(self._ambient_delay_ms())

    def _tick_clock(self):
        now = datetime.now()
        hour = now.hour % 12 or 12
        suffix = "AM" if now.hour < 12 else "PM"
        self._r_time.set_value(f"{hour}:{now.minute:02d} {suffix}")

    def _refresh_readouts(self):
        self._tick_clock()
        self._r_next.set_value(_cached("calendar"))
        self._r_today.set_value(_cached("tasks"))
        self._r_skills.set_value(self._skills_online())
        self._refresh_rails()

    def _skills_online(self) -> str:
        """How many of the six surfaces are switched on in Settings → Skills."""
        try:
            from core.brain import SKILL_TOOLS
            disabled = set(_load_settings().get("skills_disabled", []) or [])
            live = [k for k in SKILL_TOOLS if k not in disabled]
        except Exception:
            return "—"
        return f"{len(live)} of {len(live) + len(disabled)}"

    # ── Data moments ──────────────────────────────────────────────────────

    def _clear_data_moment(self):
        while self._moment_layout.count():
            item = self._moment_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._moment.setVisible(False)

    def _show_data_moment(self):
        """Show the thing the turn was about, if it is a thing worth seeing.

        Driven off the step ledger — the tools the turn actually ran — so it
        can only ever appear for a turn that touched that data. It is
        transient by construction: the next 'listening' clears it.
        """
        self._clear_data_moment()
        skills = {step.skill for step in progress.steps() if step.skill}
        builder = None
        if "todoist" in skills or "calendar" in skills:
            builder = self._moment_rows
        if "gmail" in skills:
            builder = self._moment_rows
        if any("health" in (step.tool or "") or "meal" in (step.tool or "")
               or "nutrition" in (step.tool or "") for step in progress.steps()):
            builder = self._moment_health
        if builder is None:
            return
        widgets = builder(skills)
        for widget in widgets:
            self._moment_layout.addWidget(widget)
        self._moment.setVisible(bool(widgets))

    def _moment_health(self, _skills) -> list:
        """The day-arc, the same one the Command Center paints."""
        from ui.command_center import _read_nutrition
        from ui.widgets import DayArc, MacroBar

        nutrition = _read_nutrition()
        if not nutrition or not nutrition["kcal"]:
            return []
        arc = DayArc(unit="kcal")
        arc.set_values(nutrition["logged_kcal"], nutrition["kcal"])
        protein = MacroBar("Protein", tokens.CK_STATE["speaking"])
        protein.set_values(nutrition["logged_protein"], nutrition["protein"])
        return [arc, protein]

    def _moment_rows(self, skills) -> list:
        """Up to three lines of whatever the turn was about, from the cache."""
        card = "mail" if "gmail" in skills else (
            "calendar" if "calendar" in skills else "tasks")
        try:
            data = json.loads(_CACHE.read_text(encoding="utf-8"))
            text = data.get("cards", {}).get(card, {}).get("text", "")
        except Exception:
            return []
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()][:3]
        if not lines:
            return []
        tint = tokens.SKILL_TINT.get(
            "gmail" if card == "mail" else
            ("calendar" if card == "calendar" else "todoist"),
            tokens.CK_STATE["listening"],
        )
        out = []
        head = QLabel(card.upper())
        head.setStyleSheet(_mono(9, tint, 2.0))
        out.append(head)
        for line in lines:
            row = QLabel(f"·  {line[:44]}")
            row.setStyleSheet(_mono(11, tokens.CK_TEXT_MID, 0.6))
            out.append(row)
        return out

    @pyqtSlot()
    def _refresh_receipts(self):
        """Max three, newest first — the corner ledger, not a history."""
        while self._receipts_layout.count():
            item = self._receipts_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        for receipt in staging.receipts()[:3]:
            line = QLabel(f"•  {receipt['at']}  {receipt['summary']}"[:64])
            line.setStyleSheet(_mono(10, tokens.OK, 0.8))
            self._receipts_layout.addWidget(line)
        self._receipts_box.setVisible(
            self._receipts_layout.count() > 0 and self._attention != "ambient")

    @pyqtSlot()
    def _refresh_steps(self):
        """Per-skill tinted dot while active, green when done, red on fail."""
        while self._steps_layout.count():
            item = self._steps_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        from ui.widgets import StepMark

        steps = progress.steps()
        for step in steps:
            if step.status == "done":
                color = tokens.OK
            elif step.status == "failed":
                color = tokens.CK_STATE["error"]
            else:
                color = tokens.SKILL_TINT.get(step.skill or "",
                                              tokens.CK_STATE["thinking"])
            row = QWidget()
            row.setStyleSheet("background: transparent;")
            line = QHBoxLayout(row)
            line.setContentsMargins(0, 0, 0, 0)
            line.setSpacing(10)
            line.addWidget(StepMark(step.status, color), 0,
                           Qt.AlignmentFlag.AlignVCenter)
            label = QLabel(step.label)
            label.setStyleSheet(_mono(12, color, 0.8))
            line.addWidget(label)
            line.addStretch()
            self._steps_layout.addWidget(row)
        self._steps_box.setVisible(bool(steps))

    @pyqtSlot()
    def _refresh_staged(self):
        self._refresh_receipts()   # a send clears the stage and writes one
        action = staging.current()
        if action is None:
            self._staged.setVisible(False)
            return
        self._staged.setText(
            f"{action.medium.upper()} → {action.target}\n{action.body}"
        )
        self._staged.setStyleSheet(
            f"color: {tokens.CK_TEXT_HI}; font-family: {theme.FONT}; font-size: 14px;"
            f" background: {tokens.CK_CARD};"
            f" border: 1px solid {tokens.rgba(tokens.CK_STATE['speaking'], 0.45)};"
            f" border-radius: 14px; padding: 13px 16px;"
        )
        self._staged.setVisible(True)

    @pyqtSlot(str, str, str)
    def on_state_update(self, state: str, transcript: str, response: str):
        self._current_state = state
        if state == "listening":
            # The mic reopens a beat after every answer; the conversation
            # stays put so it can still be read.
            self._notice.setText("")
            self._clear_data_moment()
        elif (state == "processing" and transcript
                and transcript not in ("Transcribing...", "Loading Whisper model...")):
            self._add_exchange(transcript)
        elif state == "speaking" and response:
            if not self._exchanges:
                self._add_exchange("")
            self._exchanges[-1][1] = response
            self._render_exchange(len(self._exchanges) - 1)
            self._show_data_moment()
        elif state == "interrupted" and self._exchanges:
            # The half-spoken answer stays, marked as cut short.
            self._exchanges[-1][2] = True
            self._render_exchange(len(self._exchanges) - 1)
        self._paint_state(state)
        # An exchange dims the readouts to 12%: the exchange owns the screen.
        self._wake_attention("exchange" if state != "idle" else "ready")

    @pyqtSlot(str)
    def on_error(self, message: str):
        self._current_state = "error"
        self._notice.setText(message)
        self._paint_state("error")
        self._wake_attention("exchange")

    @pyqtSlot()
    def on_pipeline_done(self):
        if self._current_state != "error":
            self._current_state = "idle"
            self._paint_state("idle")
        # The readouts come back, and the ambient countdown starts again.
        self._wake_attention("ready")

    # ------------------------------------------------------------------ #
    #  Show / hide                                                         #
    # ------------------------------------------------------------------ #

    def toggle(self):
        if self.isVisible():
            self._close()
        else:
            self.open()

    def open(self):
        self._ensure_orb()
        self._refresh_readouts()
        self._refresh_staged()
        self._refresh_steps()
        self.showFullScreen()
        self.raise_()
        self.activateWindow()
        self._clock.start()
        self._orb_js("window.orb && window.orb.start()")
        self._wake_attention("ready")

    def wake_word_activate(self):
        """Voice wake blooms; a click-open is silent."""
        self.open()
        self._orb_js("window.orb && window.orb.bloom()")

    def _close(self):
        # The session's conversation ends with it: the next open starts empty.
        while self._reading_layout.count():
            item = self._reading_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().setParent(None)
        self._exchanges = []
        self._notice.setText("")
        self._clock.stop()
        self._ambient_timer.stop()      # no timers running behind the tray
        self._keymap.setVisible(False)
        self._orb_js("window.orb && window.orb.stop()")   # no idle GPU in tray
        self.hide()

    def open_ledger(self):
        """The record, opened over the cockpit. Built on first use."""
        if getattr(self, "_ledger_window", None) is None:
            from ui.trust_ledger import TrustLedgerWindow
            self._ledger_window = TrustLedgerWindow(self)
        self._ledger_window.open()

    def keyPressEvent(self, event):
        key = event.key()
        self._wake_attention(self._attention if self._attention == "exchange"
                             else "ready")
        if key == Qt.Key.Key_Escape:
            # Esc unwinds one layer at a time: the map, then a staged action,
            # then the cockpit itself.
            if not self._keymap.isHidden():
                self._keymap.setVisible(False)
            elif staging.current() is not None:
                staging.cancel()
            else:
                self._close()
        elif key == Qt.Key.Key_Question:
            self.toggle_keymap()
        elif key == Qt.Key.Key_Space:
            self._start_pipeline()
        elif key == Qt.Key.Key_Return or key == Qt.Key.Key_Enter:
            if staging.current() is not None:
                staging.confirm()
        elif key == Qt.Key.Key_L:
            self.open_ledger()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        staging.unsubscribe(getattr(self, "_staged_cb", None))
        progress.unsubscribe(getattr(self, "_progress_cb", None))
        event.ignore()
        self._close()

    # ------------------------------------------------------------------ #
    #  Pipeline                                                            #
    # ------------------------------------------------------------------ #

    def _start_pipeline(self, text_input: "str | None" = None):
        if self._worker and self._worker.isRunning():
            return
        from core.pipeline import PipelineWorker

        self._worker = PipelineWorker(
            self.voice_in, self.brain, self.voice_out, self.memory,
            text_input=text_input,
        )
        self._worker.state_update.connect(self.on_state_update)
        self._worker.done.connect(self.on_pipeline_done)
        self._worker.error.connect(self.on_error)
        if self._wake_listener:
            self._worker.started.connect(self._wake_listener.pause)
            self._worker.done.connect(self._wake_listener.resume)
        self._worker.start()
