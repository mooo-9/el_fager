"""A prep sheet for one interview: how the company interviews, the questions
likely to come, and how Mo can answer them from his real experience."""
from core.career import claude, profile, tracker

_SYSTEM = (
    "You coach a Business Informatics graduate in Cairo for a specific interview. Be "
    "concrete and honest. Answer suggestions must use only experience in his profile; "
    "where his profile has nothing to draw on, say what to prepare instead. Plain text, "
    "short headed sections, no emojis."
)


def prep(company: str, role: str = "") -> str:
    app = _tracked(company, role)
    role = role or (app or {}).get("title", "")
    posting = (app or {}).get("description", "")

    from core.agents.research_agent import ResearchAgent
    research = ResearchAgent().run(
        f"{company} Egypt interview process {role} graduate assessment questions")

    sheet = claude.ask(
        f"Company: {company}\nRole: {role or 'not specified'}\n\n"
        f"His profile:\n{profile.as_text()}\n\n"
        f"Job posting:\n{posting or '(not available)'}\n\n"
        f"What's known about their interviews:\n{research}\n\n"
        "Write the prep sheet: 1) the likely stages (for Big 4 firms include online "
        "aptitude tests, video interviews and assessment centres if they apply); "
        "2) eight likely questions, each with how he should answer from his profile; "
        "3) three questions for him to ask them; 4) what to revise the night before.",
        system=_SYSTEM, effort="medium", model=claude.model_for(company),
    )
    return sheet or "Couldn't write the prep sheet -- try again."


def _tracked(company: str, role: str) -> "dict | None":
    low = company.lower()
    matches = [a for a in tracker.all_apps().values()
               if low in (a.get("company", "") + " " + a.get("company_key", "")).lower()
               and (not role or role.lower() in a.get("title", "").lower())]
    matches.sort(key=lambda a: a.get("status") != "interview")
    return matches[0] if matches else None
