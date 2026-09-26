"""The application text for one job, written from Mo's profile only."""

_SCHEMA = {
    "type": "object",
    "properties": {
        "subject": {"type": "string"},
        "body": {"type": "string"},
    },
    "required": ["subject", "body"],
    "additionalProperties": False,
}

_SYSTEM = (
    "You write job applications for Mohamed, a Business Informatics graduate in Cairo. "
    "Use only facts in his profile: never invent experience, skills, grades or numbers. "
    "State each fact no stronger than the profile does: keep its verbs (if it says he used "
    "something, don't say he built it) and its ratings word for word, and add no soft "
    "skills, traits or abilities it doesn't state. "
    "Plain, confident English, no clichés, under 180 words. Connect two or three of his "
    "real strengths to what the posting asks for. If the profile is thin, keep it short "
    "rather than padding it. No placeholders in brackets."
)

_SHAPE = {
    "email": ("An email to the recruiter that will carry his CV as an attachment. "
              "Subject: 'Application: <job title> - <his name>'. Body: greeting, why this "
              "role, what he brings, a line saying his CV is attached, sign-off with his "
              "name and phone if known."),
    "form": ("A cover letter for the posting's application form. Subject: the job title. "
             "Body: the letter itself, opening with 'Dear Hiring Team,', no address block, "
             "signed with his name."),
}


def draft(job: dict, profile_text: str, channel: str) -> "dict | None":
    """{"subject", "body"}, or None when Claude declines."""
    from core.career import claude
    shape = _SHAPE["email" if channel == "email" else "form"]
    firm_note = ""
    if job.get("tier") == "big4":
        firm_note = ("\nThis is a Big 4 firm: name the service line the role belongs to "
                     "and why that line, in one sentence.")
    return claude.ask(
        f"{shape}{firm_note}\n\nHis profile:\n{profile_text}\n\n"
        f"Job: {job['title']} at {job.get('company') or 'the company'}\n\n"
        f"Posting:\n{job.get('description') or '(not available)'}",
        system=_SYSTEM, schema=_SCHEMA, effort="medium",
        model=claude.model_for(job.get("company_key") or job.get("company", "")),
    )
