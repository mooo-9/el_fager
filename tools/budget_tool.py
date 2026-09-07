"""
Budget tool — JSON-backed budgets and savings goals.
Data: data/budget.json
"""

import json
from datetime import datetime
from pathlib import Path
from core import atomic

_BUDGET_PATH = Path("data/budget.json")


def _load() -> dict:
    if not _BUDGET_PATH.exists():
        return {"budgets": [], "savings_goals": []}
    return json.loads(_BUDGET_PATH.read_text(encoding="utf-8"))


def _save(data: dict) -> None:
    _BUDGET_PATH.parent.mkdir(exist_ok=True)
    atomic.write(_BUDGET_PATH, json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _get_actual_spending(category: str, period: str) -> float:
    """Pull actual spending for a category from expense_tool."""
    try:
        from tools.expense_tool import _load as load_expenses
        from datetime import timedelta
        today = datetime.now().date()
        p = period.lower()
        if p == "week":
            start = today - timedelta(days=today.weekday())
        elif p == "year":
            start = today.replace(month=1, day=1)
        else:
            start = today.replace(day=1)
        end = today
        rows = load_expenses()
        total = 0.0
        for r in rows:
            try:
                d = datetime.strptime(r["date"].strip()[:10], "%Y-%m-%d").date()
                if start <= d <= end and r.get("category", "").lower() == category.lower():
                    total += float(r["amount"])
            except Exception:
                pass
        return total
    except Exception:
        return 0.0


def set_budget(category: str, limit, period: str = "month", currency: str = "EGP") -> str:
    data = _load()
    category = category.lower()
    for b in data["budgets"]:
        if b["category"] == category and b["period"] == period.lower():
            b["limit"]    = float(limit)
            b["currency"] = currency.upper()
            _save(data)
            return f"Updated budget: {category} -> {float(limit):,.0f} {currency.upper()} per {period}."
    data["budgets"].append({
        "category": category,
        "period":   period.lower(),
        "limit":    float(limit),
        "currency": currency.upper(),
    })
    _save(data)
    return f"Budget set: {category} -> {float(limit):,.0f} {currency.upper()} per {period}."


def list_budgets() -> str:
    data  = _load()
    budgs = data.get("budgets", [])
    if not budgs:
        return "No budgets set. Say 'my food budget is X EGP per month' to create one."

    lines = ["Budgets:"]
    for b in budgs:
        cat    = b["category"]
        limit  = b["limit"]
        curr   = b["currency"]
        period = b["period"]
        actual = _get_actual_spending(cat, period)
        pct    = (actual / limit * 100) if limit > 0 else 0
        bar    = "#" * int(pct / 10) + "." * (10 - int(pct / 10))
        status = " [OVER]" if actual > limit else ""
        lines.append(
            f"  {cat:<15} {actual:>8,.0f} / {limit:>8,.0f} {curr}  [{bar}] {pct:.0f}%{status}"
        )
    return "\n".join(lines)


def delete_budget(category: str, period: str = "month") -> str:
    data   = _load()
    before = len(data["budgets"])
    data["budgets"] = [
        b for b in data["budgets"]
        if not (b["category"] == category.lower() and b["period"] == period.lower())
    ]
    if len(data["budgets"]) == before:
        return f"No {category} budget found for {period}."
    _save(data)
    return f"Deleted {category} budget ({period})."


def check_budget_status(category: str, period: str = "month") -> dict | None:
    """Internal helper — returns status dict or None if no budget set."""
    data = _load()
    for b in data["budgets"]:
        if b["category"] == category.lower() and b["period"] == period.lower():
            actual  = _get_actual_spending(category, period)
            limit   = b["limit"]
            pct     = (actual / limit * 100) if limit > 0 else 0
            return {
                "category": category,
                "limit":    limit,
                "actual":   actual,
                "currency": b["currency"],
                "period":   period,
                "pct":      pct,
                "over":     actual > limit,
            }
    return None


def set_savings_goal(name: str, target, currency: str = "EGP",
                     deadline: str = "", notes: str = "") -> str:
    data = _load()
    for g in data["savings_goals"]:
        if g["name"].lower() == name.lower():
            g["target"]   = float(target)
            g["currency"] = currency.upper()
            if deadline:
                g["deadline"] = deadline
            if notes:
                g["notes"] = notes
            _save(data)
            return f"Updated savings goal '{name}' — target: {float(target):,.0f} {currency.upper()}."
    data["savings_goals"].append({
        "name":     name,
        "target":   float(target),
        "saved":    0.0,
        "currency": currency.upper(),
        "deadline": deadline,
        "notes":    notes,
    })
    _save(data)
    return f"Savings goal '{name}' created — target: {float(target):,.0f} {currency.upper()}."


def update_savings_progress(name: str, amount_saved) -> str:
    """Set the TOTAL saved so far (absolute value, not increment)."""
    data = _load()
    for g in data["savings_goals"]:
        if g["name"].lower() == name.lower():
            g["saved"] = float(amount_saved)
            _save(data)
            pct = (g["saved"] / g["target"] * 100) if g["target"] > 0 else 0
            remaining = max(g["target"] - g["saved"], 0)
            return (
                f"'{name}' progress: {float(amount_saved):,.0f} / {g['target']:,.0f} {g['currency']} "
                f"({pct:.0f}%)  — {remaining:,.0f} to go."
            )
    return f"Savings goal '{name}' not found."


def list_savings_goals() -> str:
    data  = _load()
    goals = data.get("savings_goals", [])
    if not goals:
        return "No savings goals set."

    lines = ["Savings goals:"]
    for g in goals:
        pct       = (g["saved"] / g["target"] * 100) if g["target"] > 0 else 0
        remaining = max(g["target"] - g["saved"], 0)
        bar       = "#" * int(pct / 10) + "." * (10 - int(pct / 10))
        deadline  = f"  by {g['deadline']}" if g.get("deadline") else ""
        lines.append(
            f"  {g['name']:<20} {g['saved']:>10,.0f} / {g['target']:>10,.0f} {g['currency']}"
            f"  [{bar}] {pct:.0f}%{deadline}"
        )
    return "\n".join(lines)


def delete_savings_goal(name: str) -> str:
    data   = _load()
    before = len(data["savings_goals"])
    data["savings_goals"] = [g for g in data["savings_goals"] if g["name"].lower() != name.lower()]
    if len(data["savings_goals"]) == before:
        return f"Savings goal '{name}' not found."
    _save(data)
    return f"Savings goal '{name}' deleted."


def get_exceeded_budgets() -> list[dict]:
    """Internal helper for proactive — returns list of over-budget dicts sorted by % over."""
    data    = _load()
    results = []
    for b in data.get("budgets", []):
        actual = _get_actual_spending(b["category"], b["period"])
        if actual > b["limit"] and b["limit"] > 0:
            pct = actual / b["limit"] * 100
            results.append({
                "category": b["category"],
                "limit":    b["limit"],
                "actual":   actual,
                "currency": b["currency"],
                "period":   b["period"],
                "pct":      pct,
            })
    return sorted(results, key=lambda x: -x["pct"])
