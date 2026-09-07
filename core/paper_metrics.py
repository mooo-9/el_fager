"""Computes paper-trading gate criteria from completed trades in trades.json."""
import json
import math
from pathlib import Path

from core.backtester import _max_drawdown

_TRADES_PATH = Path("data/trades.json")

# Gate thresholds
# Win rate is NOT a gate criterion: with ~2:1 R:R (avg gain ~11%, avg loss ~5%) the
# breakeven win rate is ~33%, so a 45% win rate is already healthy. Profit factor
# and Sharpe capture profitability more precisely than a fixed win-rate floor.
_MIN_TRADES = 30
_MIN_SHARPE = 1.0
_MAX_DRAWDOWN = 15.0
_MIN_PROFIT_FACTOR = 1.3


def _sharpe(returns: list[float]) -> float:
    """Annualised Sharpe from per-trade returns. Returns 0.0 if fewer than 5 data points."""
    if len(returns) < 5:
        return 0.0
    n = len(returns)
    mean = sum(returns) / n
    variance = sum((r - mean) ** 2 for r in returns) / n
    std = math.sqrt(variance)
    if std == 0.0:
        return 0.0
    # Annualise assuming ~252 trading days, treating each trade as one day
    return (mean / std) * math.sqrt(min(n, 252))


class PaperMetrics:
    def _load_completed(self) -> list[dict]:
        """Return only trades with a final outcome (TP or SL)."""
        if not _TRADES_PATH.exists():
            return []
        try:
            trades = json.loads(_TRADES_PATH.read_text(encoding="utf-8"))
        except Exception:
            return []
        return [t for t in trades if t.get("outcome") in ("TP", "SL")]

    def compute(self) -> dict:
        completed = self._load_completed()
        n = len(completed)

        if n == 0:
            return {
                "total_completed": 0,
                "win_rate": 0.0,
                "sharpe": 0.0,
                "max_drawdown": 0.0,
                "profit_factor": 0.0,
                "gate_pass": False,
            }

        returns = [float(t.get("pnl_pct") or 0.0) for t in completed]
        wins = [r for r in returns if r > 0]
        losses = [r for r in returns if r <= 0]

        win_rate = len(wins) / n * 100.0
        sharpe = _sharpe(returns)

        # Equity curve: start at 100, compound each trade return
        equity = [100.0]
        for r in returns:
            equity.append(equity[-1] * (1 + r / 100.0))
        drawdown = _max_drawdown(equity)

        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0.0

        gate_pass = (
            n >= _MIN_TRADES
            and sharpe >= _MIN_SHARPE
            and drawdown <= _MAX_DRAWDOWN
            and profit_factor >= _MIN_PROFIT_FACTOR
        )

        return {
            "total_completed": n,
            "win_rate": round(win_rate, 2),
            "sharpe": round(sharpe, 3),
            "max_drawdown": round(drawdown, 2),
            "profit_factor": round(profit_factor, 3),
            "gate_pass": gate_pass,
        }

    def gate_summary(self) -> str:
        m = self.compute()
        lines = [
            f"Paper trading gate check ({m['total_completed']}/{_MIN_TRADES} trades):",
            f"  Win rate:      {m['win_rate']:.1f}% (informational)",
            f"  Sharpe ratio:  {m['sharpe']:.2f} (need {_MIN_SHARPE})",
            f"  Max drawdown:  {m['max_drawdown']:.1f}% (limit {_MAX_DRAWDOWN}%)",
            f"  Profit factor: {m['profit_factor']:.2f} (need {_MIN_PROFIT_FACTOR})",
        ]
        if m["gate_pass"]:
            lines.append(
                "ALL CRITERIA MET. Ready to trade real money. "
                "Say 'confirm real trading' to activate."
            )
        else:
            lines.append("NOT YET -- keep paper trading.")
        return "\n".join(lines)
