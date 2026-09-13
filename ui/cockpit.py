"""
El Fager — the Cockpit (the design's primary surface).

A dark window with the Ember at its centre, corner readouts on
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
import re
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QEvent, QPoint, QPointF, QRect, QUrl, Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
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
from ui.overlay import _load_settings, _save_settings

_CACHE = Path("data/command_center_cache.json")
_ORB_PAGE = Path(__file__).parent / "assets" / "cockpit_orb.html"

# The three attention states, as readout opacity. Ambient is the orb alone;
# during an exchange the words own the stage and the readouts recede.
_ATTENTION = {"ambient": 0.0, "ready": 1.0, "exchange": 0.12}

# Settings → System offers 30s / 60s / 2m; 60 is the design's default.
_AMBIENT_DELAYS = {"30s": 30, "60s": 60, "2m": 120}
_AMBIENT_DEFAULT = 60

# A normal window rather than full screen: this size when there is no saved
# one, and a grab margin round the edge that resizes it.
_DEFAULT_SIZE = (1280, 760)
_RESIZE_MARGIN = 5

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


class _StatusCard(QWidget):
    """The reel's small card at the head of the left rail: the time and date,
    what El Fager has done today, and what is next."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("status")
        self.setStyleSheet(
            f"QWidget#status {{ background: {tokens.rgba(tokens.CK_PANEL, 0.72)};"
            f" border: 1px solid {tokens.CK_HAIRLINE}; border-radius: {tokens.R2}px; }}")
        col = QVBoxLayout(self)
        col.setContentsMargins(16, 12, 16, 12)
        col.setSpacing(6)

        top = QHBoxLayout()
        self.time = QLabel("—")
        self.time.setStyleSheet(
            f"color: {tokens.CK_TEXT_HI}; font-family: {theme.FONT}; font-size: 20px;"
            f" font-weight: 500; background: transparent;")
        top.addWidget(self.time)
        top.addStretch()
        self.date = QLabel("")
        self.date.setStyleSheet(_mono(10, tokens.CK_TEXT_LOW, 1.4))
        top.addWidget(self.date, 0, Qt.AlignmentFlag.AlignVCenter)
        col.addLayout(top)

        done = QHBoxLayout()
        done.setSpacing(8)
        dot = QLabel("●")
        dot.setStyleSheet(_mono(8, tokens.OK, 0))
        done.addWidget(dot)
        kicker = QLabel("DONE TODAY")
        kicker.setStyleSheet(_mono(10, tokens.CK_TEXT_LOW, 1.6))
        done.addWidget(kicker)
        self.done = QLabel("—")
        self.done.setStyleSheet(
            f"color: {tokens.OK}; font-family: {theme.FONT_MONO}; font-size: 13px;"
            f" font-weight: 600; background: transparent;")
        done.addWidget(self.done)
        done.addStretch()
        col.addLayout(done)

        upcoming = QHBoxLayout()
        upcoming.setSpacing(8)
        kicker = QLabel("NEXT")
        kicker.setStyleSheet(_mono(10, tokens.CK_TEXT_LOW, 1.6))
        upcoming.addWidget(kicker, 0, Qt.AlignmentFlag.AlignTop)
        self.next = QLabel("—")
        self.next.setWordWrap(True)
        self.next.setStyleSheet(
            f"color: {tokens.CK_TEXT_MID}; font-family: {theme.FONT}; font-size: 12px;"
            f" background: transparent;")
        upcoming.addWidget(self.next, 1)
        col.addLayout(upcoming)

    def set_attention(self, opacity: float):
        """Recedes with the other readouts; an effect, so nothing reflows."""
        effect = self.graphicsEffect()
        if not isinstance(effect, QGraphicsOpacityEffect):
            effect = QGraphicsOpacityEffect(self)
            self.setGraphicsEffect(effect)
        effect.setOpacity(opacity)

    def set_tint(self, color: str):
        pass                  # a card, not a hairline readout: it keeps its border


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
    place to find yourself in the month, not a calendar to work in. ‹ › in
    the title row look at the months either side, as the reel's does."""

    def __init__(self, parent=None):
        super().__init__(parent)
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(4)
        self._title = QLabel("")
        self._title.setStyleSheet(_mono(11, tokens.CK_TEXT_MID, 2.4))
        head.addWidget(self._title)
        head.addStretch()
        arrows = []
        for glyph, step in (("‹", -1), ("›", 1)):
            arrow = QPushButton(glyph)
            arrow.setCursor(Qt.CursorShape.PointingHandCursor)
            arrow.setFixedSize(22, 22)
            arrow.setStyleSheet(
                f"QPushButton {{ {_mono(13, tokens.CK_TEXT_LOW, 0)} border: none;"
                f" border-radius: 11px; }}"
                f"QPushButton:hover {{ color: {tokens.CK_TEXT_HI};"
                f" background: {tokens.rgba('#FFFFFF', 0.06)}; }}")
            arrow.clicked.connect(lambda _c=False, s=step: self._step(s))
            head.addWidget(arrow)
            arrows.append(arrow)
        self._prev, self._next = arrows
        col.addLayout(head)
        self._shown = (datetime.now().year, datetime.now().month)

        self._grid = QGridLayout()
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(2)
        self._grid.setVerticalSpacing(3)
        col.addLayout(self._grid)
        self.refresh()

    def _step(self, months: int):
        index = self._shown[0] * 12 + (self._shown[1] - 1) + months
        self._paint(index // 12, index % 12 + 1)

    def refresh(self):
        """Back to this month — the rail opens on today."""
        now = datetime.now()
        self._paint(now.year, now.month)

    def _paint(self, year: int, month: int):
        self._shown = (year, month)
        while self._grid.count():
            item = self._grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)

        today = datetime.now()
        self._title.setText(datetime(year, month, 1).strftime("%B %Y").upper())
        this_month = (year, month) == (today.year, today.month)
        for c, name in enumerate(("M", "T", "W", "T", "F", "S", "S")):
            head = QLabel(name)
            head.setAlignment(Qt.AlignmentFlag.AlignCenter)
            head.setStyleSheet(_mono(9, tokens.CK_TEXT_FAINT, 0.6))
            self._grid.addWidget(head, 0, c)

        for r, week in enumerate(calendar.monthcalendar(year, month), start=1):
            for c, day in enumerate(week):
                if day == 0:
                    continue
                cell = QLabel(str(day))
                cell.setAlignment(Qt.AlignmentFlag.AlignCenter)
                cell.setFixedHeight(20)
                if this_month and day == today.day:
                    cell.setStyleSheet(
                        f"{_mono(10, tokens.CK_TEXT_ON_FILL, 0)}"
                        f" background: {tokens.EMBER}; border-radius: 4px;"
                    )
                else:
                    cell.setStyleSheet(_mono(10, tokens.CK_TEXT_LOW, 0))
                self._grid.addWidget(cell, r, c)


class _FileMark(QWidget):
    """The reel's automation icon: a small ember page with its corner folded.

    Painted rather than typed, like the step ledger's marks — a font without
    the glyph would draw an empty box.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(12, 16)   # page sits 2px low, on the text line

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        page = QPainterPath(QPointF(1.5, 3.5))
        page.lineTo(7.5, 3.5)
        page.lineTo(10.5, 6.5)
        page.lineTo(10.5, 14.5)
        page.lineTo(1.5, 14.5)
        page.closeSubpath()
        p.setBrush(QColor(tokens.EMBER))
        p.drawPath(page)
        fold = QPainterPath(QPointF(7.5, 3.5))
        fold.lineTo(7.5, 6.5)
        fold.lineTo(10.5, 6.5)
        fold.closeSubpath()
        p.setBrush(QColor(tokens.EMBER_BRIGHT))
        p.drawPath(fold)


class _RailRow(QWidget):
    """One automation: what it is on the left, when/where it runs on the
    right. The tag is mono so the column of them lines up."""

    def __init__(self, label: str, tag: str, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 5, 0, 5)
        row.setSpacing(10)
        row.addWidget(_FileMark(), 0, Qt.AlignmentFlag.AlignTop)
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


# A long run with no spaces — a link, an email address — cannot wrap, so it
# forces its label wider than the rail and the end is clipped off. A
# zero-width space after each of these characters lets it break there while
# reading and copying exactly as written.
_LONG_RUN = re.compile(r"\S{20,}")
_BREAK_AFTER = re.compile(r"([/?&=._\-@:])")


def _breakable(text: str) -> str:
    return _LONG_RUN.sub(lambda m: _BREAK_AFTER.sub("\\1\u200b", m.group(0)), text)


# A transcript tab is named for what was asked, in a few words: the wake
# phrase comes off the front, the words speech is padded with come out ("I
# want you to", "can you", "tell me what's", "no, it's"), and the first three
# left name it, as many as fit. Local and instant, so the tab has its name the
# moment the question lands.
_TOPIC_WAKE = sorted((tuple(p.split()) for p in (
    "hey el fager", "hey fager", "el fager", "fager",
)), key=len, reverse=True)
_TOPIC_SMALL_WORDS = frozenset("""
    a an the my me to on of for by in at and or is are am was were be been
    please about some any it it's just now up also there here not don't
    i i'm i'll i'd i've you you're your we he she they them
    that that's this these those what what's whats when where how how's why who
    do does did have has had will would can could should
    no yes yeah yep ok okay so if then but um uh oh ah hey
    going gonna want wanna like really actually first all with
    tell show give let know see get got
""".split())
_TOPIC_MAX = 22


def _topic(heard: str) -> str:
    """A few words naming the question, or "" when nothing is left."""
    words = re.findall(r"[\w']+", heard)
    lowered = [w.lower() for w in words]
    for wake in _TOPIC_WAKE:
        if tuple(lowered[:len(wake)]) == wake:
            words, lowered = words[len(wake):], lowered[len(wake):]
            break
    kept, seen = [], set()
    for word, low in zip(words, lowered):
        if low not in _TOPIC_SMALL_WORDS and low not in seen:   # "ask ask ask" once
            kept.append(word)
            seen.add(low)
    kept = kept[:3]
    if not kept:
        return ""
    # Whole words, as many as fit; only a single overlong word is cut.
    while len(kept) > 1 and len(" ".join(kept)) > _TOPIC_MAX:
        kept.pop()
    name = " ".join(kept)
    name = name[0].upper() + name[1:]
    return name if len(name) <= _TOPIC_MAX else name[:_TOPIC_MAX - 1] + "…"


def _wrapped(text: str, style: str) -> QLabel:
    """A word-wrapped label that tells its layout how tall it is — wrapped
    labels clip otherwise, the trap this project has hit before."""
    label = QLabel(_breakable(text))
    label.setWordWrap(True)
    label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
    policy = label.sizePolicy()
    policy.setHeightForWidth(True)
    label.setSizePolicy(policy)
    label.setStyleSheet(style)
    return label


class _TitleButton(QPushButton):
    """– □ × for the Cockpit's own title bar. Painted, not typed: the bundled
    face has no box glyph, and a font fallback for a window control is a
    coin flip."""

    _TIPS = {"min": "Minimise", "max": "Maximise", "close": "Close"}

    def __init__(self, kind: str, parent=None):
        super().__init__(parent)
        self._kind = kind
        self.setFixedSize(40, 30)
        self.setToolTip(self._TIPS[kind])
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("background: transparent; border: none;")

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.underMouse():
            hover = (tokens.rgba(tokens.CK_STATE["error"], 0.75) if self._kind == "close"
                     else tokens.rgba("#FFFFFF", 0.08))
            p.fillRect(self.rect(), QColor(hover))
        pen = QPen(QColor(tokens.CK_TEXT_HI if self.underMouse() else tokens.CK_TEXT_MID), 1.2)
        p.setPen(pen)
        cx, cy = self.width() / 2, self.height() / 2
        if self._kind == "min":
            p.drawLine(QPointF(cx - 5, cy), QPointF(cx + 5, cy))
        elif self._kind == "max":
            p.drawRect(QRect(int(cx - 5), int(cy - 5), 10, 10))
        else:
            p.drawLine(QPointF(cx - 5, cy - 5), QPointF(cx + 5, cy + 5))
            p.drawLine(QPointF(cx + 5, cy - 5), QPointF(cx - 5, cy + 5))


class _TabStrip(QScrollArea):
    """The transcript's tab row. It scrolls sideways with no bar to grab, so
    the mouse wheel does it: up goes toward the first tab, down toward the
    newest."""

    def wheelEvent(self, event):
        delta = event.angleDelta().y() or event.angleDelta().x()
        bar = self.horizontalScrollBar()
        bar.setValue(bar.value() - delta // 2)
        event.accept()


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
    """The design's primary surface, in a normal window. Same integration contract as the overlay."""

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
        # Cockpit closes — the ledger is the durable record. _focus is the one
        # the arrows under the sphere point at, -1 while there are none.
        self._exchanges: list = []
        self._tab_buttons: list = []
        self._focus = -1

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
        """A normal window with a dark title bar of its own. Frameless so the
        bar can be the design's, but it keeps the minimise and maximise hints
        so the taskbar button behaves like any other app's."""
        self.setWindowFlags(Qt.WindowType.Window
                            | Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.WindowMinMaxButtonsHint)
        self.setWindowTitle("El Fager — Cockpit")
        self.setObjectName("cockpit")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            f"QWidget#cockpit {{ background: {tokens.CK_VOID};"
            f" border: 1px solid {tokens.CK_HAIRLINE}; }}")
        self.setMouseTracking(True)       # edge cursors before any button is down

    def _build_ui(self):
        # The window: a grab margin for resizing, the title bar, then the
        # stage. StackAll puts the native chrome over the orb without either
        # one clipping the other.
        root = QVBoxLayout(self)
        root.setContentsMargins(*([_RESIZE_MARGIN] * 4))
        root.setSpacing(0)
        root.addWidget(self._build_title_bar())
        stage = QWidget()
        stage.setStyleSheet("background: transparent;")
        root.addWidget(stage, 1)
        self._stack = QStackedLayout(stage)
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
        self._centre = centre        # the orb page centres the sphere on it
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
        # An explicit minimum overrides the text's own: an error with one long
        # unbroken string must never push the window past the screen edge.
        self._notice.setMinimumWidth(1)
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

        # Under the sphere, as the reel has it: ‹ › step through the
        # conversation in the rail, and the count says where you are in it.
        self._scrub_value = QLabel("—")
        self._scrub_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._scrub_value.setMinimumWidth(90)
        self._scrub_value.setStyleSheet(_mono(11, tokens.CK_TEXT_MID, 2.0))
        scrub = QHBoxLayout()
        scrub.setSpacing(14)
        scrub.addStretch()
        arrows = []
        for glyph, step in (("‹", -1), ("›", 1)):
            arrow = QPushButton(glyph)
            arrow.setCursor(Qt.CursorShape.PointingHandCursor)
            arrow.setFixedSize(26, 26)
            arrow.setStyleSheet(
                f"QPushButton {{ {_mono(14, tokens.CK_TEXT_LOW, 0)}"
                f" border: 1px solid {tokens.rgba('#FFFFFF', 0.08)};"
                f" border-radius: 13px; }}"
                f"QPushButton:hover {{ color: {tokens.CK_TEXT_HI};"
                f" border-color: {tokens.rgba(tokens.EMBER, 0.45)}; }}"
            )
            arrow.clicked.connect(lambda _c=False, s=step: self._step(s))
            arrows.append(arrow)
        self._scrub_prev, self._scrub_next = arrows
        scrub.addWidget(self._scrub_prev)
        scrub.addWidget(self._scrub_value)
        scrub.addWidget(self._scrub_next)
        scrub.addStretch()
        grid.addLayout(scrub)
        grid.addSpacing(14)

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
        # Nothing else under the sphere, as the reel has it: the ledger is on
        # L and the SKILLS button, and ? lists the keys.

        # Tests and the state machine both read _state_label; it *is* the
        # chip's label, so the state is named once on screen, not twice.
        self._state_label = self._state_chip.label

        outer.addWidget(self._build_right_rail(), 0)
        self._keymap = self._build_keymap(chrome)

    def _build_title_bar(self) -> QWidget:
        """Name on the left, – □ × on the right; drag it to move the window,
        double-click it to maximise."""
        self._title_bar = QWidget()
        self._title_bar.setStyleSheet("background: transparent;")
        self._title_bar.installEventFilter(self)
        row = QHBoxLayout(self._title_bar)
        row.setContentsMargins(18, 0, 0, 0)
        row.setSpacing(0)
        name = QLabel("EL FAGER — COCKPIT")
        name.setStyleSheet(_mono(10, tokens.CK_TEXT_LOW, 2.0))
        name.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        row.addWidget(name)
        row.addStretch()
        self._btn_min = _TitleButton("min")
        self._btn_min.clicked.connect(self.showMinimized)
        self._btn_max = _TitleButton("max")
        self._btn_max.clicked.connect(self._toggle_maximised)
        self._btn_close = _TitleButton("close")
        self._btn_close.clicked.connect(self._close)
        for button in (self._btn_min, self._btn_max, self._btn_close):
            row.addWidget(button)
        return self._title_bar

    # ── Rails ─────────────────────────────────────────────────────────────

    def _build_left_rail(self) -> QWidget:
        """The day: the status card, the month, what is on today."""
        rail = QWidget()
        rail.setFixedWidth(318)
        rail.setStyleSheet("background: transparent;")
        col = QVBoxLayout(rail)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(18)

        self._status = _StatusCard()
        col.addWidget(self._status)

        cal_panel = _Panel("")
        self._calendar = _MonthCalendar()
        cal_panel.column.addWidget(self._calendar)
        col.addWidget(cal_panel)

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
        # The panel ends at its buttons, as the reel's does; how many skills
        # are on rides on the SKILLS button rather than a readout of its own.
        col.addWidget(auto)

        # The conversation takes the rest of the rail: every exchange this
        # session stacked in one scroll, newest last, the way the reel lays
        # out its chat. An answer is set as labelled sections rather than one
        # block — the model reaches for "Academic:" style headings on a
        # summary, and reading that structure beats a wall of prose.
        reading = _Panel("")
        self._reading_panel = reading

        # The reel's tab row heads the panel: one numbered tab per question,
        # the selected one a filled pill. A long session scrolls sideways.
        self._tabs_row = QWidget()
        self._tabs_row.setStyleSheet("background: transparent;")
        head = QHBoxLayout(self._tabs_row)
        head.setContentsMargins(0, 0, 0, 4)
        head.setSpacing(10)
        tabs_box = QWidget()
        tabs_box.setStyleSheet("background: transparent;")
        self._tabs_layout = QHBoxLayout(tabs_box)
        self._tabs_layout.setContentsMargins(0, 0, 0, 0)
        self._tabs_layout.setSpacing(4)
        self._tabs_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self._tabs_scroll = _TabStrip()
        self._tabs_scroll.setWidgetResizable(True)
        self._tabs_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._tabs_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._tabs_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self._tabs_scroll.viewport().setStyleSheet("background: transparent;")
        self._tabs_scroll.setFixedHeight(30)
        self._tabs_scroll.setWidget(tabs_box)
        head.addWidget(self._tabs_scroll, 1)
        reading.column.addWidget(self._tabs_row)

        self._reading_box = QWidget()
        self._reading_box.setStyleSheet("background: transparent;")
        self._reading_layout = QVBoxLayout(self._reading_box)
        self._reading_layout.setContentsMargins(0, 4, 10, 4)
        self._reading_layout.setSpacing(0)
        # No AlignTop here: an aligned layout sizes its rows from their
        # unwrapped height, which clipped a long question and its answer
        # mid-line with nothing left to scroll to. Each exchange carries its
        # own stretch instead, so a short one still sits at the top.
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
        index = len(self._exchanges) - 1
        tab = QPushButton(_topic(heard) or str(index + 1))
        tab.setToolTip(heard)
        tab.setCheckable(True)
        tab.setCursor(Qt.CursorShape.PointingHandCursor)
        tab.setStyleSheet(
            f"QPushButton {{ color: {tokens.CK_TEXT_MID}; font-family: {theme.FONT};"
            f" font-size: 12px; background: transparent;"
            f" border: none; border-radius: 12px; padding: 0; }}"
            f"QPushButton:hover {{ color: {tokens.CK_TEXT_HI}; }}"
            f"QPushButton:checked {{ color: {tokens.CK_TEXT_HI};"
            f" background: {tokens.rgba(tokens.EMBER, 0.22)}; }}")
        # A fixed size, measured once the stylesheet font applies: the strip
        # squeezes each tab down to its minimum, which clipped the text.
        tab.ensurePolished()
        tab.setFixedSize(tab.fontMetrics().horizontalAdvance(tab.text()) + 24, 24)
        tab.clicked.connect(lambda _c=False, i=index: self._on_tab_clicked(i))
        self._tabs_layout.addWidget(tab)
        self._tab_buttons.append(tab)
        self._focus = index                            # a new question takes the tab
        self._render_exchange(index)

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
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(0)

        # Set to be read from a normal sitting distance: what Mo said heavy,
        # the answer large, both in the reading face rather than mono.
        if heard:
            rows.addWidget(_wrapped(
                heard,
                f"color: {tokens.CK_TEXT_HI}; font-family: {theme.FONT};"
                f" font-size: 15px; font-weight: 600; background: transparent;"
                f" padding: 0 0 10px 0;"))

        for n, (label, body) in enumerate(prose.sections(answer)):
            if label:
                kicker = QLabel(label.upper())
                kicker.setStyleSheet(
                    f"{_mono(10, tokens.CK_TEXT_MID, 1.8)}"
                    f" padding: {14 if n else 0}px 0 4px 0;")
                rows.addWidget(kicker)
            rows.addWidget(_wrapped(
                body,
                f"color: {tokens.CK_TEXT_HI};"
                f" font-family: {theme.FONT}; font-size: 16px; font-weight: 500;"
                f" background: transparent; line-height: 150%;"
                f" padding: {0 if label else (10 if n else 0)}px 0 0 0;"))

        if interrupted:
            # Talked over: the half-spoken answer stays, marked as cut short.
            cut = QLabel("INTERRUPTED")
            cut.setStyleSheet(f"{_mono(9, tokens.CK_TEXT_LOW, 1.8)} padding: 8px 0 0 0;")
            rows.addWidget(cut)

        time_label = QLabel(stamp)
        time_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        time_label.setStyleSheet(f"{_mono(10, tokens.CK_TEXT_LOW, 0.8)} padding: 6px 0 0 0;")
        rows.addWidget(time_label)
        rows.addStretch(1)

        old = self._reading_layout.itemAt(index).widget()
        self._reading_layout.replaceWidget(old, block)
        old.setParent(None)                # not deleteLater: the old rows stay
                                           # painted over the new ones
        self._focus_exchange(self._focus)

    def _on_tab_clicked(self, index: int):
        self._focus_exchange(index)
        self._wake_attention("ready")

    def _step(self, delta: int):
        """‹ goes to the exchange before, › to the one after; both stop at
        the ends."""
        if self._exchanges:
            self._focus_exchange(
                max(0, min(len(self._exchanges) - 1, self._focus + delta)))
        self._wake_attention("ready")

    def _focus_exchange(self, index: int):
        """Show one exchange: its tab selected, its count under the sphere, and
        only it in the panel, read from its first line."""
        self._focus = index
        count = self._reading_layout.count()
        for i in range(count):
            self._reading_layout.itemAt(i).widget().setVisible(i == index)
        for i, tab in enumerate(self._tab_buttons):
            tab.setChecked(i == index)
        self._scrub_value.setText(f"{index + 1} / {count}" if count else "—")
        self._reading_scroll.verticalScrollBar().setValue(0)
        QTimer.singleShot(0, self._settle_focus)

    def _settle_focus(self):
        """Once laid out: the answer back at its first line, and the selected
        tab scrolled into the strip. Looked up when it runs — a close in the
        meantime may have emptied both."""
        self._reading_scroll.verticalScrollBar().setValue(0)
        if 0 <= self._focus < len(self._tab_buttons):
            self._tabs_layout.activate()
            self._tabs_scroll.widget().adjustSize()
            self._tabs_scroll.ensureWidgetVisible(self._tab_buttons[self._focus], 40, 0)

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
            self._keymap.setGeometry(self._keymap.parentWidget().rect())
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
            self._push_stage()

    def _push_stage(self):
        """Tell the page the free space in the middle column: centred on the
        column, from under the state label down to the arrows. The side panels
        differ in width, so the window's centre — where the sphere used to sit
        — was 41px right of the arrows, and a height-only size ran it into
        them once the window was maximised."""
        origin = self._orb_host.mapTo(self, QPoint(0, 0))
        # Through the window: the column and the orb's host are siblings in
        # the stack, and mapTo() is only meaningful toward an ancestor.
        column = self._centre.mapTo(self, QPoint(0, 0)) - origin
        top = (self._state_chip.mapTo(self, QPoint(0, self._state_chip.height())) - origin).y()
        bottom = (self._scrub_prev.mapTo(self, QPoint(0, 0)) - origin).y()
        x = column.x() + self._centre.width() / 2
        self._orb_js(f"window.orb && window.orb.setStage("
                     f"{x:g}, {(top + bottom) / 2:g}, {self._centre.width()}, {bottom - top})")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._push_stage)       # once the columns have moved

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
        return (self._status, self._r_today)

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
        self._status.time.setText(f"{hour}:{now.minute:02d} {suffix}")
        self._status.date.setText(now.strftime("%a, %b %d").upper())

    def _refresh_readouts(self):
        self._tick_clock()
        self._status.next.setText(_cached("calendar"))
        self._status.done.setText(self._done_today())
        self._r_today.set_value(_cached("tasks"))
        self._skills_btn.setText(f"SKILLS  {self._skills_online().replace(' of ', '/')}")
        self._refresh_rails()

    def _done_today(self) -> str:
        """What the Trust Ledger says El Fager did today: an action that was
        walked back does not count, and nor does the undo itself."""
        try:
            from core import ledger
            today = datetime.now().date().isoformat()
            done = [e for e in ledger.entries(limit=1000)
                    if str(e.get("ts", "")).startswith(today)
                    and e.get("category") != "revoked" and not e.get("revoked")]
        except Exception:
            return "—"
        return str(len(done))

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
        self._notice.setText(_breakable(message))
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
        self._show_window()
        self._clock.start()
        self._orb_js("window.orb && window.orb.start()")
        self._wake_attention("ready")

    def _show_window(self):
        """Show it where it was left, or centred above the taskbar at the
        default size. A saved spot that no longer fits the screen — a monitor
        unplugged, a resolution changed — is ignored rather than trusted."""
        if not self.isVisible():
            self.setMinimumSize(self.minimumSizeHint())
            area = QApplication.primaryScreen().availableGeometry()
            saved = _load_settings().get("cockpit_geometry")
            rect = QRect(*saved) if isinstance(saved, list) and len(saved) == 4 else QRect()
            if rect.isEmpty() or not area.contains(rect):
                width = max(self.minimumWidth(), min(_DEFAULT_SIZE[0], area.width() - 40))
                height = max(self.minimumHeight(), min(_DEFAULT_SIZE[1], area.height() - 40))
                rect = QRect(area.x() + (area.width() - width) // 2,
                             area.y() + (area.height() - height) // 2, width, height)
            self.setGeometry(rect)
            if _load_settings().get("cockpit_maximised"):
                self.showMaximized()
            else:
                self.showNormal()
        elif self.isMinimized():
            self.showNormal()
        self.raise_()
        self.activateWindow()

    def _save_window(self):
        settings = _load_settings()
        g = self.normalGeometry() if self.isMaximized() else self.geometry()
        settings["cockpit_geometry"] = [g.x(), g.y(), g.width(), g.height()]
        settings["cockpit_maximised"] = self.isMaximized()
        _save_settings(settings)

    def _toggle_maximised(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def changeEvent(self, event):
        # Minimised costs no GPU, the same as hidden; restored, it turns again.
        if event.type() == QEvent.Type.WindowStateChange:
            self._orb_js("window.orb && window.orb." +
                         ("stop()" if self.isMinimized() else "start()"))
        super().changeEvent(event)

    # ── Moving and resizing a frameless window ────────────────────────────

    def _edges_at(self, pos) -> Qt.Edge:
        if self.isMaximized():
            return Qt.Edge(0)
        m, edges = _RESIZE_MARGIN, Qt.Edge(0)
        if pos.x() <= m:
            edges |= Qt.Edge.LeftEdge
        if pos.x() >= self.width() - m:
            edges |= Qt.Edge.RightEdge
        if pos.y() <= m:
            edges |= Qt.Edge.TopEdge
        if pos.y() >= self.height() - m:
            edges |= Qt.Edge.BottomEdge
        return edges

    def mouseMoveEvent(self, event):
        edges = self._edges_at(event.position().toPoint())
        diagonal = (Qt.Edge.LeftEdge | Qt.Edge.TopEdge, Qt.Edge.RightEdge | Qt.Edge.BottomEdge)
        if edges in diagonal:
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif edges & (Qt.Edge.LeftEdge | Qt.Edge.RightEdge) and edges & (Qt.Edge.TopEdge | Qt.Edge.BottomEdge):
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        elif edges & (Qt.Edge.LeftEdge | Qt.Edge.RightEdge):
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif edges:
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        else:
            self.unsetCursor()
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        edges = self._edges_at(event.position().toPoint())
        if event.button() == Qt.MouseButton.LeftButton and edges and self.windowHandle():
            # The system does the resize, so it feels like any other window's.
            self.windowHandle().startSystemResize(edges)
            return
        super().mousePressEvent(event)

    def eventFilter(self, obj, event):
        if obj is getattr(self, "_title_bar", None):
            if (event.type() == QEvent.Type.MouseButtonPress
                    and event.button() == Qt.MouseButton.LeftButton and self.windowHandle()):
                # A system move, so Windows snap works on the drag.
                self.windowHandle().startSystemMove()
                return True
            if event.type() == QEvent.Type.MouseButtonDblClick:
                self._toggle_maximised()
                return True
        return super().eventFilter(obj, event)

    def wake_word_activate(self):
        """Voice wake blooms; a click-open is silent."""
        self.open()
        self._orb_js("window.orb && window.orb.bloom()")

    def _close(self):
        # The session's conversation ends with it: the next open starts empty.
        for layout in (self._reading_layout, self._tabs_layout):
            while layout.count():
                item = layout.takeAt(0)
                if item.widget() is not None:
                    item.widget().setParent(None)
        self._exchanges = []
        self._tab_buttons = []
        self._focus = -1
        self._scrub_value.setText("—")
        self._notice.setText("")
        self._clock.stop()
        self._ambient_timer.stop()      # no timers running behind the tray
        self._keymap.setVisible(False)
        self._orb_js("window.orb && window.orb.stop()")   # no idle GPU in tray
        if self.isVisible():
            self._save_window()
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
