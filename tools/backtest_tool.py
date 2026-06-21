"""
Backtest tool -- 4 Jarvis voice commands for strategy backtesting.
Wraps core/backtester.py and persists results to data/backtest_results.json.
"""
import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

_RESULTS_PATH = Path("data/backtest_results.json")
_PLACEHOLDER = "your_alpaca_key_here"


def _api_keys() -> tuple[str, str]:
    return os.getenv("ALPACA_API_KEY", ""), os.getenv("ALPACA_SECRET_KEY", "")


def _keys_configured() -> bool:
    key, secret = _api_keys()
    return bool(key) and key != _PLACEHOLDER and bool(secret)


def _save_results(symbol: str, result) -> None:
    _RESULTS_PATH.parent.mkdir(exist_ok=True)
    data: dict = {}
    if _RESULTS_PATH.exists():
        try:
            data = json.loads(_RESULTS_PATH.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data[symbol] = {
        "total_return_pct": result.total_return_pct,
        "benchmark_return_pct": result.benchmark_return_pct,
        "win_rate_pct": result.win_rate_pct,
        "avg_gain_pct": result.avg_gain_pct,
        "avg_loss_pct": result.avg_loss_pct,
        "max_drawdown_pct": result.max_drawdown_pct,
        "sharpe_ratio": result.sharpe_ratio,
        "total_trades": result.total_trades,
        "winning_trades": result.winning_trades,
        "losing_trades": result.losing_trades,
    }
    import datetime
    data["_run_at"] = datetime.datetime.now().isoformat()
    _RESULTS_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def run_backtest(symbol: str = "SPY", days: int = 730) -> str:
    """Backtest the trading strategy on historical data for one symbol."""
    if not _keys_configured():
        return "Alpaca API keys not configured. Add ALPACA_API_KEY and ALPACA_SECRET_KEY to .env first."
    key, secret = _api_keys()
    from core.backtester import run_backtest as _run
    result = _run(symbol.upper(), days, key, secret)
    _save_results(symbol.upper(), result)
    if result.total_trades == 0:
        return (
            f"Backtest for {symbol.upper()} over {days} days completed with no trades fired. "
            f"Strategy signals may be too strict or data insufficient."
        )
    direction = "outperforms" if result.total_return_pct > result.benchmark_return_pct else "underperforms"
    years = days // 365
    return (
        f"Backtest complete for {symbol.upper()} over {years} year{'s' if years != 1 else ''}. "
        f"Strategy returned {result.total_return_pct:.1f}% vs buy-and-hold {result.benchmark_return_pct:.1f}% "
        f"-- strategy {direction} the benchmark. "
        f"Win rate {result.win_rate_pct:.0f}%, average gain {result.avg_gain_pct:.1f}%, "
        f"average loss {result.avg_loss_pct:.1f}%. "
        f"Max drawdown {result.max_drawdown_pct:.1f}%. Sharpe ratio {result.sharpe_ratio:.1f}. "
        f"{result.total_trades} trades executed. Results saved."
    )


def run_full_backtest() -> str:
    """Backtest the strategy across all active symbols and report combined results."""
    if not _keys_configured():
        return "Alpaca API keys not configured. Add ALPACA_API_KEY and ALPACA_SECRET_KEY to .env first."
    config_path = Path("data/trading_config.json")
    symbols = ["SPY", "QQQ", "AAPL", "NVDA", "MSFT"]
    if config_path.exists():
        try:
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
            symbols = cfg.get("active_symbols", symbols)
        except Exception:
            pass
    key, secret = _api_keys()
    from core.backtester import run_full_backtest as _run
    results = _run(symbols, 730, key, secret)
    for sym, result in results.items():
        _save_results(sym, result)
    if not results:
        return "Full backtest returned no results."
    best = max(results, key=lambda s: results[s].total_return_pct)
    worst = min(results, key=lambda s: results[s].total_return_pct)
    avg_sharpe = round(sum(r.sharpe_ratio for r in results.values()) / len(results), 1)
    avg_return = round(sum(r.total_return_pct for r in results.values()) / len(results), 1)
    return (
        f"Full backtest across {len(symbols)} symbols complete. "
        f"Best performer: {best} at {results[best].total_return_pct:.1f}% return. "
        f"Worst performer: {worst} at {results[worst].total_return_pct:.1f}% return. "
        f"Average return {avg_return:.1f}%, average Sharpe {avg_sharpe:.1f}. "
        f"Full breakdown saved."
    )


def get_backtest_results() -> str:
    """Return last saved backtest results as readable text."""
    if not _RESULTS_PATH.exists():
        return "No backtest results saved yet. Run run_backtest or run_full_backtest first."
    try:
        data = json.loads(_RESULTS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return "Backtest results file exists but could not be read."
    run_at = data.pop("_run_at", "unknown time")
    if not data:
        return "No symbol results in backtest file."
    lines = [f"Backtest results (run at {run_at}):"]
    for sym, r in data.items():
        direction = "outperforms" if r['total_return_pct'] > r['benchmark_return_pct'] else "underperforms"
        lines.append(
            f"  {sym}: strategy {r['total_return_pct']:.1f}% vs buy-and-hold "
            f"{r['benchmark_return_pct']:.1f}% ({direction}). "
            f"Win rate {r['win_rate_pct']:.0f}%, Sharpe {r['sharpe_ratio']:.1f}, "
            f"max drawdown {r['max_drawdown_pct']:.1f}%, {r['total_trades']} trades."
        )
    return "\n".join(lines)


def compare_to_buyhold(symbol: str) -> str:
    """Compare strategy return vs simply holding the symbol over the backtest period."""
    if not _RESULTS_PATH.exists():
        return f"No backtest results found. Run run_backtest('{symbol.upper()}') first."
    try:
        data = json.loads(_RESULTS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return "Could not read backtest results."
    sym = symbol.upper()
    if sym not in data:
        return f"No backtest results for {sym}. Run run_backtest('{sym}') first."
    r = data[sym]
    diff = round(r['total_return_pct'] - r['benchmark_return_pct'], 1)
    if diff > 0:
        verdict = (
            f"Strategy outperforms buy-and-hold by {diff} percentage points "
            f"-- active trading adds value on {sym}."
        )
    elif diff < 0:
        verdict = (
            f"Strategy underperforms buy-and-hold by {abs(diff)} percentage points "
            f"-- consider removing {sym} from the watchlist."
        )
    else:
        verdict = f"Strategy matches buy-and-hold exactly on {sym}."
    return (
        f"{sym}: strategy {r['total_return_pct']:.1f}% vs buy-and-hold "
        f"{r['benchmark_return_pct']:.1f}%. {verdict}"
    )
