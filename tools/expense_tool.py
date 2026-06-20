"""
Expense tracker — Phase 6B.
Logs to data/expenses.csv. Zero new dependencies.
"""

import csv
import os
from datetime import datetime, timedelta
from pathlib import Path

EXPENSES_PATH = Path("data/expenses.csv")
FIELDNAMES = ["date", "amount", "currency", "category", "description"]

_CATEGORIES = [
    "food", "transport", "shopping", "health", "education",
    "entertainment", "bills", "other",
]


def _load() -> list[dict]:
    if not EXPENSES_PATH.exists():
        return []
    with open(EXPENSES_PATH, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _save_row(row: dict):
    EXPENSES_PATH.parent.mkdir(parents=True, exist_ok=True)
    new_file = not EXPENSES_PATH.exists()
    with open(EXPENSES_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if new_file:
            writer.writeheader()
        writer.writerow(row)


def log_expense(
    amount: float,
    currency: str = "EGP",
    category: str = "other",
    description: str = "",
) -> str:
    """Log a single expense entry."""
    cat = category.lower().strip()
    if cat not in _CATEGORIES:
        cat = "other"
    row = {
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "amount": f"{float(amount):.2f}",
        "currency": currency.upper(),
        "category": cat,
        "description": description.strip(),
    }
    _save_row(row)
    return f"Logged: {amount:.2f} {currency.upper()} — {cat} — {description or '(no description)'}"


def get_expense_summary(period: str = "week") -> str:
    """
    Summarise spending for 'today', 'week', or 'month'.
    Returns totals per category and an overall total.
    """
    rows = _load()
    if not rows:
        return "No expenses logged yet."

    now = datetime.now()
    cutoffs = {
        "today": now.replace(hour=0, minute=0, second=0),
        "week":  now - timedelta(days=7),
        "month": now - timedelta(days=30),
    }
    cutoff = cutoffs.get(period.lower(), cutoffs["week"])

    filtered = []
    for r in rows:
        try:
            dt = datetime.strptime(r["date"], "%Y-%m-%d %H:%M")
            if dt >= cutoff:
                filtered.append(r)
        except ValueError:
            pass

    if not filtered:
        return f"No expenses in the last {period}."

    by_cat: dict[str, dict[str, float]] = {}
    for r in filtered:
        cur = r.get("currency", "EGP")
        cat = r.get("category", "other")
        try:
            amt = float(r["amount"])
        except ValueError:
            continue
        by_cat.setdefault(cur, {}).setdefault(cat, 0.0)
        by_cat[cur][cat] += amt

    period_label = {"today": "today", "week": "this week", "month": "this month"}.get(period, period)
    lines = [f"Expense summary for {period_label} ({len(filtered)} entries):\n"]
    for cur, cats in sorted(by_cat.items()):
        lines.append(f"  {cur}:")
        total = 0.0
        for cat, amt in sorted(cats.items(), key=lambda x: -x[1]):
            lines.append(f"    {cat:<14} {amt:>9.2f}")
            total += amt
        lines.append(f"    {'TOTAL':<14} {total:>9.2f}")
        lines.append("")
    return "\n".join(lines).rstrip()


def list_recent_expenses(n: int = 10) -> str:
    """Return the most recent n expense entries."""
    rows = _load()
    if not rows:
        return "No expenses logged yet."
    recent = rows[-n:][::-1]
    lines = [f"Last {len(recent)} expenses:\n"]
    for r in recent:
        lines.append(
            f"  {r['date']}  {float(r['amount']):>8.2f} {r['currency']}  "
            f"{r['category']:<12}  {r.get('description','')}"
        )
    return "\n".join(lines)
