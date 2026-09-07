"""
Commander tools -- how El Fager assigns work to his agents and holds them to it.

delegate() is the supervised path: the named agent runs, Warden inspects the
result against the acceptance criteria, a failure is retried once, and what
comes back says whether it actually passed. All return strings are cp1252-safe
(they are TTS-bound).
"""


def delegate(agent: str, task: str, acceptance: str | None = None) -> str:
    """Assign a task to one named agent and verify it was really done."""
    from core.agents import registry
    from core.agents.supervisor import assign

    spec = registry.resolve(agent)
    if spec is None:
        known = ", ".join(s.callsign for s in registry.ROSTER.values())
        return f"I have no agent called '{agent}'. My agents are: {known}."

    report = assign(spec.tool_name, task, acceptance=acceptance,
                    verify=True, source="delegate")
    if report.verdict == "blocked":
        return report.result
    if report.ok:
        return f"{report.callsign} finished it. {report.result}"
    return (f"{report.callsign} could not finish that after "
            f"{report.attempts} attempts. {report.reason} "
            f"Tell me how you want to proceed.")


def agent_roster() -> str:
    """Who El Fager commands, and who is working right now."""
    from core.agents import ledger, registry

    lines = [registry.format_roster()]
    running = ledger.active_runs()
    if running:
        lines.append("Working right now:")
        for run in running:
            lines.append(f"  {run['callsign']}: {run['task'][:60]} (since {run['since'][11:16]})")
    else:
        lines.append("No agent is working right now.")
    return "\n".join(lines)


def agent_report(agent: str | None = None, days: int = 1) -> str:
    """What the agents did and how much of it passed inspection."""
    from core.agents import ledger, registry

    if agent:
        spec = registry.resolve(agent)
        if spec is None:
            return f"I have no agent called '{agent}'."
        return ledger.format_report(spec.callsign, days=days)
    return ledger.format_report(None, days=days)
