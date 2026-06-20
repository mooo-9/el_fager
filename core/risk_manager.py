"""
Risk guardrails for the trading engine.
All rules enforced before any order reaches Alpaca.
Config is re-read on every call so voice-command changes take effect immediately.
"""
import json
from pathlib import Path

_CONFIG_PATH = Path("data/trading_config.json")

_DEFAULTS = {
    "max_position_pct": 10,
    "stop_loss_pct": 8,
    "take_profit_pct": 15,
    "daily_loss_limit_pct": 5,
    "max_open_positions": 5,
}


def _load_config() -> dict:
    if not _CONFIG_PATH.exists():
        return dict(_DEFAULTS)
    try:
        return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return dict(_DEFAULTS)


def can_open_position(open_positions_count: int) -> tuple[bool, str]:
    """Return (allowed, reason). Checks only position count — caller checks symbol duplication."""
    cfg = _load_config()
    max_pos = cfg.get("max_open_positions", _DEFAULTS["max_open_positions"])
    if open_positions_count >= max_pos:
        return False, f"Max positions reached ({max_pos})"
    return True, "ok"


def calc_position_size(portfolio_value: float, price_per_share: float) -> float:
    """Return fractional qty capped at max_position_pct% of portfolio_value."""
    cfg = _load_config()
    max_pct = cfg.get("max_position_pct", _DEFAULTS["max_position_pct"]) / 100.0
    max_dollars = portfolio_value * max_pct
    return round(max_dollars / price_per_share, 6)


def get_stop_loss_price(entry_price: float) -> float:
    """Return stop price (entry * (1 - stop_loss_pct/100))."""
    cfg = _load_config()
    pct = cfg.get("stop_loss_pct", _DEFAULTS["stop_loss_pct"]) / 100.0
    return round(entry_price * (1.0 - pct), 2)


def get_take_profit_price(entry_price: float) -> float:
    """Return take-profit limit price (entry * (1 + take_profit_pct/100))."""
    cfg = _load_config()
    pct = cfg.get("take_profit_pct", _DEFAULTS["take_profit_pct"]) / 100.0
    return round(entry_price * (1.0 + pct), 2)


def is_daily_limit_hit(portfolio_value: float, day_open_value: float) -> bool:
    """True when portfolio has dropped >= daily_loss_limit_pct% from day_open_value."""
    if day_open_value <= 0:
        return False
    cfg = _load_config()
    limit_pct = cfg.get("daily_loss_limit_pct", _DEFAULTS["daily_loss_limit_pct"]) / 100.0
    drop = (day_open_value - portfolio_value) / day_open_value
    return drop >= limit_pct
