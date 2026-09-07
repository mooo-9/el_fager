# JARVIS HUD + Trading Terminal UI — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two new visual modes to El Fager's overlay — a full-screen JARVIS voice HUD (Iron Man reactor orb + audio waveform + corner brackets) and a Bloomberg-style trading terminal (P&L chart + signal matrix + open positions + controls) — switchable with a single toggle button in the header.

**Architecture:** A `QStackedWidget` replaces the body of `OverlayWindow._card`, holding three pages: the existing voice bubble UI (page 0), a new `HudCanvas` JARVIS mode (page 1), and a new `TradingPanel` trading terminal (page 2). A mode-toggle button in the header cycles through all three modes. The two new panels live in separate files (`ui/hud_canvas.py`, `ui/trading_panel.py`) for testability. A `tests/ui/` package covers both.

**Tech Stack:** PyQt6 (already installed), QPainter for all custom rendering — no matplotlib, no OpenGL, no new pip installs.

## Global Constraints

- Python 3.14, PyQt6 only (no tkinter, no Qt5, no wx)
- `pygame-ce` (NOT `pygame`) already installed — UI code does NOT import it directly
- cp1252 safety: no U+2192 arrows, no emojis, no Arabic in any string that may be spoken or written to a response. All visible label text must be ASCII or cp1252-safe Latin characters
- No new pip installs — everything is rendered with QPainter or standard PyQt6 widgets
- JARVIS HUD background: `QColor(4, 8, 15)` — hex `#04080f`
- JARVIS HUD primary accent: `QColor(100, 200, 255)` — cyan
- Trading terminal background: `QColor(12, 12, 12)` — hex `#0c0c0c`
- Trading terminal accent: `QColor(0, 200, 100)` — terminal green
- Trading terminal font: `Consolas` (fallback: `Courier New`), monospaced
- All QTimer intervals must be integers (PyQt6 rejects float)
- Tests must NOT import PyQt6 at module level — all PyQt6 imports go inside test functions or fixtures, so pytest collection succeeds even without a display

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `ui/hud_canvas.py` | Create | `HudCanvas(QWidget)` — reactor orb, waveform arc, corner brackets, floating response text, clock top-bar, data strip |
| `ui/trading_panel.py` | Create | `TradingPanel(QWidget)` — P&L chart, signal matrix `QTableWidget`, positions list, trade log, START/STOP/BACKTEST buttons |
| `ui/overlay.py` | Modify | Wrap body in `QStackedWidget` (pages 0-2), add mode toggle to header, wire `HudCanvas.set_state()` to `on_state_update`, add `refresh_trading_panel()` called by timer |
| `tests/ui/__init__.py` | Create | Package marker (empty) |
| `tests/ui/conftest.py` | Create | Session-scoped `qapp` fixture so all UI tests share one `QApplication` |
| `tests/ui/test_hud_canvas.py` | Create | 10 tests: construction, state transitions, response text, amplitude clamping, data strip, waveform visibility |
| `tests/ui/test_trading_panel.py` | Create | 10 tests: construction, button presence, `set_signals()` populates table, `refresh()` with no trades file, `refresh()` with trades file |
| `tests/ui/test_overlay_modes.py` | Create | 6 tests: initial mode 0, cycle_mode advances, mode wraps at 3, mode name correct, stacked widget page count is 3, HudCanvas.set_state called on state_update in HUD mode |

---

### Task 1: HudCanvas — JARVIS reactor orb, waveform, corner brackets

**Files:**
- Create: `ui/hud_canvas.py`
- Create: `tests/ui/__init__.py`
- Create: `tests/ui/conftest.py`
- Create: `tests/ui/test_hud_canvas.py`

**Interfaces:**
- Produces: `HudCanvas(QWidget)` with:
  - `_state: str` — current state, default `"idle"`
  - `_response_text: str` — currently displayed response, default `""`
  - `_text_alpha: int` — 0–255 fade value for response text
  - `_amplitude: float` — 0.0–1.0 waveform height, default `0.0`
  - `_data_items: list[str]` — bottom data strip items, max 5
  - `set_state(state: str) -> None` — accepts `"idle"`, `"listening"`, `"processing"`, `"speaking"`; stores in `_state`; calls `self.update()`
  - `set_response_text(text: str) -> None` — stores in `_response_text`, sets `_text_alpha = 255`
  - `set_amplitude(amp: float) -> None` — clamps to [0.0, 1.0], stores in `_amplitude`
  - `set_data_strip(items: list[str]) -> None` — stores `items[:5]` in `_data_items`; calls `self.update()`

- [ ] **Step 1: Write the failing tests**

```python
# tests/ui/conftest.py
import pytest


@pytest.fixture(scope="session")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app
```

```python
# tests/ui/test_hud_canvas.py
import pytest


class TestHudCanvasConstruction:
    def test_widget_created(self, qapp):
        from ui.hud_canvas import HudCanvas
        w = HudCanvas()
        assert w is not None
        w.close()

    def test_default_state_is_idle(self, qapp):
        from ui.hud_canvas import HudCanvas
        w = HudCanvas()
        assert w._state == "idle"
        w.close()

    def test_minimum_size_set(self, qapp):
        from ui.hud_canvas import HudCanvas
        w = HudCanvas()
        assert w.minimumWidth() >= 400
        assert w.minimumHeight() >= 300
        w.close()

    def test_default_response_text_empty(self, qapp):
        from ui.hud_canvas import HudCanvas
        w = HudCanvas()
        assert w._response_text == ""
        assert w._text_alpha == 0
        w.close()


class TestHudCanvasState:
    def test_set_state_listening(self, qapp):
        from ui.hud_canvas import HudCanvas
        w = HudCanvas()
        w.set_state("listening")
        assert w._state == "listening"
        w.close()

    def test_set_state_speaking(self, qapp):
        from ui.hud_canvas import HudCanvas
        w = HudCanvas()
        w.set_state("speaking")
        assert w._state == "speaking"
        w.close()

    def test_set_response_text_sets_alpha(self, qapp):
        from ui.hud_canvas import HudCanvas
        w = HudCanvas()
        w.set_response_text("Analysis complete")
        assert w._response_text == "Analysis complete"
        assert w._text_alpha == 255
        w.close()

    def test_set_amplitude_clamps_high(self, qapp):
        from ui.hud_canvas import HudCanvas
        w = HudCanvas()
        w.set_amplitude(2.5)
        assert w._amplitude <= 1.0
        w.close()

    def test_set_amplitude_clamps_low(self, qapp):
        from ui.hud_canvas import HudCanvas
        w = HudCanvas()
        w.set_amplitude(-1.0)
        assert w._amplitude >= 0.0
        w.close()


class TestHudCanvasDataStrip:
    def test_set_data_strip_stored(self, qapp):
        from ui.hud_canvas import HudCanvas
        w = HudCanvas()
        w.set_data_strip(["SPY: +1.2%", "AAPL: -0.5%"])
        assert len(w._data_items) == 2
        assert w._data_items[0] == "SPY: +1.2%"
        w.close()

    def test_data_strip_capped_at_five(self, qapp):
        from ui.hud_canvas import HudCanvas
        w = HudCanvas()
        w.set_data_strip(["A", "B", "C", "D", "E", "F", "G"])
        assert len(w._data_items) == 5
        w.close()
```

- [ ] **Step 2: Run tests to confirm import failure**

```
cd C:\claude proj\el_fager
pytest tests/ui/test_hud_canvas.py -v
```
Expected: `ImportError: No module named 'ui.hud_canvas'`

- [ ] **Step 3: Create `tests/ui/__init__.py`**

Empty file — package marker only.

- [ ] **Step 4: Implement `ui/hud_canvas.py`**

```python
"""JARVIS voice HUD — reactor orb, waveform arc, Iron Man corner brackets."""
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

        self._timer = QTimer(self)
        self._timer.setInterval(40)   # 25 fps
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    # ── Public API ──────────────────────────────────────────────────────────

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

    # ── Animation tick ──────────────────────────────────────────────────────

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

    # ── Paint ───────────────────────────────────────────────────────────────

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
```

- [ ] **Step 5: Run tests**

```
cd C:\claude proj\el_fager
pytest tests/ui/test_hud_canvas.py -v
```
Expected: 10 PASSED

- [ ] **Step 6: Commit**

```
git add ui/hud_canvas.py tests/ui/__init__.py tests/ui/conftest.py tests/ui/test_hud_canvas.py
git commit -m "feat: add HudCanvas JARVIS voice HUD widget with reactor orb, waveform, corner brackets"
```

---

### Task 2: TradingPanel — Bloomberg trading terminal

**Files:**
- Create: `ui/trading_panel.py`
- Create: `tests/ui/test_trading_panel.py`

**Interfaces:**
- Consumes: `tests/ui/conftest.py::qapp` from Task 1
- Produces: `TradingPanel(QWidget)` with:
  - `_start_btn: QPushButton` — "START SCAN" button
  - `_stop_btn: QPushButton` — "STOP" button
  - `_backtest_btn: QPushButton` — "BACKTEST" button
  - `_signal_table: QTableWidget` — 4 columns: SYMBOL, DIRECTION, CONVICTION, STATUS
  - `_positions_label: QLabel` — shows open positions text
  - `_log_list: QListWidget` — recent trade log entries
  - `_equity_points: list[float]` — equity curve data points (used for chart)
  - `set_signals(signals: list[dict]) -> None` — populates `_signal_table`; each dict has keys `symbol: str`, `direction: str`, `conviction: float`, `status: str`
  - `refresh() -> None` — reads `data/trades.json` (catches all exceptions, never raises); updates `_equity_points` and `_log_list`; calls `self.update()`
  - `set_callback(on_start, on_stop, on_backtest) -> None` — wires button click handlers

- [ ] **Step 1: Write the failing tests**

```python
# tests/ui/test_trading_panel.py
import json
import pytest


class TestTradingPanelConstruction:
    def test_widget_created(self, qapp):
        from ui.trading_panel import TradingPanel
        w = TradingPanel()
        assert w is not None
        w.close()

    def test_start_button_present(self, qapp):
        from ui.trading_panel import TradingPanel
        w = TradingPanel()
        assert w._start_btn is not None
        assert "START" in w._start_btn.text().upper()
        w.close()

    def test_stop_button_present(self, qapp):
        from ui.trading_panel import TradingPanel
        w = TradingPanel()
        assert w._stop_btn is not None
        assert "STOP" in w._stop_btn.text().upper()
        w.close()

    def test_backtest_button_present(self, qapp):
        from ui.trading_panel import TradingPanel
        w = TradingPanel()
        assert w._backtest_btn is not None
        assert "BACKTEST" in w._backtest_btn.text().upper()
        w.close()

    def test_signal_table_has_four_columns(self, qapp):
        from ui.trading_panel import TradingPanel
        w = TradingPanel()
        assert w._signal_table.columnCount() == 4
        w.close()


class TestTradingPanelSignals:
    def test_set_signals_populates_rows(self, qapp):
        from ui.trading_panel import TradingPanel
        w = TradingPanel()
        signals = [
            {"symbol": "NVDA", "direction": "BUY", "conviction": 88.0, "status": "Pending"},
            {"symbol": "AAPL", "direction": "HOLD", "conviction": 55.0, "status": "Watching"},
        ]
        w.set_signals(signals)
        assert w._signal_table.rowCount() == 2
        assert w._signal_table.item(0, 0).text() == "NVDA"
        assert w._signal_table.item(1, 0).text() == "AAPL"
        w.close()

    def test_set_signals_empty_clears_table(self, qapp):
        from ui.trading_panel import TradingPanel
        w = TradingPanel()
        w.set_signals([{"symbol": "SPY", "direction": "BUY", "conviction": 70.0, "status": "OK"}])
        w.set_signals([])
        assert w._signal_table.rowCount() == 0
        w.close()


class TestTradingPanelRefresh:
    def test_refresh_no_trades_file(self, qapp, tmp_path, monkeypatch):
        from ui.trading_panel import TradingPanel
        # Point _TRADES_PATH at a nonexistent file
        monkeypatch.setattr("ui.trading_panel._TRADES_PATH", tmp_path / "no_trades.json")
        w = TradingPanel()
        w.refresh()   # must not raise
        assert w._equity_points == []
        w.close()

    def test_refresh_with_trades_populates_log(self, qapp, tmp_path, monkeypatch):
        from ui.trading_panel import TradingPanel
        trades_file = tmp_path / "trades.json"
        trades_file.write_text(json.dumps([
            {"symbol": "NVDA", "side": "buy", "qty": 0.5, "price": 120.0,
             "timestamp": "2026-06-23T10:00:00", "signal": "test", "agent": "test",
             "sl_price": 114.0, "tp_price": 134.4, "id": "abc"},
        ]))
        monkeypatch.setattr("ui.trading_panel._TRADES_PATH", trades_file)
        w = TradingPanel()
        w.refresh()
        assert w._log_list.count() >= 1
        w.close()

    def test_refresh_with_malformed_file(self, qapp, tmp_path, monkeypatch):
        from ui.trading_panel import TradingPanel
        trades_file = tmp_path / "trades.json"
        trades_file.write_text("not valid json{{{{")
        monkeypatch.setattr("ui.trading_panel._TRADES_PATH", trades_file)
        w = TradingPanel()
        w.refresh()   # must not raise
        assert w._equity_points == []
        w.close()


class TestTradingPanelCallback:
    def test_set_callback_start(self, qapp):
        from ui.trading_panel import TradingPanel
        w = TradingPanel()
        called = []
        w.set_callback(on_start=lambda: called.append("start"), on_stop=None, on_backtest=None)
        w._start_btn.click()
        assert "start" in called
        w.close()
```

- [ ] **Step 2: Run tests to confirm import failure**

```
cd C:\claude proj\el_fager
pytest tests/ui/test_trading_panel.py -v
```
Expected: `ImportError: No module named 'ui.trading_panel'`

- [ ] **Step 3: Implement `ui/trading_panel.py`**

```python
"""Bloomberg-style trading terminal panel."""
import json
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

_TRADES_PATH = Path("data/trades.json")

_BG = "#0c0c0c"
_GREEN = "#00c864"
_GREEN_DIM = "rgba(0,200,100,60)"
_GREY = "#5a5a6a"
_WHITE = "#d0d0e0"

_BASE_STYLE = f"""
    QWidget {{
        background-color: {_BG};
        color: {_WHITE};
    }}
    QLabel {{
        color: {_WHITE};
        font-family: Consolas, 'Courier New';
        font-size: 11px;
    }}
    QPushButton {{
        background-color: #1a1a1a;
        color: {_GREEN};
        border: 1px solid {_GREEN};
        border-radius: 3px;
        font-family: Consolas, 'Courier New';
        font-size: 11px;
        padding: 4px 12px;
        font-weight: bold;
    }}
    QPushButton:hover {{
        background-color: #002210;
        color: #00ff80;
    }}
    QTableWidget {{
        background-color: #111111;
        color: {_WHITE};
        border: 1px solid #2a2a2a;
        gridline-color: #1a1a1a;
        font-family: Consolas, 'Courier New';
        font-size: 10px;
        selection-background-color: #002210;
    }}
    QTableWidget QHeaderView::section {{
        background-color: #1a1a1a;
        color: {_GREEN};
        border: none;
        font-family: Consolas, 'Courier New';
        font-size: 10px;
        padding: 3px;
    }}
    QListWidget {{
        background-color: #111111;
        color: {_GREY};
        border: 1px solid #2a2a2a;
        font-family: Consolas, 'Courier New';
        font-size: 10px;
    }}
"""


class _ChartWidget(QWidget):
    """Simple equity-curve polyline chart."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(80)
        self._points: list[float] = []

    def set_points(self, points: list[float]) -> None:
        self._points = points
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor(10, 10, 10))

        # Zero line
        pen0 = QPen(QColor(50, 50, 60))
        pen0.setWidth(1)
        p.setPen(pen0)
        mid_y = h // 2
        p.drawLine(0, mid_y, w, mid_y)

        if len(self._points) < 2:
            p.setPen(QPen(QColor(80, 80, 100)))
            p.drawText(10, mid_y + 5, "No trade data")
            return

        lo = min(self._points)
        hi = max(self._points)
        span = hi - lo if hi != lo else 1.0
        margin = 8

        def _py(v: float) -> int:
            return int((h - margin) - (v - lo) / span * (h - margin * 2))

        def _px(i: int) -> int:
            return int(margin + i * (w - margin * 2) / (len(self._points) - 1))

        pen = QPen(QColor(0, 200, 100, 200))
        pen.setWidth(2)
        p.setPen(pen)
        for i in range(len(self._points) - 1):
            p.drawLine(_px(i), _py(self._points[i]),
                       _px(i + 1), _py(self._points[i + 1]))


class TradingPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(_BASE_STYLE)
        self._equity_points: list[float] = []
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(6)

        # Title bar
        title = QLabel("EL FAGER  //  TRADING TERMINAL")
        title.setStyleSheet(f"color: {_GREEN}; font-size: 12px; font-weight: bold; font-family: Consolas, 'Courier New'; letter-spacing: 2px;")
        root.addWidget(title)

        # P&L chart
        chart_label = QLabel("P&L CURVE")
        chart_label.setStyleSheet(f"color: {_GREY}; font-size: 9px; font-family: Consolas;")
        root.addWidget(chart_label)
        self._chart = _ChartWidget(self)
        root.addWidget(self._chart)

        # Signal matrix
        sig_label = QLabel("SIGNAL MATRIX")
        sig_label.setStyleSheet(f"color: {_GREY}; font-size: 9px; font-family: Consolas;")
        root.addWidget(sig_label)

        self._signal_table = QTableWidget(0, 4, self)
        self._signal_table.setHorizontalHeaderLabels(["SYMBOL", "DIRECTION", "CONVICTION", "STATUS"])
        self._signal_table.horizontalHeader().setStretchLastSection(True)
        self._signal_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._signal_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._signal_table.setMaximumHeight(120)
        root.addWidget(self._signal_table)

        # Positions + log row
        row = QHBoxLayout()
        row.setSpacing(6)

        pos_col = QVBoxLayout()
        pos_label = QLabel("OPEN POSITIONS")
        pos_label.setStyleSheet(f"color: {_GREY}; font-size: 9px;")
        pos_col.addWidget(pos_label)
        self._positions_label = QLabel("No open positions")
        self._positions_label.setWordWrap(True)
        self._positions_label.setStyleSheet(f"color: {_WHITE}; font-size: 10px; font-family: Consolas;")
        self._positions_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        pos_col.addWidget(self._positions_label)
        pos_col.addStretch()
        row.addLayout(pos_col)

        log_col = QVBoxLayout()
        log_label = QLabel("TRADE LOG")
        log_label.setStyleSheet(f"color: {_GREY}; font-size: 9px;")
        log_col.addWidget(log_label)
        self._log_list = QListWidget(self)
        self._log_list.setMaximumHeight(80)
        log_col.addWidget(self._log_list)
        row.addLayout(log_col)

        root.addLayout(row)

        # Controls
        ctrl = QHBoxLayout()
        ctrl.setSpacing(6)
        ctrl.addStretch()

        self._start_btn = QPushButton("START SCAN", self)
        self._stop_btn = QPushButton("STOP", self)
        self._backtest_btn = QPushButton("BACKTEST", self)

        for btn in (self._start_btn, self._stop_btn, self._backtest_btn):
            ctrl.addWidget(btn)

        root.addLayout(ctrl)

    # ── Public API ──────────────────────────────────────────────────────────

    def set_signals(self, signals: list[dict]) -> None:
        self._signal_table.setRowCount(0)
        for s in signals:
            row = self._signal_table.rowCount()
            self._signal_table.insertRow(row)
            self._signal_table.setItem(row, 0, QTableWidgetItem(str(s.get("symbol", ""))))
            self._signal_table.setItem(row, 1, QTableWidgetItem(str(s.get("direction", ""))))
            conv = s.get("conviction", 0.0)
            self._signal_table.setItem(row, 2, QTableWidgetItem(f"{conv:.0f}%"))
            self._signal_table.setItem(row, 3, QTableWidgetItem(str(s.get("status", ""))))

    def refresh(self) -> None:
        try:
            raw = _TRADES_PATH.read_text(encoding="utf-8")
            trades = json.loads(raw)
        except Exception:
            self._equity_points = []
            self._chart.set_points([])
            self.update()
            return

        # Build equity curve: cumulative entry value (simple proxy)
        cumulative = 0.0
        self._equity_points = []
        self._log_list.clear()

        for t in trades:
            val = float(t.get("qty", 0)) * float(t.get("price", 0))
            cumulative += val
            self._equity_points.append(cumulative)
            ts = str(t.get("timestamp", ""))[:16]
            sym = t.get("symbol", "?")
            side = t.get("side", "?").upper()
            price = t.get("price", 0)
            self._log_list.addItem(f"{ts}  {side} {sym} @ {price:.2f}")

        if len(self._equity_points) > 1:
            # Normalise to relative % change from first value
            base = self._equity_points[0] if self._equity_points[0] != 0 else 1.0
            self._equity_points = [(v - base) / base * 100 for v in self._equity_points]

        self._chart.set_points(self._equity_points)
        self.update()

    def set_callback(self, on_start=None, on_stop=None, on_backtest=None) -> None:
        if on_start is not None:
            self._start_btn.clicked.connect(on_start)
        if on_stop is not None:
            self._stop_btn.clicked.connect(on_stop)
        if on_backtest is not None:
            self._backtest_btn.clicked.connect(on_backtest)
```

- [ ] **Step 4: Run tests**

```
cd C:\claude proj\el_fager
pytest tests/ui/test_trading_panel.py -v
```
Expected: 10 PASSED

- [ ] **Step 5: Commit**

```
git add ui/trading_panel.py tests/ui/test_trading_panel.py
git commit -m "feat: add TradingPanel Bloomberg-style trading terminal widget"
```

---

### Task 3: Mode switching — wire both panels into OverlayWindow

**Files:**
- Modify: `ui/overlay.py`
- Create: `tests/ui/test_overlay_modes.py`

**Interfaces:**
- Consumes (Task 1): `HudCanvas` with `set_state(state)`, `set_response_text(text)`, `set_data_strip(items)`
- Consumes (Task 2): `TradingPanel` with `refresh()`, `set_callback(on_start, on_stop, on_backtest)`
- Produces in `OverlayWindow`:
  - `_mode: int` — 0 = voice bubbles, 1 = JARVIS HUD, 2 = trading terminal; default `0`
  - `_stack: QStackedWidget` — replaces body area; pages 0/1/2
  - `_hud: HudCanvas` — page 1
  - `_trading: TradingPanel` — page 2
  - `_mode_btn: QPushButton` — header button, text changes per mode: `"[V]"` when mode 0, `"[H]"` when mode 1, `"[T]"` when mode 2
  - `cycle_mode() -> None` — advances `_mode` by 1, wraps at 3, calls `_stack.setCurrentIndex(_mode)`, updates `_mode_btn` text
  - `mode_name -> str` — property returning `"voice"` / `"hud"` / `"trading"`

- [ ] **Step 1: Write the failing tests**

```python
# tests/ui/test_overlay_modes.py
import pytest


def _make_overlay(qapp):
    """Build a minimal OverlayWindow without a real wake listener or pipeline."""
    from unittest.mock import MagicMock
    from ui.overlay import OverlayWindow
    voice_in = MagicMock()
    brain = MagicMock()
    brain._offline_mode = False
    voice_out = MagicMock()
    memory = MagicMock()
    w = OverlayWindow(voice_in, brain, voice_out, memory)
    w.set_wake_listener(None)
    return w


class TestOverlayModes:
    def test_initial_mode_is_zero(self, qapp):
        w = _make_overlay(qapp)
        assert w._mode == 0
        w.close()

    def test_cycle_mode_advances(self, qapp):
        w = _make_overlay(qapp)
        w.cycle_mode()
        assert w._mode == 1
        w.close()

    def test_cycle_mode_wraps_at_three(self, qapp):
        w = _make_overlay(qapp)
        w.cycle_mode()   # 1
        w.cycle_mode()   # 2
        w.cycle_mode()   # 0
        assert w._mode == 0
        w.close()

    def test_mode_name_voice(self, qapp):
        w = _make_overlay(qapp)
        assert w.mode_name == "voice"
        w.close()

    def test_mode_name_hud(self, qapp):
        w = _make_overlay(qapp)
        w.cycle_mode()
        assert w.mode_name == "hud"
        w.close()

    def test_stacked_widget_has_three_pages(self, qapp):
        from PyQt6.QtWidgets import QStackedWidget
        w = _make_overlay(qapp)
        assert w._stack.count() == 3
        w.close()
```

- [ ] **Step 2: Run tests to confirm failure**

```
cd C:\claude proj\el_fager
pytest tests/ui/test_overlay_modes.py -v
```
Expected: 6 failures (`AttributeError: 'OverlayWindow' object has no attribute '_mode'`)

- [ ] **Step 3: Modify `ui/overlay.py` — add mode infrastructure**

The changes are all additive. The existing bubble-UI widgets are unchanged; they are wrapped into page 0 of the new `QStackedWidget`.

**3a. Add imports at the top of `ui/overlay.py` (after existing imports):**

```python
from ui.hud_canvas import HudCanvas
from ui.trading_panel import TradingPanel
```

**3b. Add `_mode` initialisation in `OverlayWindow.__init__` (after the existing instance-variable block, before `set_wake_listener` is called):**

```python
self._mode = 0
```

**3c. Replace `_build_ui` body** — wrap the inner layout in a `QStackedWidget`. The existing `_build_ui` builds everything into `inner` (a `QVBoxLayout` on `self._card`). We restructure so:

- Page 0 = a `QWidget` that contains all the existing voice UI (history scroll, transcript, status bar, input, action strip)
- Page 1 = `HudCanvas`
- Page 2 = `TradingPanel`

Find the section in `_build_ui` that currently does:

```python
inner = QVBoxLayout(self._card)
inner.setContentsMargins(16, 12, 16, 14)
inner.setSpacing(8)

# ── Header ──────────────────────────────────────────────────────
inner.addLayout(self._build_header())

# ── Separator ───────────────────────────────────────────────────
sep = QWidget()
sep.setFixedHeight(1)
sep.setStyleSheet("background-color: rgba(255,255,255,18);")
inner.addWidget(sep)

# ── Conversation history ─────────────────────────────────────────
self._history_scroll = ...
...
# ── Input + quick actions ────────────────────────────────────────
...
inner.addLayout(actions_row)
```

Replace the entire `_build_ui` method body with the version below. It is identical in behaviour except it inserts the `QStackedWidget` between the header and the rest, and moves the voice widgets into page 0.

```python
def _build_ui(self):
    from PyQt6.QtWidgets import QStackedWidget
    outer = QVBoxLayout(self)
    outer.setContentsMargins(10, 10, 10, 10)
    outer.setSpacing(0)

    self._card = QWidget(self)
    self._card.setObjectName("card")
    outer.addWidget(self._card)

    inner = QVBoxLayout(self._card)
    inner.setContentsMargins(16, 12, 16, 14)
    inner.setSpacing(8)

    # ── Header (shared across all modes) ───────────────────────────
    inner.addLayout(self._build_header())

    sep = QWidget()
    sep.setFixedHeight(1)
    sep.setStyleSheet("background-color: rgba(255,255,255,18);")
    inner.addWidget(sep)

    # ── Stacked pages ───────────────────────────────────────────────
    self._stack = QStackedWidget(self._card)
    inner.addWidget(self._stack)

    # Page 0: voice bubble UI
    self._voice_page = QWidget(self._stack)
    self._build_voice_page(self._voice_page)
    self._stack.addWidget(self._voice_page)

    # Page 1: JARVIS HUD
    self._hud = HudCanvas(self._stack)
    self._stack.addWidget(self._hud)

    # Page 2: trading terminal
    self._trading = TradingPanel(self._stack)
    self._trading.set_callback(
        on_start=lambda: self._start_pipeline(text_input="scan my watchlist"),
        on_stop=lambda: self._start_pipeline(text_input="pause trading"),
        on_backtest=None,   # Phase 5
    )
    self._stack.addWidget(self._trading)

    self._stack.setCurrentIndex(0)
```

**3d. Extract voice-page widgets into `_build_voice_page(self, page: QWidget)`** — move exactly the existing code (history scroll, transcript label, status bar, sep2, input row, actions row) into a new method that takes a parent `page` widget and builds the layout on it:

```python
def _build_voice_page(self, page: QWidget):
    from PyQt6.QtWidgets import QSizePolicy, QScrollArea
    layout = QVBoxLayout(page)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)

    # ── Conversation history ──────────────────────────────────────
    self._history_scroll = QScrollArea()
    self._history_scroll.setWidgetResizable(True)
    self._history_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    self._history_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    self._history_scroll.setSizePolicy(
        QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
    )
    self._history_scroll.setMinimumHeight(200)
    self._history_scroll.setStyleSheet("""
        QScrollArea {
            background: transparent;
            border: none;
        }
        QScrollBar:vertical {
            background: rgba(255,255,255,8);
            width: 5px;
            border-radius: 2px;
        }
        QScrollBar::handle:vertical {
            background: rgba(100,200,255,80);
            border-radius: 2px;
            min-height: 20px;
        }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
    """)

    self._history_container = QWidget()
    self._history_container.setStyleSheet("background: transparent;")
    self._history_layout = QVBoxLayout(self._history_container)
    self._history_layout.setContentsMargins(0, 4, 0, 4)
    self._history_layout.setSpacing(4)
    self._history_layout.addStretch()
    self._history_scroll.setWidget(self._history_container)
    layout.addWidget(self._history_scroll)

    # ── Active transcript ─────────────────────────────────────────
    self._transcript_label = QLabel("")
    self._transcript_label.setWordWrap(True)
    self._transcript_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    self._transcript_label.setStyleSheet("""
        color: rgba(180, 180, 195, 190);
        font-size: 12px;
        font-family: 'Segoe UI', sans-serif;
        padding: 2px 0;
    """)
    self._transcript_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
    self._transcript_label.setVisible(False)
    layout.addWidget(self._transcript_label)

    # ── Status bar ───────────────────────────────────────────────
    self._status_bar = QLabel("")
    self._status_bar.setStyleSheet("""
        color: rgba(100, 200, 255, 160);
        font-size: 10px;
        font-family: 'Segoe UI', sans-serif;
        padding: 0;
    """)
    self._status_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
    self._status_bar.setVisible(False)
    layout.addWidget(self._status_bar)

    # ── Separator ─────────────────────────────────────────────────
    sep2 = QWidget()
    sep2.setFixedHeight(1)
    sep2.setStyleSheet("background-color: rgba(255,255,255,12);")
    layout.addWidget(sep2)

    # ── Input + quick actions ─────────────────────────────────────
    input_row = QHBoxLayout()
    input_row.setSpacing(6)

    self._text_input = QLineEdit()
    self._text_input.setPlaceholderText("Type here or just speak...")
    self._text_input.setStyleSheet("""
        QLineEdit {
            background: rgba(255, 255, 255, 8);
            border: 1px solid rgba(255, 255, 255, 25);
            border-radius: 8px;
            color: rgba(240, 240, 248, 220);
            padding: 7px 12px;
            font-size: 13px;
            font-family: 'Segoe UI', sans-serif;
        }
        QLineEdit:focus {
            border: 1px solid rgba(100, 200, 255, 140);
            background: rgba(255, 255, 255, 12);
        }
        QLineEdit::placeholder { color: rgba(150, 150, 165, 140); }
    """)
    self._text_input.returnPressed.connect(self._on_text_entered)
    self._text_input.installEventFilter(self)
    input_row.addWidget(self._text_input)
    layout.addLayout(input_row)

    # ── Quick action strip ────────────────────────────────────────
    actions_row = QHBoxLayout()
    actions_row.setSpacing(4)
    actions_row.addStretch()

    _qa_style = """
        QPushButton {
            background: rgba(255,255,255,8);
            color: rgba(160,160,170,180);
            border: 1px solid rgba(255,255,255,15);
            border-radius: 6px;
            font-size: 13px;
            padding: 3px 8px;
            min-width: 28px;
        }
        QPushButton:hover {
            background: rgba(100,200,255,30);
            color: rgba(220,240,255,220);
            border: 1px solid rgba(100,200,255,60);
        }
    """

    self._mic_btn = QPushButton("[M]")
    self._mic_btn.setToolTip("Mute/unmute mic")
    self._mic_btn.setStyleSheet(_qa_style)
    self._mic_btn.clicked.connect(self._toggle_mute)
    actions_row.addWidget(self._mic_btn)

    stop_btn = QPushButton("[S]")
    stop_btn.setToolTip("Stop speaking")
    stop_btn.setStyleSheet(_qa_style)
    stop_btn.clicked.connect(self._stop_tts)
    actions_row.addWidget(stop_btn)

    clear_btn = QPushButton("[C]")
    clear_btn.setToolTip("Clear conversation history")
    clear_btn.setStyleSheet(_qa_style)
    clear_btn.clicked.connect(self._clear_history)
    actions_row.addWidget(clear_btn)

    settings_btn = QPushButton("[G]")
    settings_btn.setToolTip("Settings")
    settings_btn.setStyleSheet(_qa_style)
    settings_btn.clicked.connect(self._open_settings)
    actions_row.addWidget(settings_btn)

    layout.addLayout(actions_row)
```

Note: the emoji buttons (`🎤`, `⏹`, `🧹`, `⚙️`) in the original are replaced with ASCII tokens (`[M]`, `[S]`, `[C]`, `[G]`) for cp1252 safety in the button text. The tooltip strings (shown only in the OS-native tooltip popup, not spoken) may retain ASCII text.

**3e. Add mode-toggle button to `_build_header`** — in the `_build_header` method, before the existing `min_btn`, `minimize_btn`, `close_btn` block, add:

```python
self._mode_btn = QPushButton("[V]")
self._mode_btn.setFixedSize(28, 20)
self._mode_btn.setToolTip("Switch mode: Voice / HUD / Trading")
self._mode_btn.setStyleSheet(_btn)
self._mode_btn.clicked.connect(self.cycle_mode)
row.addWidget(self._mode_btn)
```

**3f. Add `cycle_mode` and `mode_name` to `OverlayWindow`:**

```python
def cycle_mode(self) -> None:
    self._mode = (self._mode + 1) % 3
    self._stack.setCurrentIndex(self._mode)
    labels = {0: "[V]", 1: "[H]", 2: "[T]"}
    self._mode_btn.setText(labels[self._mode])
    if self._mode == 2:
        self._trading.refresh()

@property
def mode_name(self) -> str:
    return {0: "voice", 1: "hud", 2: "trading"}[self._mode]
```

**3g. Wire HUD state updates** — in `on_state_update`, after the existing state logic, add at the bottom of the method:

```python
if self._mode == 1:
    self._hud.set_state(state)
    if response:
        self._hud.set_response_text(response)
```

**3h. Add trading refresh timer** — in `_setup_timers`, after the existing timer setup:

```python
self._trading_refresh_timer = QTimer(self)
self._trading_refresh_timer.setInterval(30000)   # 30 seconds
self._trading_refresh_timer.timeout.connect(self._refresh_trading_if_active)
self._trading_refresh_timer.start()

def _refresh_trading_if_active(self):
    if self._mode == 2:
        self._trading.refresh()
```

- [ ] **Step 4: Run ALL tests**

```
cd C:\claude proj\el_fager
pytest tests/ui/ -v
```
Expected: 26 PASSED (10 + 10 + 6)

Then confirm no regressions:

```
cd C:\claude proj\el_fager
pytest --tb=short -q
```
Expected: 196 passed (170 previous + 26 new)

- [ ] **Step 5: Commit**

```
git add ui/overlay.py tests/ui/test_overlay_modes.py
git commit -m "feat: add mode switching to OverlayWindow (voice/HUD/trading terminal)"
```

---

## Self-Review

**Spec coverage:**
- [x] Mode 1 JARVIS HUD (#04080f, reactor orb, waveform arc, corner brackets, floating text, top bar, data strip) — Task 1
- [x] Mode 2 Trading Terminal (#0c0c0c, green on black, monospaced, P&L chart, signal matrix, positions, log, START/STOP/BACKTEST) — Task 2
- [x] Toggle between modes with one button — Task 3
- [x] Both in PyQt6, no new deps — throughout

**Placeholder scan:** No TBD/TODO items — all code blocks are complete.

**Type consistency:**
- `HudCanvas.set_state(state: str)` defined Task 1, consumed Task 3 `_hud.set_state(state)` — match
- `TradingPanel.refresh()` defined Task 2, called Task 3 `self._trading.refresh()` — match
- `TradingPanel.set_callback(on_start, on_stop, on_backtest)` defined Task 2, called Task 3 — match
- `_TRADES_PATH` module-level constant in `trading_panel.py` monkeypatched in tests — match
- `OverlayWindow.cycle_mode()` and `.mode_name` defined Task 3, tested Task 3 — match
