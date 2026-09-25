"""Graduate programmes at the target companies: whether each is open, when it
closes, and whether a fresh graduate like Mo can apply.

The programme list ships in the package (programmes.json). Each check reads
the programme's page and has Claude pull out its status and dates; results
live in data/career/programmes.json. A programme that opens, or closes within
a week, is what Mo hears about first.
"""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path

from core.career import store

_SEED = Path(__file__).parent / "programmes.json"
_STATE = "programmes.json"
_PAGE_CHARS = 6000
SOON_DAYS = 7

_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["open", "upcoming", "closed", "unknown"]},
        "opens": {"type": "string", "description": "YYYY-MM-DD or empty"},
        "deadline": {"type": "string", "description": "YYYY-MM-DD or empty"},
        "fresh_grads": {"type": "string", "enum": ["yes", "no", "unclear"]},
        "eligibility": {"type": "string"},
        "how_to_apply": {"type": "string"},
    },
    "required": ["status", "opens", "deadline", "fresh_grads", "eligibility", "how_to_apply"],
    "additionalProperties": False,
}

_SYSTEM = (
    "You read a company's graduate-programme or early-careers page and report only what "
    "it states. status: 'open' if applications are being accepted now, 'upcoming' if it "
    "gives a future opening, 'closed' if it says applications closed, else 'unknown'. "
    "Dates as YYYY-MM-DD, empty when the page gives none. fresh_grads: can someone who "
    "has already graduated (not a current student) apply? eligibility: the stated "
    "requirements in one sentence (graduation years, degrees, military status). "
    "how_to_apply: one sentence."
)


def seeds() -> list[dict]:
    return json.loads(_SEED.read_text(encoding="utf-8"))


def state() -> dict:
    return store.load(_STATE, {})


def check_all() -> str:
    """Read every programme page now. Returns what changed."""
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(_check_one, seeds()))
    saved = state()
    changes = []
    for prog, found in results:
        if found is None:
            continue
        before = saved.get(prog["id"], {})
        if found["status"] == "open" and before.get("status") != "open":
            changes.append(f"{prog['name']} is OPEN" +
                           (f", closes {found['deadline']}" if found["deadline"] else ""))
        saved[prog["id"]] = {**prog, **found,
                             "checked_at": datetime.now().isoformat(timespec="seconds")}
    store.save(_STATE, saved)
    return "; ".join(changes)


def _check_one(prog: dict) -> tuple[dict, "dict | None"]:
    from tools.web_tool import fetch_page
    text = fetch_page(prog["url"], max_chars=_PAGE_CHARS)
    if text.startswith("["):
        return prog, {"status": "unknown", "opens": "", "deadline": "", "fresh_grads": "unclear",
                      "eligibility": "", "how_to_apply": "Page couldn't be read -- open it in Comet."}
    from core.career import claude
    try:
        found = claude.ask(
            f"Today is {date.today().isoformat()}.\nProgramme: {prog['name']}\n"
            f"Page ({prog['url']}):\n\n{text}",
            system=_SYSTEM, schema=_SCHEMA, effort="low", max_tokens=3000)
    except Exception:
        return prog, None
    return prog, found


def days_left(p: dict) -> "int | None":
    try:
        return (date.fromisoformat(p.get("deadline", "")) - date.today()).days
    except ValueError:
        return None


def closing_soon() -> list[dict]:
    """Open programmes Mo can apply to whose deadline is within a week."""
    out = [p for p in state().values()
           if p.get("status") == "open" and p.get("fresh_grads") != "no"
           and (d := days_left(p)) is not None and 0 <= d <= SOON_DAYS]
    return sorted(out, key=days_left)


def summary_text() -> str:
    progs = sorted(state().values(), key=lambda p: (p.get("tier") != "big4",
                                                    p.get("status") != "open"))
    if not progs:
        return "Programmes haven't been checked yet -- say 'check the graduate programmes'."
    lines = []
    for p in progs:
        d = days_left(p)
        when = (f", closes in {d} days ({p['deadline']})" if d is not None and d >= 0
                else f", opens {p['opens']}" if p.get("opens") else "")
        fit = {"no": " -- not open to graduates", "unclear": ""}.get(p.get("fresh_grads"), "")
        lines.append(f"- {p['name']}: {p.get('status', 'unknown')}{when}{fit}. {p.get('eligibility', '')}"
                     f" {p['url']}")
    return "\n".join(lines)
