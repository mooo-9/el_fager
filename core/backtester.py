"""
Backtesting engine — replays Alpaca hourly bars and simulates the trading strategy.
Pure simulation logic (_simulate, helpers) is free of API calls and fully unit-testable.
Alpaca imports are deferred inside _fetch_bars / run_backtest / run_full_backtest.
"""
from typing import NamedTuple

from core.signals import rsi, macd, classify_signal, SignalStrength
from core.risk_manager import calc_position_size, get_stop_loss_price, get_take_profit_price

_MIN_BARS = 100  # minimum history bars before signal computation begins


SymbolResult = NamedTuple('SymbolResult', [
    ('symbol', str),
    ('total_return_pct', float),
    ('benchmark_return_pct', float),
    ('win_rate_pct', float),
    ('avg_gain_pct', float),
    ('avg_loss_pct', float),
    ('max_drawdown_pct', float),
    ('sharpe_ratio', float),
    ('total_trades', int),
    ('winning_trades', int),
    ('losing_trades', int),
])


def _max_drawdown(values: list[float]) -> float:
    """Return max peak-to-trough drop as a positive percentage."""
    if len(values) < 2:
        return 0.0
    peak = values[0]
    max_dd = 0.0
    for v in values:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (peak - v) / peak * 100
            if dd > max_dd:
                max_dd = dd
    return max_dd


def _sharpe(values: list[float]) -> float:
    """Annualized Sharpe ratio from a bar-level portfolio value series."""
    if len(values) < 2:
        return 0.0
    returns = [
        (values[i] - values[i - 1]) / values[i - 1]
        for i in range(1, len(values))
        if values[i - 1] != 0
    ]
    if len(returns) < 2:
        return 0.0
    n = len(returns)
    mean_r = sum(returns) / n
    variance = sum((r - mean_r) ** 2 for r in returns) / (n - 1)
    std_r = variance ** 0.5
    if std_r == 0:
        return 0.0
    annualization = (252 * 6.5) ** 0.5  # hourly bars: 6.5 trading hours/day
    return round(mean_r / std_r * annualization, 2)


def _simulate(
    bars: list[dict],
    symbol: str,
    portfolio_value: float = 10_000.0,
) -> SymbolResult:
    """
    Pure simulation. bars is a chronological list of {open, high, low, close} dicts.
    No API calls. Fully unit-testable.

    Fill rule: buy at NEXT bar's open (pending_entry flag).
    Exit rule: check bar's low vs SL and bar's high vs TP each bar.
    """
    _empty = SymbolResult(
        symbol=symbol, total_return_pct=0.0, benchmark_return_pct=0.0,
        win_rate_pct=0.0, avg_gain_pct=0.0, avg_loss_pct=0.0,
        max_drawdown_pct=0.0, sharpe_ratio=0.0,
        total_trades=0, winning_trades=0, losing_trades=0,
    )
    if len(bars) <= _MIN_BARS:
        return _empty

    cash = portfolio_value
    open_pos: dict | None = None
    pending_entry = False
    trade_pnls: list[float] = []
    portfolio_values: list[float] = [portfolio_value]

    for i in range(_MIN_BARS, len(bars)):
        bar = bars[i]

        # Execute pending entry at this bar's open
        if pending_entry and open_pos is None:
            fill_price = bar['open']
            qty = calc_position_size(cash, fill_price)
            if qty > 0:
                cash -= qty * fill_price
                open_pos = {
                    'entry_price': fill_price,
                    'sl_price': get_stop_loss_price(fill_price),
                    'tp_price': get_take_profit_price(fill_price),
                    'qty': qty,
                }
            pending_entry = False

        # Check SL / TP
        if open_pos is not None:
            if bar['low'] <= open_pos['sl_price']:
                pnl = (open_pos['sl_price'] - open_pos['entry_price']) / open_pos['entry_price'] * 100
                cash += open_pos['qty'] * open_pos['sl_price']
                trade_pnls.append(pnl)
                open_pos = None
            elif bar['high'] >= open_pos['tp_price']:
                pnl = (open_pos['tp_price'] - open_pos['entry_price']) / open_pos['entry_price'] * 100
                cash += open_pos['qty'] * open_pos['tp_price']
                trade_pnls.append(pnl)
                open_pos = None

        # Check for new signal when flat and not the last bar
        if open_pos is None and not pending_entry and i < len(bars) - 1:
            window = [b['close'] for b in bars[i - _MIN_BARS:i]]
            rsi_val = rsi(window)
            macd_result = macd(window)
            signal = classify_signal(window, rsi_val, macd_result)
            if signal == SignalStrength.STRONG_BUY:
                pending_entry = True

        # Record portfolio value for metrics
        pos_val = open_pos['qty'] * bar['close'] if open_pos is not None else 0.0
        portfolio_values.append(cash + pos_val)

    # Close remaining open position at last bar's close
    if open_pos is not None:
        last_price = bars[-1]['close']
        pnl = (last_price - open_pos['entry_price']) / open_pos['entry_price'] * 100
        cash += open_pos['qty'] * last_price
        trade_pnls.append(pnl)

    # Compute final metrics
    total_trades = len(trade_pnls)
    winning = [p for p in trade_pnls if p > 0]
    losing = [p for p in trade_pnls if p <= 0]
    win_rate = len(winning) / total_trades * 100 if total_trades > 0 else 0.0
    avg_gain = sum(winning) / len(winning) if winning else 0.0
    avg_loss = abs(sum(losing) / len(losing)) if losing else 0.0

    final_value = portfolio_values[-1]
    total_return = (final_value - portfolio_value) / portfolio_value * 100
    benchmark_return = (bars[-1]['close'] - bars[0]['close']) / bars[0]['close'] * 100

    return SymbolResult(
        symbol=symbol,
        total_return_pct=round(total_return, 2),
        benchmark_return_pct=round(benchmark_return, 2),
        win_rate_pct=round(win_rate, 1),
        avg_gain_pct=round(avg_gain, 2),
        avg_loss_pct=round(avg_loss, 2),
        max_drawdown_pct=round(_max_drawdown(portfolio_values), 2),
        sharpe_ratio=_sharpe(portfolio_values),
        total_trades=total_trades,
        winning_trades=len(winning),
        losing_trades=len(losing),
    )


def _fetch_bars(symbol: str, days: int, api_key: str, secret_key: str) -> list[dict]:
    """Fetch hourly OHLCV bars from Alpaca for the past `days` days."""
    from datetime import datetime, timedelta, timezone
    from alpaca.data.historical.stock import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    client = StockHistoricalDataClient(api_key, secret_key)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    req = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame.Hour,
        start=start,
        end=end,
    )
    try:
        bars_resp = client.get_stock_bars(req)
        df = bars_resp.df
    except Exception:
        return []
    if df.empty:
        return []
    df = df.reset_index()
    if 'symbol' in df.columns:
        df = df[df['symbol'] == symbol]
    if 'timestamp' in df.columns:
        df = df.sort_values('timestamp')
    result = []
    for _, row in df.iterrows():
        result.append({
            'open': float(row['open']),
            'high': float(row['high']),
            'low': float(row['low']),
            'close': float(row['close']),
        })
    return result


def run_backtest(symbol: str, days: int, api_key: str, secret_key: str) -> SymbolResult:
    """Fetch bars and simulate the strategy for one symbol."""
    return _simulate(_fetch_bars(symbol, days, api_key, secret_key), symbol)


def run_full_backtest(
    symbols: list[str],
    days: int,
    api_key: str,
    secret_key: str,
) -> dict[str, SymbolResult]:
    """Run backtest for each symbol and return a mapping of symbol -> SymbolResult."""
    return {sym: _simulate(_fetch_bars(sym, days, api_key, secret_key), sym) for sym in symbols}
