"""
Email template management — Phase 5A.
Templates stored in data/email_templates.json.
Each entry: {description, to_hint, subject, body} with {placeholder} syntax.
Claude fills in placeholders and calls compose_gmail / create_draft to send.
"""

import json
from pathlib import Path
from core import atomic

TEMPLATES_PATH = Path("data/email_templates.json")

_DEFAULTS = {
    "professor_extension": {
        "description": "Request a deadline extension from a professor",
        "to_hint": "professor / instructor",
        "subject": "Request for Extension – {course_name}",
        "body": (
            "Dear {professor_name},\n\n"
            "I hope this message finds you well. I am writing to request an extension on "
            "{assignment_name}, currently due {due_date}.\n\n"
            "{reason}\n\n"
            "I would greatly appreciate any additional time you could grant. "
            "I am committed to submitting thorough, quality work.\n\n"
            "Thank you for your understanding.\n\n"
            "Best regards,\n{your_name}"
        ),
    },
    "standup_summary": {
        "description": "Send a daily standup / status update to the team",
        "to_hint": "team / manager",
        "subject": "Standup Summary – {date}",
        "body": (
            "Hi team,\n\n"
            "Here is today's standup summary:\n\n"
            "✅ Done:\n{done}\n\n"
            "🔄 In Progress:\n{in_progress}\n\n"
            "🚧 Blockers:\n{blockers}\n\n"
            "Best,\n{your_name}"
        ),
    },
    "meeting_request": {
        "description": "Request a meeting with a colleague, professor, or contact",
        "to_hint": "colleague / professor / professional contact",
        "subject": "Meeting Request – {topic}",
        "body": (
            "Dear {name},\n\n"
            "I hope you are doing well. I would like to schedule a brief meeting to discuss {topic}.\n\n"
            "I am available on {availability}. Please let me know if any of these times work for you, "
            "or feel free to suggest an alternative.\n\n"
            "Thank you for your time.\n\n"
            "Best regards,\n{your_name}"
        ),
    },
    "late_submission": {
        "description": "Notify a professor about a late submission",
        "to_hint": "professor",
        "subject": "Late Submission – {assignment_name}",
        "body": (
            "Dear {professor_name},\n\n"
            "I am writing to inform you that I will be submitting {assignment_name} late due to {reason}.\n\n"
            "I sincerely apologise for the inconvenience and take full responsibility. "
            "I understand this may affect my grade.\n\n"
            "Thank you for your understanding.\n\n"
            "Best regards,\n{your_name}"
        ),
    },
    "internship_application": {
        "description": "Apply for an internship position",
        "to_hint": "HR / hiring manager",
        "subject": "Internship Application – {position} – {your_name}",
        "body": (
            "Dear {hiring_manager},\n\n"
            "I am writing to express my interest in the {position} internship at {company}. "
            "I am a {year} student studying {major} at {university}.\n\n"
            "{why_interested}\n\n"
            "I have attached my CV for your consideration and would welcome the opportunity "
            "to discuss how I can contribute to your team.\n\n"
            "Thank you for your time.\n\n"
            "Best regards,\n{your_name}"
        ),
    },
    "group_project_update": {
        "description": "Send a progress update to a group project team",
        "to_hint": "project team members",
        "subject": "Project Update – {project_name}",
        "body": (
            "Hi everyone,\n\n"
            "Quick update on {project_name}:\n\n"
            "📌 Progress so far:\n{progress}\n\n"
            "📅 Next steps:\n{next_steps}\n\n"
            "⚠️ Action needed:\n{action_needed}\n\n"
            "Let me know if you have any questions. See you at our next meeting on {next_meeting}.\n\n"
            "Best,\n{your_name}"
        ),
    },
}


def _load() -> dict:
    if not TEMPLATES_PATH.exists():
        TEMPLATES_PATH.parent.mkdir(parents=True, exist_ok=True)
        atomic.write(TEMPLATES_PATH,
            json.dumps(_DEFAULTS, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return json.loads(TEMPLATES_PATH.read_text(encoding="utf-8"))


def _save(templates: dict):
    atomic.write(TEMPLATES_PATH,
        json.dumps(templates, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def list_email_templates() -> str:
    templates = _load()
    if not templates:
        return "No email templates saved yet. Use save_email_template to create one."
    lines = ["Available email templates:\n"]
    for name, t in templates.items():
        lines.append(f"  • {name}: {t.get('description', '(no description)')}")
    lines.append(
        "\nUse get_email_template(name) to view a template's subject and body."
    )
    return "\n".join(lines)


def get_email_template(name: str) -> str:
    templates = _load()
    key = name.lower().replace(" ", "_")
    if key not in templates:
        available = ", ".join(templates.keys())
        return f"Template '{name}' not found. Available: {available}"
    t = templates[key]
    return (
        f"Template: {key}\n"
        f"Description: {t.get('description', '')}\n"
        f"To (hint): {t.get('to_hint', '')}\n"
        f"Subject: {t.get('subject', '')}\n\n"
        f"Body:\n{t.get('body', '')}\n\n"
        f"Fill in all {{placeholders}} with the actual values, "
        f"then use compose_gmail or create_draft to send."
    )


def save_email_template(
    name: str,
    description: str,
    subject: str,
    body: str,
    to_hint: str = "",
) -> str:
    templates = _load()
    key = name.lower().replace(" ", "_")
    templates[key] = {
        "description": description,
        "to_hint": to_hint,
        "subject": subject,
        "body": body,
    }
    _save(templates)
    return f"Saved email template '{key}'."


def delete_email_template(name: str) -> str:
    templates = _load()
    key = name.lower().replace(" ", "_")
    if key not in templates:
        return f"Template '{key}' not found."
    del templates[key]
    _save(templates)
    return f"Deleted email template '{key}'."
