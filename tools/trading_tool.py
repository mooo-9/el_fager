"""
Trading tool -- Alpaca-backed autonomous investment engine interface.
Data: data/trading_config.json, data/trades.json
"""
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Callable
from core import atomic

_CONFIG_PATH = Path("data/trading_config.json")
_TRADES_PATH = Path("data/trades.json")

_engine = None          # TradingEngine singleton
_speak_fn: Callable[[str], None] | None = None


def set_trading_speak_callback(fn: Callable[[str], None]) -> None:
    """Called from main.py at startup to wire in the TTS speak function."""
    global _speak_fn
    _speak_fn = fn


def _get_engine():
    global _engine
    if _engine is None:
        from core.trading_engine import TradingEngine
        _engine = TradingEngine(speak_fn=_speak_fn)
    return _engine


def _load_config() -> dict:
    if not _CONFIG_PATH.exists():
        return _default_config()
    try:
        return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return _default_config()


def _save_config(cfg: dict) -> None:
    _CONFIG_PATH.parent.mkdir(exist_ok=True)
    atomic.write(_CONFIG_PATH, json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


def _default_config() -> dict:
    return {
        "mode": "paper",
        "active_symbols": ["SPY", "QQQ", "AAPL", "NVDA", "MSFT"],
        "max_position_pct": 10,
        "stop_loss_pct": 8,
        "take_profit_pct": 15,
        "daily_loss_limit_pct": 5,
        "max_open_positions": 5,
        "cycle_interval_minutes": 15,
    }


def _load_trades() -> list:
    if not _TRADES_PATH.exists():
        return []
    try:
        return json.loads(_TRADES_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []


# -- Tool functions -------------------------------------------------------------

def start_trading_engine() -> str:
    if not _CONFIG_PATH.exists():
        _save_config(_default_config())
    engine = _get_engine()
    return engine.start()


def stop_trading_engine() -> str:
    return _get_engine().stop()


def get_trading_status() -> str:
    engine = _get_engine()
    cfg = _load_config()
    running = engine.is_running()
    mode = cfg.get("mode", "paper")
    symbols = cfg.get("active_symbols", [])
    trades = _load_trades()
    last_ts = trades[-1]["timestamp"][:16] if trades else "No trades yet"
    return (
        f"Trading engine: {'RUNNING' if running else 'STOPPED'}\n"
        f"Mode: {mode.upper()}\n"
        f"Watching: {', '.join(symbols)}\n"
        f"Last trade: {last_ts}"
    )


def get_trading_portfolio() -> str:
    api_key = os.getenv("ALPACA_API_KEY", "")
    secret = os.getenv("ALPACA_SECRET_KEY", "")
    if not api_key or api_key == "your_alpaca_key_here":
        return "Alpaca API keys not configured. Add ALPACA_API_KEY and ALPACA_SECRET_KEY to .env"
    try:
        from alpaca.trading.client import TradingClient
        cfg = _load_config()
        paper = cfg.get("mode", "paper") == "paper"
        client = TradingClient(api_key, secret, paper=paper)
        account = client.get_account()
        positions = client.get_all_positions()
        lines = [
            f"Portfolio: ${float(account.portfolio_value):,.2f}",
            f"Cash: ${float(account.cash):,.2f}",
            f"Mode: {cfg.get('mode', 'paper').upper()}",
            f"Open positions: {len(positions)}",
            "---",
        ]
        if not positions:
            lines.append("No open positions.")
        for p in positions:
            pnl = float(p.unrealized_pl)
            pnl_pct = float(p.unrealized_plpc) * 100
            lines.append(
                f"{p.symbol}: {p.qty} shares @ ${float(p.avg_entry_price):.2f}"
                f" | P&L: ${pnl:+.2f} ({pnl_pct:+.1f}%)"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"Error fetching portfolio: {e}"


def get_trade_history(n: int = 20) -> str:
    trades = _load_trades()
    if not trades:
        return "No trades recorded yet."
    recent = list(reversed(trades[-n:]))
    lines = [f"Last {len(recent)} trade(s):"]
    for t in recent:
        ts = t.get("timestamp", "?")[:16]
        side = t.get("side", "?").upper()
        qty = t.get("qty", 0)
        price = t.get("price", 0)
        symbol = t.get("symbol", "?")
        signal = t.get("signal", "?")
        lines.append(f"{ts} | {side} {qty:.3f} {symbol} @ ${price:.2f} | {signal}")
    return "\n".join(lines)


def get_trading_summary() -> str:
    trades = _load_trades()
    if not trades:
        return "No trades yet. Start the engine with start_trading_engine."
    today = datetime.now().date().isoformat()
    today_trades = [t for t in trades if t.get("timestamp", "")[:10] == today]
    lines = [
        f"Total trades all time: {len(trades)}",
        f"Today's trades: {len(today_trades)}",
        "",
        get_trading_portfolio(),
    ]
    return "\n".join(lines)


def set_risk_params(
    max_position_pct: float | None = None,
    stop_loss_pct: float | None = None,
    take_profit_pct: float | None = None,
    daily_loss_limit_pct: float | None = None,
    max_open_positions: int | None = None,
) -> str:
    cfg = _load_config()
    changes = []
    if max_position_pct is not None:
        cfg["max_position_pct"] = float(max_position_pct)
        changes.append(f"max position -> {max_position_pct}%")
    if stop_loss_pct is not None:
        cfg["stop_loss_pct"] = float(stop_loss_pct)
        changes.append(f"stop-loss -> {stop_loss_pct}%")
    if take_profit_pct is not None:
        cfg["take_profit_pct"] = float(take_profit_pct)
        changes.append(f"take-profit -> {take_profit_pct}%")
    if daily_loss_limit_pct is not None:
        cfg["daily_loss_limit_pct"] = float(daily_loss_limit_pct)
        changes.append(f"daily limit -> {daily_loss_limit_pct}%")
    if max_open_positions is not None:
        cfg["max_open_positions"] = int(max_open_positions)
        changes.append(f"max positions -> {max_open_positions}")
    if not changes:
        return "No parameters provided — nothing changed."
    _save_config(cfg)
    return "Risk params updated: " + ", ".join(changes)


def switch_to_paper_mode() -> str:
    cfg = _load_config()
    cfg["mode"] = "paper"
    _save_config(cfg)
    engine = _get_engine()
    if engine.is_running():
        engine.stop()
        engine.start()
    return "Switched to PAPER mode. All orders route to Alpaca sandbox (fake money)."


def switch_to_live_mode(confirmed: bool = False) -> str:
    if not confirmed:
        return (
            "WARNING: This will trade with REAL money. "
            "Say 'confirm live trading' to proceed."
        )
    cfg = _load_config()
    cfg["mode"] = "live"
    _save_config(cfg)
    engine = _get_engine()
    if engine.is_running():
        engine.stop()
        engine.start()
    return "Switched to LIVE mode. Real-money trading is now active."


def add_trading_symbol(symbol: str) -> str:
    symbol = symbol.upper().strip()
    cfg = _load_config()
    symbols = cfg.get("active_symbols", [])
    if symbol in symbols:
        return f"{symbol} is already in the trading watchlist."
    symbols.append(symbol)
    cfg["active_symbols"] = symbols
    _save_config(cfg)
    return f"Added {symbol}. Now tracking: {', '.join(symbols)}"


def remove_trading_symbol(symbol: str) -> str:
    symbol = symbol.upper().strip()
    cfg = _load_config()
    symbols = cfg.get("active_symbols", [])
    if symbol not in symbols:
        return f"{symbol} is not in the trading watchlist."
    symbols.remove(symbol)
    cfg["active_symbols"] = symbols
    _save_config(cfg)
    return f"Removed {symbol}. Now tracking: {', '.join(symbols) or 'nothing'}"
