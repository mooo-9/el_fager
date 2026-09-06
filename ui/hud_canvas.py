"""JARVIS voice HUD -- reactor orb, waveform arc, Iron Man corner brackets."""
import math
from datetime import datetime

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QWidget

_BG = QColor(4, 8, 15)
_CYAN = QColor(100, 200, 255)
_CYAN_DIM = QColor(100, 200, 255, 50)
_CYAN_MID = QColor(100, 200, 255, 140)
_TEXT = QColor(220, 220, 245)
_GREY = QColor(140, 140, 160)


class HudCanvas(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(480, 360)

        self._state = "idle"
        self._response_text = ""
        self._text_alpha = 0
        self._amplitude = 0.0
        self._data_items: list[str] = []

        # Pulse 0.0-1.0, drives orb glow
        self._orb_pulse = 0.0
        self._pulse_dir = 1

        # Waveform phase offset for animation
        self._wave_phase = 0.0

        # Started in showEvent — a hidden page in the stack repaints nothing,
        # so the 25 fps tick would just burn CPU.
        self._timer = QTimer(self)
        self._timer.setInterval(40)   # 25 fps
        self._timer.timeout.connect(self._tick)

    # -- Visibility ----------------------------------------------------------

    def showEvent(self, event):
        super().showEvent(event)
        self._timer.start()

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)

    # -- Public API ----------------------------------------------------------

    def set_state(self, state: str) -> None:
        self._state = state
        self.update()

    def set_response_text(self, text: str) -> None:
        self._response_text = text
        self._text_alpha = 255

    def set_amplitude(self, amp: float) -> None:
        self._amplitude = max(0.0, min(1.0, amp))

    def set_data_strip(self, items: list[str]) -> None:
        self._data_items = items[:5]
        self.update()

    # -- Animation tick ------------------------------------------------------

    def _tick(self):
        self._orb_pulse += 0.025 * self._pulse_dir
        if self._orb_pulse >= 1.0:
            self._pulse_dir = -1
        elif self._orb_pulse <= 0.0:
            self._pulse_dir = 1

        if self._text_alpha > 0:
            self._text_alpha = max(0, self._text_alpha - 2)

        if self._state in ("listening", "processing"):
            self._wave_phase += 0.15

        self.update()

    # -- Paint ---------------------------------------------------------------

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        p.fillRect(0, 0, w, h, _BG)
        self._paint_corner_brackets(p, w, h)
        self._paint_top_bar(p, w)
        self._paint_orb(p, w, h)
        self._paint_waveform(p, w, h)
        self._paint_response_text(p, w, h)
        self._paint_data_strip(p, w, h)

    def _paint_corner_brackets(self, p: QPainter, w: int, h: int):
        pen = QPen(_CYAN_DIM)
        pen.setWidth(2)
        p.setPen(pen)
        sz, mg = 28, 14
        for cx, cy, dx, dy in [
            (mg, mg, 1, 1),
            (w - mg, mg, -1, 1),
            (mg, h - mg, 1, -1),
            (w - mg, h - mg, -1, -1),
        ]:
            p.drawLine(cx, cy, cx + dx * sz, cy)
            p.drawLine(cx, cy, cx, cy + dy * sz)

    def _paint_top_bar(self, p: QPainter, w: int):
        font = QFont("Segoe UI", 9)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 3)
        font.setBold(True)
        p.setFont(font)
        p.setPen(QPen(_CYAN))
        p.drawText(22, 24, "EL FAGER")

        font2 = QFont("Consolas", 9)
        p.setFont(font2)
        p.setPen(QPen(_GREY))
        p.drawText(w // 2 - 28, 24, datetime.now().strftime("%H:%M:%S"))

        status_map = {
            "idle": "STANDBY",
            "listening": "LISTENING",
            "processing": "THINKING",
            "speaking": "SPEAKING",
        }
        status_text = status_map.get(self._state, "STANDBY")
        col = _CYAN if self._state != "idle" else QColor(70, 80, 100)
        p.setPen(QPen(col))
        p.drawText(w - 90, 24, status_text)

    def _paint_orb(self, p: QPainter, w: int, h: int):
        cx = w // 2
        cy = h // 2 - 15
        base_r = min(w, h) // 6
        pulse = self._orb_pulse

        p.setPen(Qt.PenStyle.NoPen)

        # Outer glow rings
        for i in range(5):
            r = base_r + 18 + i * 14
            alpha = int((45 - i * 7) * (0.5 + 0.5 * pulse))
            if alpha <= 0:
                continue
            pen = QPen(QColor(100, 200, 255, alpha))
            pen.setWidth(1)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(cx - r, cy - r, r * 2, r * 2)
        p.setPen(Qt.PenStyle.NoPen)

        # Core orb body
        core_alpha = int(60 + 40 * pulse)
        p.setBrush(QBrush(QColor(20, 55, 100, core_alpha)))
        p.drawEllipse(cx - base_r, cy - base_r, base_r * 2, base_r * 2)

        # Inner bright ring
        ring_r = base_r - 4
        pen_ring = QPen(QColor(100, 200, 255, int(180 + 60 * pulse)))
        pen_ring.setWidth(3)
        p.setPen(pen_ring)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(cx - ring_r, cy - ring_r, ring_r * 2, ring_r * 2)
        p.setPen(Qt.PenStyle.NoPen)

        # Centre dot
        dot_r = max(4, base_r // 5)
        p.setBrush(QBrush(QColor(150, 220, 255, int(200 + 50 * pulse))))
        p.drawEllipse(cx - dot_r, cy - dot_r, dot_r * 2, dot_r * 2)

    def _paint_waveform(self, p: QPainter, w: int, h: int):
        if self._state not in ("listening", "processing"):
            return

        cx = w // 2
        cy = h // 2 - 15
        base_r = min(w, h) // 6
        arc_r = base_r + 22

        amp = self._amplitude * 14 if self._state == "listening" else 6.0 * self._orb_pulse
        pen = QPen(QColor(100, 200, 255, 160))
        pen.setWidth(2)
        p.setPen(pen)

        steps = 80
        prev = None
        for i in range(steps + 1):
            # Bottom semicircle: angles from pi to 2*pi (bottom half)
            angle = math.pi + math.pi * i / steps
            wave = amp * math.sin(i * 0.25 + self._wave_phase)
            r = arc_r + wave
            x = int(cx + r * math.cos(angle))
            y = int(cy + r * math.sin(angle))
            if prev is not None:
                p.drawLine(prev[0], prev[1], x, y)
            prev = (x, y)

    def _paint_response_text(self, p: QPainter, w: int, h: int):
        if not self._response_text or self._text_alpha == 0:
            return
        font = QFont("Segoe UI", 11)
        p.setFont(font)
        p.setPen(QPen(QColor(220, 220, 245, self._text_alpha)))
        max_w = w - 80
        base_r = min(w, h) // 6
        cy = h // 2 - 15
        top_y = cy + base_r + 30
        p.drawText(40, top_y, max_w, h - top_y - 30,
                   Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignHCenter,
                   self._response_text)

    def _paint_data_strip(self, p: QPainter, w: int, h: int):
        if not self._data_items:
            return
        font = QFont("Consolas", 8)
        p.setFont(font)
        n = len(self._data_items)
        step = w // (n + 1)
        for i, item in enumerate(self._data_items):
            p.setPen(QPen(QColor(80, 160, 200, 180)))
            p.drawText((i + 1) * step - 35, h - 16, item)
