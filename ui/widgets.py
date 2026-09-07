"""
El Fager — native visual widgets for the Command Center (Dawn palette).

All QPainter custom-painted (same technique as the overlay's horizon header
and state glyphs) — no QWebEngine, no external deps. Each widget is
self-contained and takes plain values; colors default to ui/theme.py.
"""

from math import cos, pi, sin

from PyQt6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer
from PyQt6.QtGui import (
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PyQt6.QtWidgets import QLayout, QSizePolicy, QWidget

from ui import theme, tokens


def _font(size: int, weight: int = QFont.Weight.Normal) -> QFont:
    f = QFont()
    f.setFamilies([tokens.FONT_UI, "Segoe UI"])
    f.setPointSize(size)
    f.setWeight(weight)
    return f


def _alpha(hex_color: str, alpha: int) -> QColor:
    c = QColor(hex_color)
    c.setAlpha(alpha)
    return c


class DayArc(QWidget):
    """The day's intake as a sunrise: a 180° arc over a hairline horizon.

    The gold sun rides the head of the fill and turns warn-amber once the
    target is passed. Per the motion spec this animates on first paint only —
    a 600ms sweep — and is static thereafter, so the card never breathes.
    """

    _SWEEP_MS = 600

    def __init__(self, unit: str = "kcal", parent=None):
        super().__init__(parent)
        self.setFixedSize(190, 116)
        self._value = 0
        self._target = 0
        self._swept = False          # first paint animates; later ones don't
        self._progress = 0.0
        self._timer: "QTimer | None" = None

    def set_values(self, value: float, target: float):
        self._value, self._target = round(value), round(target)
        if not self._swept:
            self._start_sweep()
        else:
            self.update()

    def _start_sweep(self):
        self._swept = True
        self._progress = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._elapsed = 0
        def step():
            self._elapsed += 16
            # swift-out easing, matching the design's mechanical curve
            t = min(1.0, self._elapsed / self._SWEEP_MS)
            self._progress = 1 - pow(1 - t, 3)
            self.update()
            if t >= 1.0 and self._timer is not None:
                self._timer.stop()
        self._timer.timeout.connect(step)
        self._timer.start()

    @property
    def _over(self) -> bool:
        return bool(self._target) and self._value > self._target

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy, r = w / 2, h - 22, w / 2 - 14

        # the horizon the sun rises over
        p.setPen(QPen(_alpha("#FFFFFF", 36), 1))
        p.drawLine(QPointF(6, cy), QPointF(w - 6, cy))

        arc_rect = QRectF(cx - r, cy - r, r * 2, r * 2)
        track = QPen(_alpha(theme.ACCENT, 34), 6)
        track.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(track)
        p.drawArc(arc_rect, 0, 180 * 16)

        frac = min(1.0, self._value / self._target) if self._target else 0.0
        frac *= self._progress if self._progress else 1.0
        head = QColor(theme.WARN if self._over else theme.SPEAKING)
        if frac > 0:
            fill = QPen(head, 6)
            fill.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(fill)
            p.drawArc(arc_rect, 180 * 16, -int(frac * 180 * 16))

            # the sun rides the head of the fill
            ang = pi - pi * frac
            sx, sy = cx + r * cos(ang), cy - r * sin(ang)
            p.setPen(Qt.PenStyle.NoPen)
            glow = QRadialGradient(sx, sy, 13)
            glow.setColorAt(0.0, _alpha(head.name(), 150))
            glow.setColorAt(1.0, _alpha(head.name(), 0))
            p.setBrush(glow)
            p.drawEllipse(QRectF(sx - 13, sy - 13, 26, 26))
            p.setBrush(head)
            p.drawEllipse(QRectF(sx - 4, sy - 4, 8, 8))

        p.setPen(QColor(theme.TEXT_PRIMARY))
        p.setFont(_font(15, QFont.Weight.DemiBold))
        p.drawText(QRectF(0, cy - 34, w, 24), Qt.AlignmentFlag.AlignCenter,
                   f"{self._value:,}")
        p.setPen(QColor(theme.WARN if self._over else theme.TEXT_MUTED))
        f = _font(7)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.4)
        p.setFont(f)
        p.drawText(QRectF(0, cy + 4, w, 14), Qt.AlignmentFlag.AlignCenter,
                   ("OVER BY " + f"{self._value - self._target:,}"
                    if self._over else f"OF {self._target:,}").upper())


class MacroBar(QWidget):
    """Thin rounded progress bar with a label and a cur / tgt readout."""

    def __init__(self, label: str, color: str, unit: str = "g", parent=None):
        super().__init__(parent)
        self.setFixedHeight(30)
        self.setMinimumWidth(120)
        self._label = label
        self._unit = unit
        self._color = QColor(color)
        self._cur = 0
        self._tgt = 0

    def set_values(self, cur: float, tgt: float):
        self._cur, self._tgt = round(cur), round(tgt)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QColor(theme.TEXT_SECONDARY))
        f = _font(8)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.5)
        p.setFont(f)
        p.drawText(QRectF(0, 0, self.width(), 14), Qt.AlignmentFlag.AlignLeft, self._label.upper())
        p.setPen(self._color)
        p.setFont(_font(9))
        p.drawText(
            QRectF(0, 0, self.width(), 14),
            Qt.AlignmentFlag.AlignRight,
            f"{self._cur} / {self._tgt}{self._unit}",
        )
        track = QRectF(0, self.height() - 8, self.width(), 5)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_alpha(theme.ACCENT, 24))
        p.drawRoundedRect(track, 2.5, 2.5)
        frac = min(1.0, self._cur / self._tgt) if self._tgt else 0.0
        if frac > 0:
            fill = QRectF(track)
            fill.setWidth(max(5.0, track.width() * frac))
            p.setBrush(self._color)
            p.drawRoundedRect(fill, 2.5, 2.5)


class Sparkline(QWidget):
    """Tiny polyline over N points with a soft fill under the line."""

    def __init__(self, color: str = theme.ACCENT, parent=None):
        super().__init__(parent)
        self.setFixedHeight(34)
        self.setMinimumWidth(80)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._color = QColor(color)
        self._points: list[float] = []

    def set_points(self, points: list[float]):
        self._points = list(points)
        self.update()

    def paintEvent(self, event):
        if len(self._points) < 2:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pad = 3.0
        w, h = self.width() - 2 * pad, self.height() - 2 * pad
        lo, hi = min(self._points), max(self._points)
        span = (hi - lo) or 1.0
        pts = [
            QPointF(
                pad + i * w / (len(self._points) - 1),
                pad + h - (v - lo) / span * h,
            )
            for i, v in enumerate(self._points)
        ]
        path = QPainterPath(pts[0])
        for pt in pts[1:]:
            path.lineTo(pt)
        fill = QPainterPath(path)
        fill.lineTo(pts[-1].x(), self.height())
        fill.lineTo(pts[0].x(), self.height())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_alpha(self._color.name(), 34))
        p.drawPath(fill)
        p.setPen(QPen(self._color, 1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)


class StatTile(QWidget):
    """Labeled metric tile: big value on top, small caption underneath."""

    def __init__(self, caption: str, parent=None):
        super().__init__(parent)
        self.setFixedHeight(44)
        self.setMinimumWidth(90)
        self._caption = caption
        self._value = "—"

    def set_value(self, text: str):
        self._value = text
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QColor(theme.TEXT_PRIMARY))
        p.setFont(_font(16, QFont.Weight.DemiBold))
        p.drawText(QRectF(0, 0, self.width(), 26), Qt.AlignmentFlag.AlignLeft, self._value)
        p.setPen(QColor(theme.TEXT_MUTED))
        f = _font(8)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.5)
        p.setFont(f)
        p.drawText(QRectF(0, 28, self.width(), 14), Qt.AlignmentFlag.AlignLeft, self._caption.upper())


class FlowLayout(QLayout):
    """Left-to-right layout that wraps when it runs out of width.

    Qt ships no such layout, and the Command Center's learned-fact and skill
    chips are variable-width pills that have to wrap like the design's row.
    """

    def __init__(self, parent=None, spacing: int = 8):
        super().__init__(parent)
        self._items: list = []
        self.setSpacing(spacing)
        self.setContentsMargins(0, 0, 0, 0)

    # QLayout plumbing
    def addItem(self, item):
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index):
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index):
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._lay_out(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._lay_out(rect, apply=True)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize(0, 0)
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size

    def _lay_out(self, rect: QRect, apply: bool) -> int:
        x, y, line_height = rect.x(), rect.y(), 0
        space = self.spacing()
        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width()
            if next_x > rect.right() and line_height > 0:
                x = rect.x()
                y += line_height + space
                next_x = x + hint.width()
                line_height = 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x + space
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y()


class StepMark(QWidget):
    """The step ledger's mark: a dot while running, a check when it lands,
    a cross when it doesn't.

    Painted rather than typed — no bundled face carries U+2713, and the mock
    draws the check as a path anyway. The mark differs by shape as well as by
    hue, because state is never signalled by colour alone.
    """

    def __init__(self, status: str, color: str, parent=None):
        super().__init__(parent)
        self.setFixedSize(12, 12)
        self._status = status
        self._color = QColor(color)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._status == "done":
            pen = QPen(self._color, 1.6)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            path = QPainterPath(QPointF(2.0, 6.4))
            path.lineTo(4.8, 9.0)
            path.lineTo(10.0, 3.2)
            p.drawPath(path)
        elif self._status == "failed":
            pen = QPen(self._color, 1.6)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawLine(QPointF(3, 3), QPointF(9, 9))
            p.drawLine(QPointF(9, 3), QPointF(3, 9))
        else:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(self._color)
            p.drawEllipse(QRectF(3.5, 3.5, 5, 5))


class FlowHost(QWidget):
    """A widget whose height follows the FlowLayout inside it.

    Qt only asks a widget for heightForWidth when its size policy says to,
    and a plain QWidget doesn't forward the question to its layout — without
    this the chip rows get one line of height and the rest is clipped.
    """

    def __init__(self, spacing: int = 8, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        self.flow = FlowLayout(self, spacing=spacing)
        policy = QSizePolicy(QSizePolicy.Policy.Preferred,
                             QSizePolicy.Policy.MinimumExpanding)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self.flow.heightForWidth(width)

    def sizeHint(self) -> QSize:
        width = self.width() or 240
        return QSize(width, self.heightForWidth(width))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.setMinimumHeight(self.heightForWidth(self.width()))

    def refresh(self):
        """Call after adding or removing chips so the height catches up."""
        self.setMinimumHeight(self.heightForWidth(self.width() or 240))
        self.updateGeometry()


class Chip(QWidget):
    """Small rounded pill: optional colored status dot + short text."""

    def __init__(self, text: str = "", dot: "str | None" = None, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._text = text
        self._dot = QColor(dot) if dot else None
        self._font = _font(9)
        self._dot_alpha = 255
        self._pulse_timer: "QTimer | None" = None
        self._pulse_phase = 0

    def set_text(self, text: str):
        self._text = text
        self.updateGeometry()
        self.update()

    def set_dot(self, color: "str | None"):
        self._dot = QColor(color) if color else None
        self.update()

    def start_pulse(self):
        """Softly pulse the dot (same timer approach as the overlay's glyphs)."""
        if self._pulse_timer is None:
            self._pulse_timer = QTimer(self)
            self._pulse_timer.setInterval(90)
            self._pulse_timer.timeout.connect(self._pulse_tick)
        self._pulse_phase = 0
        self._pulse_timer.start()

    def stop_pulse(self):
        if self._pulse_timer is not None:
            self._pulse_timer.stop()
        self._dot_alpha = 255
        self.update()

    def _pulse_tick(self):
        self._pulse_phase = (self._pulse_phase + 1) % 20
        self._dot_alpha = 120 + round(135 * abs(self._pulse_phase - 10) / 10)
        self.update()

    def sizeHint(self) -> QSize:
        from PyQt6.QtGui import QFontMetrics
        w = QFontMetrics(self._font).horizontalAdvance(self._text) + 18
        if self._dot is not None:
            w += 10
        return QSize(w, 18)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        p.setPen(QPen(_alpha(theme.ACCENT, 26), 1))
        p.setBrush(QColor(theme.BG_RAISED))
        p.drawRoundedRect(r, 9, 9)
        x = 9.0
        if self._dot is not None:
            dot = QColor(self._dot)
            dot.setAlpha(self._dot_alpha)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(dot)
            p.drawEllipse(QRectF(x - 2, self.height() / 2 - 3, 6, 6))
            x += 10
        p.setPen(QColor(theme.TEXT_SECONDARY))
        p.setFont(self._font)
        p.drawText(
            QRectF(x, 0, self.width() - x, self.height()),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            self._text,
        )
