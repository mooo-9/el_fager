"""
Bond tool — sovereign bond yields and yield curve via yfinance.
Covers US Treasuries, German Bund, UK Gilts, and major sovereign rates.
"""

import yfinance as yf

_TREASURIES = {
    "3M":  "^IRX",
    "2Y":  "^TYT",
    "5Y":  "^FVX",
    "10Y": "^TNX",
    "30Y": "^TYX",
}

_SOVEREIGN = {
    "US 10Y":         "^TNX",
    "Germany 10Y":    "^DE10YT=RR",
    "UK 10Y":         "^GB10YT=RR",
    "Japan 10Y":      "^JP10YT=RR",
    "France 10Y":     "^FR10YT=RR",
}

_CREDIT_SPREADS = {
    "Investment Grade (LQD)":  "LQD",
    "High Yield (HYG)":        "HYG",
    "Emerging Markets (EMB)":  "EMB",
}


def _fetch_yield(symbol: str) -> float | None:
    try:
        price = yf.Ticker(symbol).fast_info.last_price
        return round(price, 3) if price else None
    except Exception:
        return None


def get_bond_yields() -> str:
    """US Treasury yield curve + major sovereign 10Y yields."""
    lines = ["Bond yields:"]

    # US Treasury curve
    lines.append("  US Treasury yield curve:")
    prev = None
    for label, sym in _TREASURIES.items():
        y = _fetch_yield(sym)
        if y is not None:
            spread = ""
            if prev is not None:
                diff = y - prev
                spread = f"  ({'+' if diff >= 0 else ''}{diff:.2f}%)"
            lines.append(f"    {label:<5}  {y:.3f}%{spread}")
            prev = y

    # 2s10s spread (most watched)
    y2 = _fetch_yield("^TYT")
    y10 = _fetch_yield("^TNX")
    if y2 and y10:
        spread_2s10s = y10 - y2
        inverted = " (INVERTED — recession signal)" if spread_2s10s < 0 else ""
        lines.append(f"  2s10s spread: {spread_2s10s:+.3f}%{inverted}")

    # Major sovereign 10Y
    lines.append("  Major sovereign 10Y:")
    for label, sym in _SOVEREIGN.items():
        y = _fetch_yield(sym)
        if y is not None:
            lines.append(f"    {label:<18}  {y:.3f}%")
        else:
            lines.append(f"    {label:<18}  N/A")

    return "\n".join(lines)


def get_yield_curve() -> str:
    """US yield curve shape with inversion analysis."""
    yields = {}
    for label, sym in _TREASURIES.items():
        y = _fetch_yield(sym)
        if y is not None:
            yields[label] = y

    if len(yields) < 3:
        return "Could not fetch enough yield data for curve analysis."

    lines = ["US Treasury yield curve:"]
    for label, y in yields.items():
        bar_len = int(y * 4)
        bar = "#" * bar_len
        lines.append(f"  {label:<5}  {y:.3f}%  {bar}")

    # Key spreads
    lines.append("")
    lines.append("  Key spreads:")
    if "3M" in yields and "10Y" in yields:
        s = yields["10Y"] - yields["3M"]
        flag = " << INVERTED" if s < 0 else ""
        lines.append(f"    3M vs 10Y: {s:+.3f}%{flag}")
    if "2Y" in yields and "10Y" in yields:
        s = yields["10Y"] - yields["2Y"]
        flag = " << INVERTED" if s < 0 else ""
        lines.append(f"    2Y vs 10Y: {s:+.3f}%{flag}")
    if "5Y" in yields and "30Y" in yields:
        s = yields["30Y"] - yields["5Y"]
        lines.append(f"    5Y vs 30Y: {s:+.3f}%")

    shape = "NORMAL" if (yields.get("30Y", 0) > yields.get("3M", 0)) else "INVERTED/FLAT"
    lines.append(f"  Curve shape: {shape}")
    lines.append("  Note: Inverted curve (short > long) historically precedes recessions by 12-18 months.")

    return "\n".join(lines)
