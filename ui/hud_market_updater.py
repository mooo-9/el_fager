"""
MarketUpdater — background QThread that fetches live price data every 60 s.

Fetches prices for the 4 Stocks-scene symbols (NVDA, AAPL, TSLA, MSFT) via
yfinance and reads the Alpaca paper account for real portfolio equity.

Emits market_ready(stocks, portfolio_value, day_pl, day_pct) once on startup
and then every 60 seconds.
"""
from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING

from PyQt6.QtCore import QThread, pyqtSignal

# The 4 DC-template slots and their bridge keys
_SYMBOLS = ["NVDA", "AAPL", "TSLA", "MSFT"]
_KEYS    = ["nv",   "aa",   "ts",   "ms"]
_INTERVAL = 60      # seconds between refreshes
_INIT_DELAY = 8     # wait for El Fager to finish booting before first fetch


class MarketUpdater(QThread):
    """
    Signals:
        market_ready(list[dict], float, float, float)
            stocks        – list of {sym, key, price, prevClose, shares}
            portfolio_value – total Alpaca account equity ($)
            day_pl        – P&L since yesterday's close ($)
            day_pct       – P&L as percentage (%)
    """
    market_ready = pyqtSignal(list, float, float, float)

    def run(self) -> None:
        # Let El Fager fully initialise before hitting external APIs
        for _ in range(_INIT_DELAY):
            if self.isInterruptionRequested():
                return
            time.sleep(1)

        while not self.isInterruptionRequested():
            try:
                self._fetch_and_emit()
            except Exception as e:
                print(f"[MarketUpdater] Error: {e}", flush=True)
            for _ in range(_INTERVAL):
                if self.isInterruptionRequested():
                    return
                time.sleep(1)

    def _fetch_and_emit(self) -> None:
        import yfinance as yf

        # Bulk download: period="5d" guarantees >= 2 trading days
        raw = yf.download(
            _SYMBOLS,
            period="5d",
            interval="1d",
            progress=False,
            auto_adjust=True,
            threads=True,
        )
        closes = raw["Close"]

        # Alpaca paper account: equity + positions
        pv: float = 0.0
        day_pl: float = 0.0
        positions: dict[str, int] = {}
        try:
            from alpaca.trading.client import TradingClient
            tc = TradingClient(
                os.getenv("ALPACA_API_KEY", ""),
                os.getenv("ALPACA_SECRET_KEY", ""),
                paper=True,
            )
            acct = tc.get_account()
            pv = float(acct.equity or 0)
            day_pl = pv - float(acct.last_equity or pv)
            for pos in tc.get_all_positions():
                try:
                    positions[pos.symbol] = int(float(pos.qty))
                except Exception:
                    pass
        except Exception as e:
            print(f"[MarketUpdater] Alpaca account: {e}", flush=True)

        day_pct = (day_pl / (pv - day_pl) * 100) if (pv - day_pl) > 1 else 0.0

        stocks: list[dict] = []
        for sym, key in zip(_SYMBOLS, _KEYS):
            try:
                col = closes[sym].dropna()
                if len(col) < 2:
                    continue
                price = round(float(col.iloc[-1]), 2)
                prev  = round(float(col.iloc[-2]), 2)
                stocks.append({
                    "sym": sym,
                    "key": key,
                    "price": price,
                    "prevClose": prev,
                    "shares": positions.get(sym, 0),
                })
            except Exception as e:
                print(f"[MarketUpdater] {sym}: {e}", flush=True)

        if stocks:
            self.market_ready.emit(
                stocks,
                round(pv, 2),
                round(day_pl, 2),
                round(day_pct, 2),
            )
            print(
                f"[MarketUpdater] {len(stocks)} symbols updated — "
                f"PV=${pv:,.0f}  DayPL={'+' if day_pl >= 0 else ''}{day_pl:,.0f}",
                flush=True,
            )
