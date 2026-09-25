"""The job-application pipeline as tools the brain can call. The work lives
in core/career/; these only check inputs and say what happened."""
from datetime import datetime, timedelta

_NIGHTLY_AT = 2          # 02:00, so the batch is ready by morning
_NIGHTLY_TASK = ("Run the nightly job hunt: call check_application_replies, then "
                 "prepare_applications. Report in one or two sentences.")


def prepare_applications() -> str:
    from core.career import pipeline
    if not pipeline.start_in_background(pipeline.prepare_batch):
        return "The pipeline is already running -- the batch will be ready when it finishes."
    return ("Preparing today's batch in the background: searching the boards and the Big 4 "
            "career sites, scoring each job, and drafting applications. It takes a few "
            f"minutes; review it at {pipeline.review_url()} when it's done.")


def review_applications() -> str:
    from core.career import pipeline
    return pipeline.review_text()


def approve_applications(skip: "list[str] | None" = None, only: "list[str] | None" = None) -> str:
    from core.career import pipeline
    return pipeline.approve(skip=skip, only=only)


def application_status() -> str:
    from core.career import pipeline
    return pipeline.status_text()


def check_application_replies() -> str:
    from core.career import pipeline
    return pipeline.check_replies()


def import_cv(path: str) -> str:
    from core.career import profile
    return profile.import_cv(path)


def set_application_answer(question: str, answer: str) -> str:
    from core.career import profile
    return profile.set_answer(question, answer)


def interview_prep(company: str, role: str = "") -> str:
    from core.career import interview
    return interview.prep(company, role)


def application_settings(live: "bool | None" = None, nightly: "bool | None" = None,
                         daily_target: "int | None" = None, min_score: "int | None" = None,
                         linkedin_daily_cap: "int | None" = None,
                         big4_per_firm_per_month: "int | None" = None) -> str:
    from core.career import profile, store
    notes = []
    if live and not profile.has_cv():
        return "Error: import your CV first (say 'import my CV from <path>') -- live mode sends it."
    changes = {k: v for k, v in {
        "live": live, "daily_target": daily_target, "min_score": min_score,
        "linkedin_daily_cap": linkedin_daily_cap,
        "big4_per_firm_per_month": big4_per_firm_per_month}.items() if v is not None}
    if nightly is not None:
        notes.append(_set_nightly(nightly))
    s = store.update_settings(**changes)
    mode = "LIVE -- approved applications are sent" if s["live"] else "practice -- nothing is sent"
    notes.insert(0, (f"Mode: {mode}. Daily target {s['daily_target']}, minimum score "
                     f"{s['min_score']}, LinkedIn cap {s['linkedin_daily_cap']}/day, "
                     f"Big 4 cap {s['big4_per_firm_per_month']} per firm per month. "
                     f"Nightly job hunt: {'on' if s['nightly_task_id'] else 'off'}."))
    return " ".join(n for n in notes if n)


def _set_nightly(on: bool) -> str:
    from core.autonomous_tasks import AutonomousTaskManager
    from core.career import store
    tasks = AutonomousTaskManager()
    current = store.settings()["nightly_task_id"]
    if on:
        if current:
            return ""
        now = datetime.now()
        nxt = now.replace(hour=_NIGHTLY_AT, minute=0, second=0, microsecond=0)
        if nxt <= now:
            nxt += timedelta(days=1)
        task = tasks.add(_NIGHTLY_TASK, delay_hours=(nxt - now).total_seconds() / 3600,
                         recurring_hours=24)
        store.update_settings(nightly_task_id=task["id"])
        return f"Nightly job hunt on: every night at {_NIGHTLY_AT:02d}:00."
    if current:
        tasks.delete(current)
        store.update_settings(nightly_task_id="")
    return "Nightly job hunt off."
