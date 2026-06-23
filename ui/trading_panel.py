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
        title.setStyleSheet(
            f"color: {_GREEN}; font-size: 12px; font-weight: bold; "
            f"font-family: Consolas, 'Courier New'; letter-spacing: 2px;"
        )
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
        self._positions_label.setStyleSheet(
            f"color: {_WHITE}; font-size: 10px; font-family: Consolas;"
        )
        self._positions_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
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

    # -- Public API ----------------------------------------------------------

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
        import ui.trading_panel as _mod
        trades_path = _mod._TRADES_PATH
        try:
            raw = Path(trades_path).read_text(encoding="utf-8")
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
