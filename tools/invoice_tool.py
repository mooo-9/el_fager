"""
Invoice tool — JSON-backed invoice lifecycle management (draft → sent → paid).
Data: data/invoices.json
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

_INVOICE_PATH = Path("data/invoices.json")


def _load() -> dict:
    if not _INVOICE_PATH.exists():
        return {"next_id": 1, "invoices": []}
    return json.loads(_INVOICE_PATH.read_text(encoding="utf-8"))


def _save(data: dict) -> None:
    _INVOICE_PATH.parent.mkdir(exist_ok=True)
    _INVOICE_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _is_overdue(inv: dict) -> bool:
    if inv.get("status") != "sent":
        return False
    try:
        due = datetime.strptime(inv["due_date"], "%Y-%m-%d").date()
        return due < datetime.now().date()
    except Exception:
        return False


def _resolve_due_date(due_date: str) -> str:
    """Accept YYYY-MM-DD, 'in X days', or 'next Friday'."""
    s = due_date.strip().lower()
    if s.startswith("in ") and "day" in s:
        try:
            n = int(s.split()[1])
            return (datetime.now().date() + timedelta(days=n)).strftime("%Y-%m-%d")
        except Exception:
            pass
    # "next <weekday>"
    weekdays = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    for i, wd in enumerate(weekdays):
        if wd in s:
            today = datetime.now().date()
            days_ahead = (i - today.weekday()) % 7 or 7
            return (today + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
    # Already in YYYY-MM-DD
    try:
        datetime.strptime(due_date.strip(), "%Y-%m-%d")
        return due_date.strip()
    except Exception:
        pass
    # Fallback: 30 days from now
    return (datetime.now().date() + timedelta(days=30)).strftime("%Y-%m-%d")


def _fmt_inv(inv: dict) -> str:
    status = "OVERDUE" if _is_overdue(inv) else inv["status"].upper()
    line = (
        f"{inv['id']}  [{status}]  {float(inv['amount']):,.0f} {inv['currency']}  "
        f"client: {inv['client']}  due: {inv['due_date']}"
    )
    if inv.get("description"):
        line += f"  — {inv['description']}"
    return line


def create_invoice(client: str, amount, description: str, due_date: str,
                   currency: str = "EGP", notes: str = "") -> str:
    data = _load()
    inv_id = f"INV-{data['next_id']:04d}"
    data["next_id"] += 1
    inv = {
        "id":           inv_id,
        "client":       client,
        "amount":       float(amount),
        "currency":     currency.upper(),
        "description":  description,
        "issued_date":  datetime.now().strftime("%Y-%m-%d"),
        "due_date":     _resolve_due_date(due_date),
        "status":       "draft",
        "paid_date":    None,
        "notes":        notes,
    }
    data["invoices"].append(inv)
    _save(data)
    return f"Created {inv_id} — {float(amount):,.0f} {currency.upper()} for {client}, due {inv['due_date']}."


def send_invoice(invoice_id: str) -> str:
    data = _load()
    for inv in data["invoices"]:
        if inv["id"].lower() == invoice_id.strip().lower():
            if inv["status"] == "paid":
                return f"{inv['id']} is already paid."
            inv["status"] = "sent"
            _save(data)
            return f"{inv['id']} marked as sent — now awaiting payment from {inv['client']}."
    return f"Invoice {invoice_id} not found."


def mark_invoice_paid(invoice_id: str, paid_date: str = "") -> str:
    data = _load()
    for inv in data["invoices"]:
        if inv["id"].lower() == invoice_id.strip().lower():
            if inv["status"] == "paid":
                return f"{inv['id']} was already marked paid."
            inv["status"]    = "paid"
            inv["paid_date"] = paid_date.strip() or datetime.now().strftime("%Y-%m-%d")
            _save(data)
            # Auto-log income to avoid duplicate manual entry
            from tools.income_tool import log_income
            log_income(
                inv["amount"], inv["currency"],
                category="freelance",
                source=inv["client"],
                description=inv.get("description", ""),
                invoice_id=inv["id"],
            )
            return (
                f"{inv['id']} marked paid — {float(inv['amount']):,.0f} {inv['currency']} "
                f"from {inv['client']} logged as income."
            )
    return f"Invoice {invoice_id} not found."


def list_invoices(status_filter: str = "all") -> str:
    data = _load()
    invs = data["invoices"]
    if not invs:
        return "No invoices found."

    f = status_filter.lower()
    if f == "overdue":
        filtered = [i for i in invs if _is_overdue(i)]
    elif f in ("draft", "sent", "paid"):
        filtered = [i for i in invs if i["status"] == f]
    else:
        filtered = invs

    if not filtered:
        return f"No {status_filter} invoices."

    lines = [f"Invoices ({status_filter}):"]
    for inv in sorted(filtered, key=lambda x: x["due_date"]):
        lines.append("  " + _fmt_inv(inv))
    return "\n".join(lines)


def get_invoice(invoice_id: str) -> str:
    data = _load()
    for inv in data["invoices"]:
        if inv["id"].lower() == invoice_id.strip().lower():
            status = "OVERDUE" if _is_overdue(inv) else inv["status"].upper()
            lines  = [f"Invoice {inv['id']}:"]
            lines.append(f"  Client:      {inv['client']}")
            lines.append(f"  Amount:      {float(inv['amount']):,.0f} {inv['currency']}")
            lines.append(f"  Description: {inv['description']}")
            lines.append(f"  Status:      {status}")
            lines.append(f"  Issued:      {inv['issued_date']}")
            lines.append(f"  Due:         {inv['due_date']}")
            if inv.get("paid_date"):
                lines.append(f"  Paid:        {inv['paid_date']}")
            if inv.get("notes"):
                lines.append(f"  Notes:       {inv['notes']}")
            return "\n".join(lines)
    return f"Invoice {invoice_id} not found."


def delete_invoice(invoice_id: str) -> str:
    data = _load()
    before = len(data["invoices"])
    data["invoices"] = [i for i in data["invoices"] if i["id"].lower() != invoice_id.strip().lower()]
    if len(data["invoices"]) == before:
        return f"Invoice {invoice_id} not found."
    _save(data)
    return f"Invoice {invoice_id} deleted."


def get_overdue_invoices() -> list[dict]:
    """Internal helper for proactive checks — returns raw dicts."""
    return [i for i in _load()["invoices"] if _is_overdue(i)]
