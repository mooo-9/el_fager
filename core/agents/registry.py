"""
Agent registry — the single source of truth for El Fager's roster.

Every specialist agent is declared once here: its callsign (the name Mo uses),
its tool name (the schema name the brain exposes -- unchanged from before this
registry existed), its role, its implementing class, and its wall-clock budget.

core/brain.py builds its agent tool schemas from tool_schemas() and dispatches
through load(), so adding an agent means adding one AgentSpec and nothing else.

Imports are lazy: several agents pull in Windows-only or heavyweight modules
(pyautogui, mss, playwright), so a spec is only imported when it actually runs.
"""
from dataclasses import dataclass, field
from importlib import import_module

_TASK_SCHEMA_HINTS = {
    "screen_agent": "The user's desktop-control request, verbatim or lightly cleaned up.",
    "browser_agent": "The user's web-automation request, verbatim or lightly cleaned up.",
    "stocks_agent": "The user's stock-analysis or trading-control request.",
    "research_agent": "The research question or topic, verbatim or lightly cleaned up.",
    "file_agent": "The file reference and question together, e.g. 'summarize my_contract.pdf'.",
    "health_agent": "The user's nutrition or workout request, verbatim or lightly cleaned up.",
}


def _comms_send_tools() -> tuple[str, ...]:
    from core.agents.comms_agent import SEND_TOOLS
    return SEND_TOOLS


def _scheduler_destructive_tools() -> tuple[str, ...]:
    from core.agents.scheduler_agent import DESTRUCTIVE_TOOLS
    return DESTRUCTIVE_TOOLS


def _finance_destructive_tools() -> tuple[str, ...]:
    from core.agents.finance_agent import DESTRUCTIVE_TOOLS
    return DESTRUCTIVE_TOOLS


def _dev_destructive_tools() -> tuple[str, ...]:
    from core.agents.dev_agent import DESTRUCTIVE_TOOLS
    return DESTRUCTIVE_TOOLS


@dataclass(frozen=True)
class AgentSpec:
    callsign: str          # the name Mo says: "Sage"
    tool_name: str         # the brain's tool schema name: "research_agent"
    role: str              # one line, shown in the roster
    module: str            # "core.agents.research_agent"
    cls: str               # "ResearchAgent"
    tool_description: str  # verbatim schema description
    task_hint: str         # schema description of the "task" property
    timeout_s: int = 180
    # Tool names this agent may only use when Mo asked for the work himself.
    # The gate is enforced by REMOVING them from the agent's dispatch map, not
    # by asking the model nicely -- see load() and core/agents/tool_loop.py.
    confirm_before: tuple[str, ...] = field(default_factory=tuple)

    def schema(self) -> dict:
        return {
            "name": self.tool_name,
            "description": self.tool_description,
            "input_schema": {
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": self.task_hint}
                },
                "required": ["task"],
            },
        }


ROSTER: dict[str, AgentSpec] = {
    spec.tool_name: spec
    for spec in [
        AgentSpec(
            callsign="Argus",
            tool_name="screen_agent",
            role="Desktop control and vision -- clicks, types, and drives any Windows app.",
            module="core.agents.screen_agent",
            cls="ScreenAgent",
            tool_description=(
                "Multi-step desktop control agent -- sees the screen and performs a sequence of "
                "clicks, typing, and keyboard shortcuts to complete a task (up to 10 internal steps). "
                "Use for: clicking buttons/links, dragging files, scrolling, multi-step UI automation "
                "('open and then...', 'automate the...', 'control the app'). Do NOT use for a single "
                "one-shot description of the screen -- use analyze_screen for that."
            ),
            task_hint=_TASK_SCHEMA_HINTS["screen_agent"],
            timeout_s=240,  # up to 10 vision steps at ~0.8s delay plus API latency
        ),
        AgentSpec(
            callsign="Nomad",
            tool_name="browser_agent",
            role="Browser automation -- navigates sites, fills forms, and logs in.",
            module="core.agents.browser_agent",
            cls="BrowserAgent",
            tool_description=(
                "Multi-step browser automation agent -- navigates websites, fills forms, logs in, and "
                "completes multi-step web tasks. Use for: 'book a table/flight', 'log into', "
                "'fill out the form', 'search on amazon/google', or any task naming a specific website "
                "or '.com/.org/.net'. Do NOT use for one-off single actions when a simpler browser_* "
                "instant tool suffices."
            ),
            task_hint=_TASK_SCHEMA_HINTS["browser_agent"],
            timeout_s=240,
        ),
        AgentSpec(
            callsign="Midas",
            tool_name="stocks_agent",
            role="Markets and trading -- deep analysis and conviction-gated trades.",
            module="core.agents.stocks_agent",
            cls="StocksAgent",
            tool_description=(
                "Deep market analysis and conviction-gated autonomous trading agent. Use for: "
                "'analyze NVDA', 'should I buy/sell X', 'your thesis/opinion/view on X', "
                "'conviction on X', 'scan my watchlist', 'why did you buy/sell X', 'my trading stats', "
                "'pause/resume trading', 'set auto-trade threshold to N'. Do NOT use for simple price "
                "lookups -- those are instant-lane tools."
            ),
            task_hint=_TASK_SCHEMA_HINTS["stocks_agent"],
        ),
        AgentSpec(
            callsign="Sage",
            tool_name="research_agent",
            role="Deep research -- searches many sources and synthesizes one answer.",
            module="core.agents.research_agent",
            cls="ResearchAgent",
            tool_description=(
                "Deep multi-source web research agent -- searches, reads multiple pages, and "
                "synthesizes a single coherent answer. Use for: 'research everything about X', "
                "'tell me everything about X', 'investigate X', 'comprehensive analysis of X', "
                "'compare and contrast X and Y', 'summarize the news about X'. Do NOT use for quick "
                "factual lookups -- use wikipedia_lookup or web_search for those."
            ),
            task_hint=_TASK_SCHEMA_HINTS["research_agent"],
        ),
        AgentSpec(
            callsign="Scribe",
            tool_name="file_agent",
            role="Documents -- reads and answers questions about PDFs, docs, and sheets.",
            module="core.agents.file_agent",
            cls="FileAgent",
            tool_description=(
                "Document intelligence agent -- reads and answers questions about PDFs, Word docs, "
                "spreadsheets, and images. Use for: 'summarize this pdf/document/contract/invoice/"
                "thesis/report', 'what does this file say', 'extract from this', 'what were the "
                "payment terms'. Pass the file reference and the question together in the task string."
            ),
            task_hint=_TASK_SCHEMA_HINTS["file_agent"],
        ),
        AgentSpec(
            callsign="Vitals",
            tool_name="health_agent",
            role="Nutrition and gym -- logs meals, macros, and workout programs.",
            module="core.agents.health_agent",
            cls="HealthAgent",
            tool_description=(
                "Nutrition and gym tracking agent -- logs meals, calculates macros/TDEE, generates "
                "workout programs and recipes. Use for: 'I just ate X', 'log my meal', 'calories "
                "today', 'my macros', 'recipe for X', 'chest day', 'finished my workout', 'generate a "
                "training program', 'what should I do today at the gym'."
            ),
            task_hint=_TASK_SCHEMA_HINTS["health_agent"],
        ),
        AgentSpec(
            callsign="Herald",
            tool_name="comms_agent",
            role="Inbox and messaging -- triages email, drafts replies, sends WhatsApp and Telegram.",
            module="core.agents.comms_agent",
            cls="CommsAgent",
            tool_description=(
                "Inbox and messaging agent -- triages Gmail, drafts and sends replies, and reaches "
                "contacts on WhatsApp and Telegram. Use for: 'check my email', 'what's in my inbox', "
                "'reply to X', 'draft an email to X', 'message X on WhatsApp', 'any Telegram "
                "messages'. Sending is two-step and confirmed; when working unattended this agent "
                "drafts and reports instead of sending."
            ),
            task_hint="The user's email or messaging request, verbatim or lightly cleaned up.",
            confirm_before=_comms_send_tools(),
        ),
        AgentSpec(
            callsign="Chronos",
            tool_name="scheduler_agent",
            role="Calendar, reminders, recurring schedules, and focus blocks.",
            module="core.agents.scheduler_agent",
            cls="SchedulerAgent",
            tool_description=(
                "Time and scheduling agent -- reads and edits the calendar, sets reminders, manages "
                "recurring schedules, and runs focus blocks. Use for: 'what's on tomorrow', 'book me "
                "an hour for X', 'move my 3pm', 'remind me in 20 minutes', 'what do I have recurring', "
                "'block distractions for 2 hours'. Do NOT use for a bare 'what time is it'."
            ),
            task_hint="The user's calendar, reminder, or scheduling request.",
            confirm_before=_scheduler_destructive_tools(),
        ),
        AgentSpec(
            callsign="Abacus",
            tool_name="finance_agent",
            role="Personal money -- expenses, income, invoices, and budgets.",
            module="core.agents.finance_agent",
            cls="FinanceAgent",
            tool_description=(
                "Personal bookkeeping agent -- logs expenses and income, manages invoices and "
                "budgets. Use for: 'I spent 200 on lunch', 'how much did I spend this week', 'what do "
                "clients owe me', 'invoice X for Y', 'set a food budget', 'am I over budget'. This is "
                "personal money only -- stocks and trading go to Midas (stocks_agent)."
            ),
            task_hint="The user's expense, income, invoice, or budget request.",
            confirm_before=_finance_destructive_tools(),
        ),
        AgentSpec(
            callsign="Forge",
            tool_name="dev_agent",
            role="Git, GitHub, code inspection, and developer utilities.",
            module="core.agents.dev_agent",
            cls="DevAgent",
            tool_description=(
                "Engineering agent -- reads repositories, inspects diffs and history, checks GitHub "
                "issues and pull requests, and runs developer utilities. Use for: 'what changed in my "
                "repo', 'show me the diff', 'commit this', 'any open PRs on X', 'check this Python for "
                "syntax errors', 'hash this string'. When working unattended it cannot execute code or "
                "write history -- it reports what it would do."
            ),
            task_hint="The user's git, GitHub, or code request.",
            confirm_before=_dev_destructive_tools(),
        ),
    ]
}

COMMANDER = "El Fager"
INSPECTOR = "Warden"


def tool_names() -> set[str]:
    return set(ROSTER)


def tool_schemas() -> list[dict]:
    """The agent tool definitions spliced into core/brain.py's TOOLS list."""
    return [spec.schema() for spec in ROSTER.values()]


def resolve(name: str) -> AgentSpec | None:
    """Look up a spec by tool name or callsign, case-insensitively."""
    if not name:
        return None
    key = name.strip().lower()
    spec = ROSTER.get(key)
    if spec is not None:
        return spec
    for spec in ROSTER.values():
        if spec.callsign.lower() == key:
            return spec
    return None


def load(name: str, allow_side_effects: bool = True):
    """Instantiate an agent by tool name or callsign. Imports on demand.

    allow_side_effects=False strips the tools named in the spec's
    confirm_before, so an agent working from a mission or the dashboard can
    draft and report but not send, delete, or push on Mo's behalf. Agents
    without confirm_before take no such argument and are built plainly.
    """
    spec = resolve(name)
    if spec is None:
        raise KeyError(f"No agent named '{name}'.")
    cls = getattr(import_module(spec.module), spec.cls)
    if spec.confirm_before:
        return cls(allow_side_effects=allow_side_effects)
    return cls()


def format_roster() -> str:
    """Plain-text roster for the system prompt and the agent_roster tool."""
    lines = [f"{COMMANDER} commands {len(ROSTER)} specialist agents:"]
    for spec in ROSTER.values():
        lines.append(f"  {spec.callsign} ({spec.tool_name}) -- {spec.role}")
    lines.append(f"  {INSPECTOR} -- inspector; verifies every agent's result.")
    return "\n".join(lines)
