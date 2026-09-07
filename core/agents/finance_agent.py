"""
Abacus -- El Fager's bookkeeper.

Personal money: expenses, income, invoices, and budgets. Wraps
tools/expense_tool.py, income_tool.py, invoice_tool.py and budget_tool.py.
Separate from Midas, who trades -- Abacus never touches the market.

Safety: sending an invoice puts a document in front of a client, and the
deletes are irreversible, so those are in confirm_before.
"""
from core.agents.base_agent import BaseAgent
from core.agents.tool_loop import run_tool_loop, tool

DESTRUCTIVE_TOOLS = (
    "send_invoice",
    "delete_invoice",
    "delete_budget",
)

_SYSTEM = """\
You are Abacus, El Fager's bookkeeping agent, working for Mo.

Money is in EGP unless Mo says otherwise. Read the current state before
changing it -- check the existing budget before setting a new one, look for a
matching invoice before creating a duplicate.

Give real numbers, not impressions: "3,200 EGP on food this week, 800 over the
budget", never "you spent a fair amount".

If a tool you need is unavailable, you are working unattended: report what you
would have done and leave it for Mo.

Report in two or three sentences. Plain English, no markdown, no emoji."""


class FinanceAgent(BaseAgent):
    def __init__(self, allow_side_effects: bool = True):
        self._allow_side_effects = allow_side_effects

    @property
    def name(self) -> str:
        return "finance"

    @property
    def description(self) -> str:
        return "Personal money -- expenses, income, invoices, and budgets."

    def run(self, task: str) -> str:
        tools, dispatch = self._toolset()
        return run_tool_loop("finance_agent", _SYSTEM, tools, dispatch, task)

    def _toolset(self) -> tuple[list[dict], dict]:
        from tools import budget_tool as bu
        from tools import expense_tool as ex
        from tools import income_tool as inc
        from tools import invoice_tool as inv

        schemas = [
            tool("log_expense", "Record one expense.",
                 {"amount": ("number", "Amount spent."),
                  "currency": ("string", "Currency code, default EGP."),
                  "category": ("string", "Category, e.g. food, transport, other."),
                  "description": ("string", "What it was for.")}, ["amount"]),
            tool("get_expense_summary", "Spending totals by category.",
                 {"period": ("string", "'day', 'week', 'month', or 'year'.")}),
            tool("list_recent_expenses", "List the most recent expenses.",
                 {"n": ("integer", "How many, default 10.")}),
            tool("log_income", "Record income received.",
                 {"amount": ("number", "Amount received."),
                  "currency": ("string", "Currency code, default EGP."),
                  "category": ("string", "Source category."),
                  "description": ("string", "What it was for.")}, ["amount"]),
            tool("get_income_summary", "Income totals for a period.",
                 {"period": ("string", "'week', 'month', or 'year'.")}),
            tool("list_recent_income", "List recent income entries.",
                 {"n": ("integer", "How many, default 10.")}),
            tool("create_invoice", "Create an invoice for a client.",
                 {"client": ("string", "Client name."),
                  "amount": ("number", "Invoice amount."),
                  "description": ("string", "What the work was."),
                  "due_date": ("string", "Due date, natural language or YYYY-MM-DD."),
                  "currency": ("string", "Currency code, default EGP."),
                  "notes": ("string", "Optional notes.")},
                 ["client", "amount", "description", "due_date"]),
            tool("list_invoices", "List invoices.",
                 {"status_filter": ("string", "'all', 'unpaid', 'paid', or 'overdue'.")}),
            tool("get_invoice", "Read one invoice.",
                 {"invoice_id": ("string", "Invoice id, e.g. INV-0003.")}, ["invoice_id"]),
            tool("mark_invoice_paid", "Mark an invoice as paid.",
                 {"invoice_id": ("string", "Invoice id."),
                  "paid_date": ("string", "Date paid, defaults to today.")}, ["invoice_id"]),
            tool("send_invoice", "Mark an invoice as sent to the client.",
                 {"invoice_id": ("string", "Invoice id.")}, ["invoice_id"]),
            tool("delete_invoice", "Delete an invoice permanently.",
                 {"invoice_id": ("string", "Invoice id.")}, ["invoice_id"]),
            tool("set_budget", "Set or update a spending budget for a category.",
                 {"category": ("string", "Category name."),
                  "limit": ("number", "Spending limit."),
                  "period": ("string", "'week' or 'month', default month."),
                  "currency": ("string", "Currency code, default EGP.")},
                 ["category", "limit"]),
            tool("list_budgets", "List budgets with actual spending against each limit."),
            tool("delete_budget", "Delete a budget.",
                 {"category": ("string", "Category name."),
                  "period": ("string", "'week' or 'month', default month.")}, ["category"]),
            tool("list_savings_goals", "List savings goals and progress."),
            tool("update_savings_progress", "Add to a savings goal's progress.",
                 {"name": ("string", "Goal name."),
                  "amount_saved": ("number", "Amount to add.")}, ["name", "amount_saved"]),
        ]
        dispatch = {
            "log_expense": ex.log_expense,
            "get_expense_summary": ex.get_expense_summary,
            "list_recent_expenses": ex.list_recent_expenses,
            "log_income": inc.log_income,
            "get_income_summary": inc.get_income_summary,
            "list_recent_income": inc.list_recent_income,
            "create_invoice": inv.create_invoice,
            "list_invoices": inv.list_invoices,
            "get_invoice": inv.get_invoice,
            "mark_invoice_paid": inv.mark_invoice_paid,
            "send_invoice": inv.send_invoice,
            "delete_invoice": inv.delete_invoice,
            "set_budget": bu.set_budget,
            "list_budgets": bu.list_budgets,
            "delete_budget": bu.delete_budget,
            "list_savings_goals": bu.list_savings_goals,
            "update_savings_progress": bu.update_savings_progress,
        }
        if not self._allow_side_effects:
            for name in DESTRUCTIVE_TOOLS:
                dispatch.pop(name, None)
            schemas = [s for s in schemas if s["name"] not in DESTRUCTIVE_TOOLS]
        return schemas, dispatch
