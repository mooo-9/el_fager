"""Mo's CV as a profile the pipeline scores and writes from, plus the answers
application forms keep asking for.

Nothing here is invented: answers Mo hasn't given stay empty, and the review
page lists them so he can fill them in by voice ("my expected salary is ...").
"""
from pathlib import Path

from core.career import store

# The questions Egyptian application forms ask most. Empty until Mo answers.
ANSWER_KEYS = {
    "phone": "Phone number",
    "email": "Email address for applications",
    "linkedin_url": "LinkedIn profile URL",
    "military_status": "Military status (exempted / completed / postponed)",
    "university": "University",
    "graduation_year": "Graduation year",
    "gpa": "GPA or grade",
    "expected_salary": "Expected monthly salary (EGP)",
    "availability": "Start date / notice period",
    "english_level": "English level",
    "willing_to_relocate": "Willing to relocate or work on-site",
}

_EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "headline": {"type": "string"},
        "education": {"type": "string"},
        "skills": {"type": "array", "items": {"type": "string"}},
        "experience": {"type": "array", "items": {"type": "string"}},
        "projects": {"type": "array", "items": {"type": "string"}},
        "certifications": {"type": "array", "items": {"type": "string"}},
        "languages": {"type": "array", "items": {"type": "string"}},
        "email": {"type": "string"},
        "phone": {"type": "string"},
        "linkedin_url": {"type": "string"},
        "graduation_year": {"type": "string"},
        "gpa": {"type": "string"},
    },
    "required": ["name", "headline", "education", "skills", "experience", "projects",
                 "certifications", "languages", "email", "phone", "linkedin_url",
                 "graduation_year", "gpa"],
    "additionalProperties": False,
}


def load() -> dict:
    return store.load("profile.json", {})


def save(profile: dict) -> None:
    store.save("profile.json", profile)


def has_cv() -> bool:
    p = load()
    return bool(p.get("cv_path")) and Path(p["cv_path"]).exists()


def import_cv(path: str) -> str:
    """Read Mo's CV (PDF or Word) into the profile. Answers the CV holds
    (phone, GPA...) fill empty answers; ones Mo gave by hand are kept."""
    cv = Path(path).expanduser()
    if not cv.exists():
        return f"Error: no file at {cv}"
    text = _cv_text(cv)
    if len(text.strip()) < 200:
        return f"Error: couldn't read text from {cv.name} -- is it a scanned image? Export it as a text PDF."

    from core.career import claude
    fields = claude.ask(
        f"CV text:\n\n{text}",
        system=("Extract this CV into the given fields, copying facts exactly as written. "
                "Leave a field empty (\"\" or []) when the CV doesn't state it. Never infer "
                "or embellish."),
        schema=_EXTRACT_SCHEMA, effort="low",
    )
    if fields is None:
        return "Error: couldn't read the CV -- try again."

    profile = load()
    answers = profile.get("answers", {})
    for key in ("email", "phone", "linkedin_url", "graduation_year", "gpa"):
        if fields.get(key) and not answers.get(key):
            answers[key] = fields[key]
    profile.update({k: v for k, v in fields.items() if k in
                    ("name", "headline", "education", "skills", "experience",
                     "projects", "certifications", "languages")})
    profile.update({"cv_path": str(cv), "cv_text": text, "answers": answers})
    save(profile)

    missing = missing_answers(profile)
    note = f" Still missing: {', '.join(missing)}." if missing else ""
    return (f"CV imported: {profile['name'] or cv.name} -- {len(profile['skills'])} skills, "
            f"{len(profile['experience'])} experience entries.{note}")


def _cv_text(cv: Path) -> str:
    # PDFs through pymupdf, which requirements.txt installs; file_agent's
    # pdfplumber isn't in it.
    if cv.suffix.lower() == ".pdf":
        try:
            import fitz
            with fitz.open(str(cv)) as doc:
                return "\n".join(page.get_text() for page in doc)
        except Exception:
            return ""
    from core.agents.file_agent import FileAgent
    return FileAgent()._extract_content(cv)


def set_answer(key: str, answer: str) -> str:
    key = key.strip().lower().replace(" ", "_")
    if key not in ANSWER_KEYS:
        return f"Error: unknown question '{key}'. Known: {', '.join(ANSWER_KEYS)}."
    profile = load()
    profile.setdefault("answers", {})[key] = answer.strip()
    save(profile)
    return f"Saved: {ANSWER_KEYS[key]} = {answer.strip()}"


def missing_answers(profile: "dict | None" = None) -> list[str]:
    answers = (profile if profile is not None else load()).get("answers", {})
    return [k for k in ANSWER_KEYS if not answers.get(k)]


def as_text(profile: "dict | None" = None) -> str:
    """The profile as the prompts see it. Before a CV is imported it is only
    what El Fager knows from Mo's profile.json -- scores and drafts made from it
    are practice runs."""
    p = profile if profile is not None else load()
    if not p.get("cv_text"):
        return ("Mohamed (Mo), Cairo, Egypt. Business Informatics graduate. "
                "No CV imported yet: nothing else is known.")
    answers = p.get("answers", {})
    lines = [f"Name: {p.get('name', '')}", f"Headline: {p.get('headline', '')}",
             f"Education: {p.get('education', '')}"]
    for key in ("skills", "experience", "projects", "certifications", "languages"):
        if p.get(key):
            lines.append(f"{key.capitalize()}: " + "; ".join(p[key]))
    lines += [f"{ANSWER_KEYS[k]}: {v}" for k, v in answers.items() if v and k in ANSWER_KEYS]
    return "\n".join(lines)
