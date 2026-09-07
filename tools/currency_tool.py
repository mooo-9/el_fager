"""
Currency converter — Phase 6A.
Uses exchangerate-api.com free endpoint (no API key, updated daily, includes EGP).
"""

import httpx

_BASE_URL = "https://api.exchangerate-api.com/v4/latest/{}"

_ALIASES = {
    "pound":   "EGP",
    "dollar":  "USD",
    "euro":    "EUR",
    "riyal":   "SAR",
    "dirham":  "AED",
    "sterling":"GBP",
}

def _normalise(code: str) -> str:
    c = code.strip().upper()
    return _ALIASES.get(c.lower(), _ALIASES.get(code.strip().lower(), c))


def convert_currency(amount: float, from_currency: str, to_currency: str) -> str:
    """Convert an amount from one currency to another."""
    src = _normalise(from_currency)
    dst = _normalise(to_currency)
    try:
        resp = httpx.get(_BASE_URL.format(src), timeout=8)
        resp.raise_for_status()
        rates = resp.json()["rates"]
        if dst not in rates:
            return f"Unknown currency: {dst}"
        result = amount * rates[dst]
        return f"{amount:,.2f} {src} = {result:,.2f} {dst}"
    except Exception as e:
        return f"[Currency error: {e}]"


def get_exchange_rates(base: str = "EGP") -> str:
    """Return live exchange rates for a base currency against common currencies."""
    src = _normalise(base)
    targets = ["USD", "EUR", "GBP", "SAR", "AED", "EGP"] if src != "EGP" else ["USD", "EUR", "GBP", "SAR", "AED"]
    try:
        resp = httpx.get(_BASE_URL.format(src), timeout=8)
        resp.raise_for_status()
        data = resp.json()
        rates = data["rates"]
        updated = data.get("date", "")
        lines = [f"Exchange rates for {src} (updated {updated}):\n"]
        for t in targets:
            if t in rates:
                lines.append(f"  1 {src} = {rates[t]:>10.4f} {t}")
        return "\n".join(lines)
    except Exception as e:
        return f"[Currency error: {e}]"
