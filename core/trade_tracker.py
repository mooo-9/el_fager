"""Syncs Alpaca closed-order fills back into trades.json as exit records."""
import json
import os
from pathlib import Path

_TRADES_PATH = Path("data/trades.json")
_CONFIG_PATH = Path("data/trading_config.json")


def _outcome_label(exit_price: float, tp_price: float, sl_price: float) -> str:
    """Classify a closed trade as TP or SL based on proximity to bracket targets."""
    dist_tp = abs(exit_price - tp_price)
    dist_sl = abs(exit_price - sl_price)
    if dist_tp <= dist_sl:
        return "TP"
    return "SL"


class TradeTracker:
    def _load_trades(self) -> list[dict]:
        if not _TRADES_PATH.exists():
            return []
        try:
            return json.loads(_TRADES_PATH.read_text(encoding="utf-8"))
        except Exception:
            return []

    def _save_trades(self, trades: list[dict]) -> None:
        _TRADES_PATH.parent.mkdir(exist_ok=True)
        _TRADES_PATH.write_text(
            json.dumps(trades, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def _fetch_closed_sells(
        self, api_key: str, secret: str, paper: bool
    ) -> list[dict]:
        """Return closed SELL fills sorted by filled_at ascending. Returns [] on any error."""
        try:
            from alpaca.trading.client import TradingClient
            from alpaca.trading.requests import GetOrdersRequest
            from alpaca.trading.enums import QueryOrderStatus, OrderSide

            client = TradingClient(api_key, secret, paper=paper)
            orders = client.get_orders(filter=GetOrdersRequest(
                status=QueryOrderStatus.CLOSED,
                limit=200,
            ))
            sells = []
            for o in orders:
                if str(o.side) != "OrderSide.SELL":
                    continue
                if o.filled_avg_price is None or o.filled_at is None:
                    continue
                sells.append({
                    "symbol": o.symbol,
                    "price": float(o.filled_avg_price),
                    "filled_at": str(o.filled_at),
                })
            sells.sort(key=lambda x: x["filled_at"])
            return sells
        except Exception:
            return []

    def sync(self) -> int:
        """Match closed Alpaca SELL fills to open trades. Returns count updated."""
        trades = self._load_trades()
        open_trades = [t for t in trades if not t.get("outcome") or t.get("outcome") == "OPEN"]
        if not open_trades:
            return 0

        # Load config for API keys and mode
        cfg: dict = {}
        if _CONFIG_PATH.exists():
            try:
                cfg = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
            except Exception:
                pass

        api_key = os.getenv("ALPACA_API_KEY", cfg.get("api_key", ""))
        secret = os.getenv("ALPACA_SECRET_KEY", cfg.get("api_secret", ""))
        paper = cfg.get("mode", "paper") == "paper"

        try:
            sells = self._fetch_closed_sells(api_key, secret, paper)
        except Exception:
            sells = []

        # Map symbol -> list of available sell fills (sorted by time)
        sell_map: dict[str, list[dict]] = {}
        for s in sells:
            sell_map.setdefault(s["symbol"], []).append(s)

        updated = 0
        for trade in trades:
            if trade.get("outcome") and trade["outcome"] != "OPEN":
                continue   # already closed

            symbol = trade.get("symbol", "")
            entry_ts = trade.get("timestamp", "")
            available = [
                s for s in sell_map.get(symbol, [])
                if s["filled_at"] > entry_ts
            ]
            if not available:
                trade["outcome"] = "OPEN"
                continue

            # Take the chronologically earliest matching sell
            fill = available[0]
            exit_price = fill["price"]
            entry_price = float(trade.get("price", exit_price) or exit_price)
            pnl_pct = (exit_price - entry_price) / entry_price * 100 if entry_price else 0.0

            trade["exit_price"] = exit_price
            trade["exit_time"] = fill["filled_at"]
            trade["pnl_pct"] = round(pnl_pct, 4)
            trade["outcome"] = _outcome_label(
                exit_price,
                float(trade.get("tp_price", exit_price + 1)),
                float(trade.get("sl_price", exit_price - 1)),
            )
            # Consume this fill so it is not matched to a second trade
            sell_map[symbol] = sell_map[symbol][1:]
            updated += 1

        self._save_trades(trades)
        return updated
