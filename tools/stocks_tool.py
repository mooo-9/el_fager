"""
Stocks tool — real-time market data, portfolio tracking, watchlist, price alerts.
Uses yfinance for market data.
Data: data/watchlist.json, data/portfolio.json, data/price_alerts.json
"""

import json
from datetime import datetime
from pathlib import Path
from core import atomic

_WATCHLIST_PATH   = Path("data/watchlist.json")
_PORTFOLIO_PATH   = Path("data/portfolio.json")
_ALERTS_PATH      = Path("data/price_alerts.json")

_MARKET_INDICES = {
    "S&P 500":   "^GSPC",
    "NASDAQ":    "^IXIC",
    "Dow Jones": "^DJI",
    "EGX30":     "^CASE30",
    "Gold":      "GC=F",
    "Oil (WTI)": "CL=F",
    "Bitcoin":   "BTC-USD",
    "USD/EGP":   "USDEGP=X",
}


# ── Data helpers ──────────────────────────────────────────────────────────────

def _load(path: Path, default) -> dict | list:
    if not path.exists():
        return default() if callable(default) else default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default() if callable(default) else default


def _save(path: Path, data) -> None:
    path.parent.mkdir(exist_ok=True)
    atomic.write(path, json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ── yfinance helpers ──────────────────────────────────────────────────────────

def _fetch(symbol: str) -> dict:
    """Return a flat dict of the most useful fields for a symbol. Never raises."""
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol.upper())
        info   = ticker.fast_info
        full   = {}
        try:
            full = ticker.info
        except Exception:
            pass

        price  = getattr(info, "last_price",       None) or full.get("currentPrice") or full.get("regularMarketPrice")
        prev   = getattr(info, "previous_close",   None) or full.get("previousClose")
        high52 = getattr(info, "year_high",        None) or full.get("fiftyTwoWeekHigh")
        low52  = getattr(info, "year_low",         None) or full.get("fiftyTwoWeekLow")
        volume = getattr(info, "three_month_average_volume", None) or full.get("averageVolume")
        mktcap = full.get("marketCap")
        pe     = full.get("trailingPE")
        name   = full.get("longName") or full.get("shortName") or symbol.upper()
        curr   = full.get("currency", "USD")

        change     = (price - prev) if (price and prev) else None
        change_pct = (change / prev * 100) if (change is not None and prev) else None

        return {
            "symbol":     symbol.upper(),
            "name":       name,
            "price":      price,
            "prev_close": prev,
            "change":     change,
            "change_pct": change_pct,
            "high_52w":   high52,
            "low_52w":    low52,
            "volume":     volume,
            "market_cap": mktcap,
            "pe":         pe,
            "currency":   curr,
            "ok":         price is not None,
        }
    except Exception as e:
        return {"symbol": symbol.upper(), "ok": False, "error": str(e)}


def _price_line(d: dict) -> str:
    """One-line price summary for a ticker dict."""
    if not d.get("ok"):
        return f"{d['symbol']}: unavailable"
    price  = d["price"]
    curr   = d["currency"]
    chg    = d.get("change")
    pct    = d.get("change_pct")
    sign   = "+" if chg and chg >= 0 else ""
    chg_s  = f"  {sign}{chg:+.2f} ({sign}{pct:.2f}%)" if chg is not None else ""
    return f"{d['symbol']:>10}  {price:>10.2f} {curr}{chg_s}"


# ── Public functions ──────────────────────────────────────────────────────────

def get_stock_price(symbol: str) -> str:
    """Current price + day change for a single ticker."""
    d = _fetch(symbol)
    if not d["ok"]:
        return f"Could not fetch data for {symbol}. Check the ticker symbol and try again."
    lines = [f"{d['name']} ({d['symbol']}):"]
    curr  = d["currency"]
    lines.append(f"  Price:    {d['price']:.2f} {curr}")
    if d.get("change") is not None:
        sign = "+" if d["change"] >= 0 else ""
        lines.append(f"  Change:   {sign}{d['change']:.2f}  ({sign}{d['change_pct']:.2f}%)")
    if d.get("prev_close"):
        lines.append(f"  Prev:     {d['prev_close']:.2f} {curr}")
    return "\n".join(lines)


def get_stock_info(symbol: str) -> str:
    """Detailed stock info: price, 52-week range, P/E, market cap, volume."""
    d = _fetch(symbol)
    if not d["ok"]:
        return f"Could not fetch data for {symbol}."
    lines = [f"{d['name']} ({d['symbol']}) — {d['currency']}:"]
    if d.get("price"):
        sign = "+" if (d.get("change") or 0) >= 0 else ""
        chg_s = f"  {sign}{d['change']:.2f} ({sign}{d['change_pct']:.2f}%)" if d.get("change") else ""
        lines.append(f"  Price:      {d['price']:.2f}{chg_s}")
    if d.get("high_52w") and d.get("low_52w"):
        lines.append(f"  52w range:  {d['low_52w']:.2f} - {d['high_52w']:.2f}")
    if d.get("pe"):
        lines.append(f"  P/E ratio:  {d['pe']:.1f}")
    if d.get("market_cap"):
        mc = d["market_cap"]
        if mc >= 1e12:
            mc_s = f"{mc/1e12:.2f}T"
        elif mc >= 1e9:
            mc_s = f"{mc/1e9:.2f}B"
        elif mc >= 1e6:
            mc_s = f"{mc/1e6:.2f}M"
        else:
            mc_s = f"{mc:,.0f}"
        lines.append(f"  Market cap: {mc_s} {d['currency']}")
    if d.get("volume"):
        lines.append(f"  Avg volume: {d['volume']:,.0f}")
    return "\n".join(lines)


def market_overview() -> str:
    """Live snapshot of major indices: S&P500, NASDAQ, DJI, EGX30, Gold, Oil, BTC, USD/EGP."""
    lines = ["Market overview:"]
    for label, sym in _MARKET_INDICES.items():
        d = _fetch(sym)
        if d.get("ok") and d.get("price"):
            price = d["price"]
            curr  = d["currency"]
            chg_s = ""
            if d.get("change_pct") is not None:
                sign  = "+" if d["change_pct"] >= 0 else ""
                chg_s = f"  {sign}{d['change_pct']:.2f}%"
            lines.append(f"  {label:<12}  {price:>12,.2f} {curr}{chg_s}")
        else:
            lines.append(f"  {label:<12}  unavailable")
    return "\n".join(lines)


def get_stock_news(symbol: str) -> str:
    """Recent news headlines for a stock."""
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol.upper())
        news   = ticker.news
        if not news:
            return f"No recent news found for {symbol}."
        lines = [f"News for {symbol.upper()}:"]
        for i, item in enumerate(news[:6], 1):
            title = item.get("title", "No title")
            src   = item.get("publisher", "")
            ts    = item.get("providerPublishTime", 0)
            date  = datetime.fromtimestamp(ts).strftime("%b %d") if ts else ""
            lines.append(f"  {i}. [{date}] {title}  — {src}")
        return "\n".join(lines)
    except Exception as e:
        return f"Could not fetch news for {symbol}: {e}"


def add_to_watchlist(symbol: str, notes: str = "") -> str:
    """Add a stock to Mo's watchlist."""
    data = _load(_WATCHLIST_PATH, list)
    sym  = symbol.upper()
    for item in data:
        if item["symbol"] == sym:
            item["notes"] = notes
            _save(_WATCHLIST_PATH, data)
            return f"{sym} already in watchlist — notes updated."
    d = _fetch(sym)
    name = d.get("name", sym) if d.get("ok") else sym
    data.append({"symbol": sym, "name": name, "notes": notes, "added": datetime.now().strftime("%Y-%m-%d")})
    _save(_WATCHLIST_PATH, data)
    return f"{sym} ({name}) added to watchlist."


def remove_from_watchlist(symbol: str) -> str:
    data   = _load(_WATCHLIST_PATH, list)
    before = len(data)
    data   = [i for i in data if i["symbol"] != symbol.upper()]
    if len(data) == before:
        return f"{symbol.upper()} not in watchlist."
    _save(_WATCHLIST_PATH, data)
    return f"{symbol.upper()} removed from watchlist."


def list_watchlist() -> str:
    data = _load(_WATCHLIST_PATH, list)
    if not data:
        return "Watchlist is empty. Say 'add AAPL to my watchlist' to start."
    lines = ["Watchlist:"]
    for item in data:
        d = _fetch(item["symbol"])
        line = "  " + _price_line(d)
        if item.get("notes"):
            line += f"  [{item['notes']}]"
        lines.append(line)
    return "\n".join(lines)


def add_holding(symbol: str, shares, avg_price, currency: str = "USD") -> str:
    """Add or update a position in Mo's portfolio."""
    data = _load(_PORTFOLIO_PATH, dict)
    sym  = symbol.upper()
    data[sym] = {
        "symbol":    sym,
        "shares":    float(shares),
        "avg_price": float(avg_price),
        "currency":  currency.upper(),
        "added":     data.get(sym, {}).get("added", datetime.now().strftime("%Y-%m-%d")),
    }
    _save(_PORTFOLIO_PATH, data)
    cost = float(shares) * float(avg_price)
    return f"Portfolio: {float(shares):g} shares of {sym} @ {float(avg_price):.2f} {currency.upper()} (cost basis: {cost:,.2f})."


def remove_holding(symbol: str) -> str:
    data = _load(_PORTFOLIO_PATH, dict)
    sym  = symbol.upper()
    if sym not in data:
        return f"{sym} not in portfolio."
    del data[sym]
    _save(_PORTFOLIO_PATH, data)
    return f"{sym} removed from portfolio."


def portfolio_summary() -> str:
    """Portfolio with live prices, current value, unrealised P&L."""
    data = _load(_PORTFOLIO_PATH, dict)
    if not data:
        return "Portfolio is empty. Say 'I own 10 shares of AAPL at 180 USD' to add holdings."

    lines       = ["Portfolio:"]
    total_cost  = 0.0
    total_value = 0.0

    for sym, holding in data.items():
        shares    = holding["shares"]
        avg_price = holding["avg_price"]
        cost      = shares * avg_price
        d         = _fetch(sym)
        curr      = holding["currency"]

        if d.get("ok") and d.get("price"):
            price     = d["price"]
            value     = shares * price
            pl        = value - cost
            pl_pct    = (pl / cost * 100) if cost else 0
            sign      = "+" if pl >= 0 else ""
            total_cost  += cost
            total_value += value
            lines.append(
                f"  {sym:<8}  {shares:>8.4g} sh  "
                f"@ {avg_price:.2f} -> {price:.2f} {curr}  "
                f"value: {value:>10,.2f}  P&L: {sign}{pl:,.2f} ({sign}{pl_pct:.1f}%)"
            )
        else:
            total_cost += cost
            lines.append(f"  {sym:<8}  {shares:>8.4g} sh  cost: {cost:,.2f} {curr}  (price unavailable)")

    if len(data) > 1:
        total_pl  = total_value - total_cost
        total_pct = (total_pl / total_cost * 100) if total_cost else 0
        sign      = "+" if total_pl >= 0 else ""
        lines.append(f"  {'':->60}")
        lines.append(f"  {'Total':8}  cost: {total_cost:>12,.2f}  value: {total_value:>12,.2f}  P&L: {sign}{total_pl:,.2f} ({sign}{total_pct:.1f}%)")
    return "\n".join(lines)


def set_price_alert(symbol: str, target_price, condition: str = "above") -> str:
    """Set a price alert. condition: 'above' or 'below'."""
    data = _load(_ALERTS_PATH, list)
    sym  = symbol.upper()
    cond = condition.lower()
    if cond not in ("above", "below"):
        cond = "above"
    data = [a for a in data if not (a["symbol"] == sym and a["condition"] == cond)]
    data.append({
        "symbol":    sym,
        "target":    float(target_price),
        "condition": cond,
        "created":   datetime.now().strftime("%Y-%m-%d"),
        "triggered": False,
    })
    _save(_ALERTS_PATH, data)
    return f"Alert set: notify when {sym} goes {cond} {float(target_price):.2f}."


def list_price_alerts() -> str:
    data = _load(_ALERTS_PATH, list)
    active = [a for a in data if not a.get("triggered")]
    if not active:
        return "No active price alerts."
    lines = ["Price alerts:"]
    for a in active:
        d = _fetch(a["symbol"])
        curr_s = f"  (now {d['price']:.2f})" if d.get("ok") and d.get("price") else ""
        lines.append(f"  {a['symbol']:>8}  {a['condition']} {a['target']:.2f}{curr_s}")
    return "\n".join(lines)


def delete_price_alert(symbol: str) -> str:
    data   = _load(_ALERTS_PATH, list)
    before = len(data)
    data   = [a for a in data if a["symbol"] != symbol.upper()]
    if len(data) == before:
        return f"No alert found for {symbol.upper()}."
    _save(_ALERTS_PATH, data)
    return f"Alert(s) for {symbol.upper()} deleted."


# ── Expert analysis tools ─────────────────────────────────────────────────────

def get_price_history(symbol: str, period: str = "1y") -> str:
    """Price performance over a period: return %, high, low, volatility.
    period: 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, ytd, max
    """
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol.upper())
        hist   = ticker.history(period=period)
        if hist.empty:
            return f"No history data for {symbol.upper()} over {period}."

        first_close  = hist["Close"].iloc[0]
        last_close   = hist["Close"].iloc[-1]
        period_high  = hist["High"].max()
        period_low   = hist["Low"].min()
        total_return = (last_close - first_close) / first_close * 100
        days         = len(hist)

        # Volatility (annualised std dev of daily returns)
        daily_returns = hist["Close"].pct_change().dropna()
        vol = daily_returns.std() * (252 ** 0.5) * 100

        sign  = "+" if total_return >= 0 else ""
        emoji = "^" if total_return >= 0 else "v"

        lines = [f"{symbol.upper()} — performance ({period}, {days} trading days):"]
        lines.append(f"  Return:       {sign}{total_return:.2f}%  {emoji}")
        lines.append(f"  Period high:  {period_high:,.2f}")
        lines.append(f"  Period low:   {period_low:,.2f}")
        lines.append(f"  Current:      {last_close:,.2f}")
        lines.append(f"  Volatility:   {vol:.1f}% annualised")
        pct_from_high = (last_close - period_high) / period_high * 100
        lines.append(f"  From period high: {pct_from_high:.1f}%")
        return "\n".join(lines)
    except Exception as e:
        return f"History error for {symbol}: {e}"


def get_financials(symbol: str) -> str:
    """Key financial metrics: revenue, profit margins, EPS, ROE, debt/equity."""
    try:
        import yfinance as yf
        info = yf.Ticker(symbol.upper()).info
        if not info:
            return f"No financial data for {symbol.upper()}."

        name = info.get("longName") or info.get("shortName", symbol.upper())
        curr = info.get("currency", "USD")
        lines = [f"{name} ({symbol.upper()}) — Financials:"]

        rev      = info.get("totalRevenue")
        gm       = info.get("grossMargins")
        om       = info.get("operatingMargins")
        pm       = info.get("profitMargins")
        eps      = info.get("trailingEps")
        fwd_eps  = info.get("forwardEps")
        roe      = info.get("returnOnEquity")
        roa      = info.get("returnOnAssets")
        de       = info.get("debtToEquity")
        cr       = info.get("currentRatio")
        fcf      = info.get("freeCashflow")
        eps_grow = info.get("earningsGrowth")
        rev_grow = info.get("revenueGrowth")

        def _b(v):
            if v is None: return None
            if abs(v) >= 1e12: return f"{v/1e12:.2f}T"
            if abs(v) >= 1e9:  return f"{v/1e9:.2f}B"
            if abs(v) >= 1e6:  return f"{v/1e6:.2f}M"
            return f"{v:,.0f}"

        if rev:     lines.append(f"  Revenue:         {_b(rev)} {curr}")
        if rev_grow is not None: lines.append(f"  Revenue growth:  {rev_grow*100:.1f}%")
        if gm  is not None: lines.append(f"  Gross margin:    {gm*100:.1f}%")
        if om  is not None: lines.append(f"  Operating margin:{om*100:.1f}%")
        if pm  is not None: lines.append(f"  Net margin:      {pm*100:.1f}%")
        if eps:     lines.append(f"  EPS (trailing):  {eps:.2f} {curr}")
        if fwd_eps: lines.append(f"  EPS (forward):   {fwd_eps:.2f} {curr}")
        if eps_grow is not None: lines.append(f"  EPS growth:      {eps_grow*100:.1f}%")
        if roe is not None: lines.append(f"  ROE:             {roe*100:.1f}%")
        if roa is not None: lines.append(f"  ROA:             {roa*100:.1f}%")
        if de  is not None: lines.append(f"  Debt/Equity:     {de:.2f}")
        if cr  is not None: lines.append(f"  Current ratio:   {cr:.2f}")
        if fcf:     lines.append(f"  Free cash flow:  {_b(fcf)} {curr}")
        return "\n".join(lines) if len(lines) > 1 else f"Limited financial data available for {symbol.upper()}."
    except Exception as e:
        return f"Financials error for {symbol}: {e}"


def get_earnings(symbol: str) -> str:
    """Earnings history, next earnings date, EPS estimates vs actuals."""
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol.upper())
        info   = ticker.info
        name   = info.get("longName") or info.get("shortName", symbol.upper())
        lines  = [f"{name} ({symbol.upper()}) — Earnings:"]

        # Next earnings date
        cal = ticker.calendar
        if cal is not None and not (hasattr(cal, 'empty') and cal.empty):
            if hasattr(cal, 'get'):
                ed = cal.get("Earnings Date")
                if ed is not None:
                    lines.append(f"  Next earnings: {ed}")
            else:
                try:
                    ed = cal.loc["Earnings Date"] if "Earnings Date" in cal.index else None
                    if ed is not None:
                        lines.append(f"  Next earnings: {ed.iloc[0].strftime('%Y-%m-%d') if hasattr(ed.iloc[0], 'strftime') else str(ed.iloc[0])}")
                except Exception:
                    pass

        # Forward/trailing P/E and PEG
        pe    = info.get("trailingPE")
        fpe   = info.get("forwardPE")
        peg   = info.get("pegRatio")
        eps   = info.get("trailingEps")
        feps  = info.get("forwardEps")
        egrow = info.get("earningsGrowth")

        if pe:    lines.append(f"  Trailing P/E:  {pe:.1f}x")
        if fpe:   lines.append(f"  Forward P/E:   {fpe:.1f}x")
        if peg:   lines.append(f"  PEG ratio:     {peg:.2f}  (< 1 = potentially undervalued)")
        if eps:   lines.append(f"  EPS (ttm):     {eps:.2f}")
        if feps:  lines.append(f"  EPS (fwd est): {feps:.2f}")
        if egrow is not None: lines.append(f"  EPS growth:    {egrow*100:.1f}%")

        # Quarterly earnings history
        try:
            eq = ticker.quarterly_earnings
            if eq is not None and not eq.empty:
                lines.append("  Quarterly EPS (recent):")
                for idx, row in eq.tail(4).iterrows():
                    rpt  = row.get("Reported EPS", row.get("EPS Actual", "?"))
                    est  = row.get("EPS Estimate", "?")
                    beat = ""
                    if rpt != "?" and est != "?":
                        try:
                            diff = float(rpt) - float(est)
                            beat = f"  ({'beat' if diff >= 0 else 'miss'} by {abs(diff):.2f})"
                        except Exception:
                            pass
                    lines.append(f"    {idx}: reported {rpt}  est {est}{beat}")
        except Exception:
            pass

        return "\n".join(lines) if len(lines) > 1 else f"No earnings data for {symbol.upper()}."
    except Exception as e:
        return f"Earnings error for {symbol}: {e}"


def get_analyst_ratings(symbol: str) -> str:
    """Analyst consensus: buy/hold/sell breakdown, average price target, upside."""
    try:
        import yfinance as yf
        ticker  = yf.Ticker(symbol.upper())
        info    = ticker.info
        name    = info.get("longName") or info.get("shortName", symbol.upper())
        price   = info.get("currentPrice") or info.get("regularMarketPrice")
        curr    = info.get("currency", "USD")
        lines   = [f"{name} ({symbol.upper()}) — Analyst ratings:"]

        # Recommendation
        rec     = info.get("recommendationKey", "")
        mean    = info.get("recommendationMean")
        n_anal  = info.get("numberOfAnalystOpinions")
        tgt_low = info.get("targetLowPrice")
        tgt_hi  = info.get("targetHighPrice")
        tgt_avg = info.get("targetMeanPrice")
        tgt_med = info.get("targetMedianPrice")

        if rec:
            lines.append(f"  Consensus:     {rec.upper().replace('_', ' ')}")
        if mean:
            scale = "  (1=strong buy, 3=hold, 5=strong sell)"
            lines.append(f"  Mean score:    {mean:.1f}{scale}")
        if n_anal:
            lines.append(f"  # analysts:    {n_anal}")
        if tgt_avg and price:
            upside = (tgt_avg - price) / price * 100
            sign   = "+" if upside >= 0 else ""
            lines.append(f"  Avg target:    {tgt_avg:.2f} {curr}  ({sign}{upside:.1f}% upside)")
        if tgt_med:
            lines.append(f"  Median target: {tgt_med:.2f} {curr}")
        if tgt_low and tgt_hi:
            lines.append(f"  Target range:  {tgt_low:.2f} — {tgt_hi:.2f} {curr}")

        # Recent upgrades/downgrades
        try:
            recs = ticker.recommendations
            if recs is not None and not recs.empty:
                lines.append("  Recent changes:")
                for idx, row in recs.tail(5).iterrows():
                    firm   = row.get("Firm", "?")
                    action = row.get("Action", row.get("To Grade", "?"))
                    grade  = row.get("To Grade", "")
                    date   = str(idx)[:10] if hasattr(idx, '__str__') else str(idx)
                    lines.append(f"    {date}  {firm:<20} {action}  {grade}")
        except Exception:
            pass

        return "\n".join(lines) if len(lines) > 1 else f"No analyst data for {symbol.upper()}."
    except Exception as e:
        return f"Analyst ratings error for {symbol}: {e}"


def get_dividends(symbol: str) -> str:
    """Dividend info: yield, annual rate, ex-dividend date, payout ratio, history."""
    try:
        import yfinance as yf
        ticker  = yf.Ticker(symbol.upper())
        info    = ticker.info
        name    = info.get("longName") or info.get("shortName", symbol.upper())
        curr    = info.get("currency", "USD")

        div_yield = info.get("dividendYield")
        div_rate  = info.get("dividendRate")
        ex_date   = info.get("exDividendDate")
        payout    = info.get("payoutRatio")
        last_div  = info.get("lastDividendValue")

        if not div_yield and not div_rate:
            return f"{name} ({symbol.upper()}) does not pay a dividend."

        lines = [f"{name} ({symbol.upper()}) — Dividends:"]
        if div_yield: lines.append(f"  Yield:         {div_yield:.2f}%")
        if div_rate:  lines.append(f"  Annual rate:   {div_rate:.4f} {curr}")
        if payout:    lines.append(f"  Payout ratio:  {payout*100:.1f}%")
        if ex_date:
            from datetime import datetime
            ex_str = datetime.fromtimestamp(ex_date).strftime("%Y-%m-%d") if isinstance(ex_date, (int, float)) else str(ex_date)
            lines.append(f"  Ex-div date:   {ex_str}")
        if last_div:  lines.append(f"  Last payment:  {last_div:.4f} {curr}")

        # 5-year dividend history
        try:
            hist = ticker.dividends
            if hist is not None and not hist.empty:
                lines.append("  Recent dividends:")
                for date, val in hist.tail(6).items():
                    lines.append(f"    {str(date)[:10]}  {val:.4f} {curr}")
        except Exception:
            pass

        return "\n".join(lines)
    except Exception as e:
        return f"Dividend error for {symbol}: {e}"


def compare_stocks(symbol1: str, symbol2: str) -> str:
    """Side-by-side comparison of two stocks on key metrics."""
    d1 = _fetch(symbol1)
    d2 = _fetch(symbol2)
    s1 = symbol1.upper()
    s2 = symbol2.upper()

    def _row(label, v1, v2):
        v1s = str(v1) if v1 is not None else "N/A"
        v2s = str(v2) if v2 is not None else "N/A"
        return f"  {label:<18} {v1s:>14}  {v2s:>14}"

    try:
        import yfinance as yf
        i1 = yf.Ticker(s1).info
        i2 = yf.Ticker(s2).info
    except Exception:
        i1, i2 = {}, {}

    def _mc(v):
        if v is None: return None
        if v >= 1e12: return f"{v/1e12:.2f}T"
        if v >= 1e9:  return f"{v/1e9:.2f}B"
        return f"{v/1e6:.0f}M"

    p1 = d1.get("price")
    p2 = d2.get("price")
    c1 = d1.get("currency", "USD")
    c2 = d2.get("currency", "USD")

    lines = [f"Comparison: {s1} vs {s2}"]
    lines.append(f"  {'Metric':<18} {s1:>14}  {s2:>14}")
    lines.append(f"  {'-'*48}")

    if p1 or p2:
        lines.append(_row("Price", f"{p1:.2f} {c1}" if p1 else "N/A", f"{p2:.2f} {c2}" if p2 else "N/A"))

    chg1 = d1.get("change_pct")
    chg2 = d2.get("change_pct")
    lines.append(_row("Day change", f"{chg1:+.2f}%" if chg1 is not None else "N/A", f"{chg2:+.2f}%" if chg2 is not None else "N/A"))

    pe1 = i1.get("trailingPE"); pe2 = i2.get("trailingPE")
    lines.append(_row("P/E (trailing)", f"{pe1:.1f}x" if pe1 else "N/A", f"{pe2:.1f}x" if pe2 else "N/A"))

    fpe1 = i1.get("forwardPE"); fpe2 = i2.get("forwardPE")
    lines.append(_row("P/E (forward)", f"{fpe1:.1f}x" if fpe1 else "N/A", f"{fpe2:.1f}x" if fpe2 else "N/A"))

    mc1 = i1.get("marketCap"); mc2 = i2.get("marketCap")
    lines.append(_row("Market cap", _mc(mc1) or "N/A", _mc(mc2) or "N/A"))

    pm1 = i1.get("profitMargins"); pm2 = i2.get("profitMargins")
    lines.append(_row("Net margin", f"{pm1*100:.1f}%" if pm1 else "N/A", f"{pm2*100:.1f}%" if pm2 else "N/A"))

    roe1 = i1.get("returnOnEquity"); roe2 = i2.get("returnOnEquity")
    lines.append(_row("ROE", f"{roe1*100:.1f}%" if roe1 else "N/A", f"{roe2*100:.1f}%" if roe2 else "N/A"))

    de1 = i1.get("debtToEquity"); de2 = i2.get("debtToEquity")
    lines.append(_row("Debt/Equity", f"{de1:.2f}" if de1 else "N/A", f"{de2:.2f}" if de2 else "N/A"))

    dy1 = i1.get("dividendYield"); dy2 = i2.get("dividendYield")
    # yfinance returns dividendYield already in pct form (0.36 = 0.36%), not decimal
    lines.append(_row("Div yield", f"{dy1:.2f}%" if dy1 else "None", f"{dy2:.2f}%" if dy2 else "None"))

    h1 = d1.get("high_52w"); l1 = d1.get("low_52w")
    h2 = d2.get("high_52w"); l2 = d2.get("low_52w")
    r1 = f"{l1:.2f}-{h1:.2f}" if h1 and l1 else "N/A"
    r2 = f"{l2:.2f}-{h2:.2f}" if h2 and l2 else "N/A"
    lines.append(_row("52w range", r1, r2))

    return "\n".join(lines)


def sector_performance() -> str:
    """US sector ETFs performance today — shows which sectors are hot/cold."""
    sectors = {
        "Technology":     "XLK",
        "Financials":     "XLF",
        "Healthcare":     "XLV",
        "Energy":         "XLE",
        "Industrials":    "XLI",
        "Consumer Disc.": "XLY",
        "Consumer Stap.": "XLP",
        "Utilities":      "XLU",
        "Materials":      "XLB",
        "Comms":          "XLC",
        "Real Estate":    "XLRE",
    }
    lines = ["US Sector performance (today):"]
    results = []
    for name, sym in sectors.items():
        d = _fetch(sym)
        pct = d.get("change_pct")
        if pct is not None:
            results.append((name, sym, pct))

    results.sort(key=lambda x: -x[2])
    for name, sym, pct in results:
        bar  = "#" * int(abs(pct) * 2)
        sign = "+" if pct >= 0 else ""
        arrow = "^" if pct >= 0 else "v"
        lines.append(f"  {name:<16} {sym}  {sign}{pct:.2f}%  {arrow} {bar}")
    return "\n".join(lines) if len(lines) > 1 else "Could not fetch sector data."


def check_price_alerts() -> list[str]:
    """Internal — called by proactive engine. Returns list of triggered messages."""
    data     = _load(_ALERTS_PATH, list)
    messages = []
    changed  = False
    for alert in data:
        if alert.get("triggered"):
            continue
        d = _fetch(alert["symbol"])
        if not d.get("ok") or not d.get("price"):
            continue
        price  = d["price"]
        target = alert["target"]
        cond   = alert["condition"]
        hit    = (cond == "above" and price >= target) or (cond == "below" and price <= target)
        if hit:
            alert["triggered"] = True
            changed = True
            sign = "+" if d.get("change_pct", 0) >= 0 else ""
            messages.append(
                f"Mo, {alert['symbol']} hit your price alert — "
                f"now at {price:.2f} ({sign}{d.get('change_pct', 0):.2f}% today), "
                f"target was {cond} {target:.2f}."
            )
    if changed:
        _save(_ALERTS_PATH, data)
    return messages
