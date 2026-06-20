"""
Income tool — CSV-backed income logging.
Data: data/income.csv
"""

import csv
from datetime import datetime, timedelta
from pathlib import Path

_INCOME_PATH = Path("data/income.csv")
_FIELDNAMES  = ["date", "amount", "currency", "category", "source", "description", "invoice_id"]
_CATEGORIES  = {"freelance", "salary", "consulting", "sales", "investment", "gift", "other"}


def _load() -> list[dict]:
    if not _INCOME_PATH.exists():
        return []
    rows = []
    with _INCOME_PATH.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def _save_row(row: dict) -> None:
    _INCOME_PATH.parent.mkdir(exist_ok=True)
    write_header = not _INCOME_PATH.exists()
    with _INCOME_PATH.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_FIELDNAMES)
        if write_header:
            writer.writeheader()
        writer.writerow(row)


def _parse_date(date_str: str):
    try:
        return datetime.strptime(date_str.strip()[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def _get_range(period: str):
    today = datetime.now().date()
    p = period.lower()
    if p == "today":
        return today, today
    if p == "week":
        return today - timedelta(days=today.weekday()), today
    if p == "year":
        return today.replace(month=1, day=1), today
    return today.replace(day=1), today


def log_income(amount, currency: str = "EGP", category: str = "other",
               source: str = "", description: str = "", invoice_id: str = "") -> str:
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return "Invalid amount."
    category = category.lower() if category.lower() in _CATEGORIES else "other"
    row = {
        "date":       datetime.now().strftime("%Y-%m-%d %H:%M"),
        "amount":     f"{amount:.2f}",
        "currency":   currency.upper(),
        "category":   category,
        "source":     source,
        "description": description,
        "invoice_id": invoice_id,
    }
    _save_row(row)
    parts = [f"Logged {amount:,.2f} {currency.upper()}"]
    if source:
        parts.append(f"from {source}")
    if category != "other":
        parts.append(f"({category})")
    return " ".join(parts) + "."


def get_income_summary(period: str = "month") -> str:
    rows = _load()
    if not rows:
        return "No income recorded yet."

    start, end = _get_range(period)
    period_rows = [r for r in rows if (d := _parse_date(r["date"])) and start <= d <= end]

    if not period_rows:
        return f"No income recorded this {period}."

    total = sum(float(r["amount"]) for r in period_rows)
    currency = period_rows[-1]["currency"]
    days = max((end - start).days, 1)

    cat_totals: dict[str, float] = {}
    for r in period_rows:
        cat = r.get("category", "other")
        cat_totals[cat] = cat_totals.get(cat, 0) + float(r["amount"])
    top = sorted(cat_totals.items(), key=lambda x: -x[1])[:3]

    lines = [f"Income — this {period}:"]
    lines.append(f"  Total:     {total:,.0f} {currency}")
    lines.append(f"  Daily avg: {total / days:,.0f} {currency}")
    lines.append(f"  Entries:   {len(period_rows)}")
    if top:
        lines.append("  By category:")
        for cat, amt in top:
            lines.append(f"    {cat}: {amt:,.0f} {currency}  ({amt/total*100:.0f}%)")
    return "\n".join(lines)


def list_recent_income(n: int = 10) -> str:
    rows = _load()
    if not rows:
        return "No income recorded yet."
    recent = rows[-n:]
    recent.reverse()
    lines = [f"Last {len(recent)} income entries:"]
    for r in recent:
        date  = r["date"][:10]
        amt   = float(r["amount"])
        curr  = r["currency"]
        cat   = r.get("category", "other")
        src   = r.get("source", "")
        desc  = r.get("description", "")
        label = src or desc or cat
        lines.append(f"  {date}  {amt:>10,.0f} {curr}  {label}")
    return "\n".join(lines)


def get_total_income(period: str = "month") -> float:
    """Internal helper for analytics and proactive checks."""
    rows = _load()
    if not rows:
        return 0.0
    start, end = _get_range(period)
    return sum(
        float(r["amount"])
        for r in rows
        if (d := _parse_date(r["date"])) and start <= d <= end
    )
