"""The nightly batch, Mo's approval, the sending, and what comes back."""
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from core.career import appliers, companies, profile, scorer, sources, store, tailor, tracker

_busy = threading.Lock()

# Seconds between browser applications: a person's pace, not a bot's.
_BROWSER_PAUSE = (45, 120)

# Statuses that count as "applied to this firm" for the Big 4 cap.
_COUNTS_AS_APPLIED = ("ready", "approved", "practice", "applied", "needs_you",
                      "interview", "rejected", "replied")

# Titles in Mo's field: AI, data analyst and business analyst roles. "Analyst"
# or "graduate" alone isn't: the first practice run spent 17 of 40 slots on
# PepsiCo supply-chain and HR analysts.
_FIELD_RE = re.compile(
    r"\b(data analy\w*|data scien\w*|business analy\w*|analytics|business intelligence"
    r"|bi|power bi|machine learning|ml|ai|artificial intelligence|nlp|llm)\b", re.IGNORECASE)


def _in_field(job: dict) -> bool:
    return bool(_FIELD_RE.search(job["title"]))


# Postings asking this many years of experience or more aren't scored: in the
# second practice run most skips were exactly these, each costing a scoring
# call and a slot a reachable job could have had.
_MAX_YEARS = 3
# "3+ years of experience", "3-7 years analytics experience", "Experience: 4+ years".
_YEARS_RE = re.compile(
    r"(\d{1,2})\s*\+?\s*(?:(?:-|–|to)\s*\d{1,2}\s*\+?\s*)?years?\b[^.\n]{0,40}?\bexperience"
    r"|\bexperience\b[^.\n]{0,25}?(\d{1,2})\s*\+?\s*(?:(?:-|–|to)\s*\d{1,2}\s*)?years?\b",
    re.IGNORECASE)


def _years_asked(text: str) -> int:
    """The fewest years of experience the posting asks for; 0 if it names none."""
    found = [int(m.group(1) or m.group(2)) for m in _YEARS_RE.finditer(text or "")]
    return min(found) if found else 0


def _within_reach(jobs: list, budget: int) -> "tuple[list, int]":
    """Up to `budget` jobs in order, each carrying its posting text, passing
    over postings that ask for _MAX_YEARS+ years (recorded as skipped).
    Reading a posting costs no Claude call; scoring it does."""
    kept, dropped = [], 0
    with ThreadPoolExecutor(max_workers=4) as pool:
        for start in range(0, len(jobs), 8):
            if len(kept) >= budget:
                break
            chunk = jobs[start:start + 8]
            texts = pool.map(lambda j: j.get("description") or scorer.read_description(j["url"]),
                             chunk)
            for job, text in zip(chunk, texts):
                job = {**job, "description": text}
                years = _years_asked(text)
                if years >= _MAX_YEARS:
                    _record({**job, "score": 0, "fit": f"Asks for {years}+ years of experience.",
                             "missing": [], "channel": appliers.channel_for(job)},
                            "skipped", f"asks for {years}+ years")
                    dropped += 1
                else:
                    kept.append(job)
    return kept[:budget], dropped


def _take_turns(firms: list, others: list) -> list:
    """One from each list in turn, then the rest of the longer one."""
    out = []
    for i in range(max(len(firms), len(others))):
        out += firms[i:i + 1] + others[i:i + 1]
    return out


# ── Prepare ──────────────────────────────────────────────────────────────────

# The 26 Sep 2026 run at a daily target of 20 cost $0.97 in API calls: about
# 5 cents for each job the target asks for (scoring twice that many, drafting).
_COST_PER_TARGET_JOB_USD = 0.05


def run_estimate() -> float:
    """What one prepare_batch run is expected to cost, in USD."""
    return store.settings()["daily_target"] * _COST_PER_TARGET_JOB_USD


def prepare_batch() -> str:
    """Find, score and draft up to the daily target. The drafts wait as
    "ready" for Mo's review; nothing is sent here."""
    s = store.settings()
    if not profile.has_cv():
        # Scores and letters written without a CV are guesses, and they cost
        # money every night. Programme deadlines don't depend on it.
        extras = _nightly_extras(s, referrals=False)
        summary = ("No CV imported yet, so no jobs were scored or drafted. Say 'import my "
                   "CV from <path>' to start." + (f" {extras}" if extras else ""))
        _notify(summary)
        return summary
    prof = profile.load()
    ptext = profile.as_text(prof)
    known = tracker.all_apps()

    # Jobs that scored well but didn't fit in an earlier day's target go first;
    # they're already scored.
    waiting = tracker.with_status("waiting")
    new = [j for j in sources.gather(s) if tracker.job_id(j["url"]) not in known]
    # Jobs in Mo's field first: top firms' careers sites list all their Egypt
    # jobs, and their sales and plant roles would otherwise take every scoring
    # slot. Within the field, target firms (Big 4 first) and the boards' other
    # employers take turns, so neither crowds the other out.
    new.sort(key=lambda j: companies.TIER_RANK[j["tier"]])
    field = [j for j in new if _in_field(j)]
    new = (_take_turns([j for j in field if j["tier"]], [j for j in field if not j["tier"]])
           + [j for j in new if not _in_field(j)])
    # Scoring costs a Claude call per job: twice the target is enough to fill it.
    new, too_senior = _within_reach(new, max(0, s["daily_target"] * 2 - len(waiting)))
    with ThreadPoolExecutor(max_workers=4) as pool:
        scored = list(pool.map(lambda j: _scored(j, ptext), new))

    candidates = sorted(waiting + scored,
                        key=lambda a: (companies.TIER_RANK[a["tier"]], -a["score"]))
    firm_counts = _big4_counts_this_month()
    picked, skipped = [], too_senior
    for app in candidates:
        reason = _skip_reason(app, s, firm_counts)
        if reason:
            _record(app, "skipped", reason)
            skipped += 1
        elif len(picked) >= s["daily_target"]:
            _record(app, "waiting", "over today's target")
        else:
            picked.append(app)
            if app["tier"] == "big4":
                firm_counts[app["company_key"]] = firm_counts.get(app["company_key"], 0) + 1

    with ThreadPoolExecutor(max_workers=4) as pool:
        drafted = list(pool.map(lambda a: (a, tailor.draft(a, ptext, a["channel"])), picked))
    ready = 0
    for app, draft in drafted:
        if draft is None:
            _record(app, "failed", "couldn't draft the application")
        else:
            app["draft"] = draft
            _record(app, "ready", "drafted")
            ready += 1

    extras = _nightly_extras(s)
    big4 = sum(1 for a, d in drafted if d and a["tier"] == "big4")
    top = sum(1 for a, d in drafted if d and a["tier"] == "top")
    mode = "" if s["live"] and profile.has_cv() else " (practice mode: nothing will be sent)"
    summary = (f"{ready} applications ready for your review{mode}: {big4} Big 4, {top} top "
               f"companies, {ready - big4 - top} others. {skipped} skipped. "
               f"Review them at {review_url()}")
    if extras:
        summary += " " + extras
    _notify(summary)
    return summary


def _nightly_extras(s: dict, referrals: bool = True) -> str:
    """The rest of the nightly hunt: programme pages once a week, and new
    people to ask for referrals. Neither may stop the batch."""
    from core.career import programmes
    from core.career import referrals as refs
    notes = []
    try:
        checked = [p.get("checked_at", "") for p in programmes.state().values()]
        week_ago = (datetime.now() - timedelta(days=6)).isoformat()
        if not checked or min(checked) < week_ago:
            opened = programmes.check_all()
            if opened:
                notes.append(f"Programmes: {opened}.")
    except Exception:
        pass
    try:
        if referrals and s["referrals_per_day"] > 0:
            found = refs.find(count=s["referrals_per_day"])
            if not found.startswith("No new"):
                notes.append(found)
    except Exception:
        pass
    return " ".join(notes)


def _scored(job: dict, ptext: str) -> dict:
    app = dict(job)
    # Some job lists carry the full text (PepsiCo's); the rest are read.
    app["description"] = job.get("description") or scorer.read_description(job["url"])
    app["hr_email"] = scorer.hr_email(app["description"])
    app.update(scorer.score(app, ptext))
    app["channel"] = appliers.channel_for(app)
    return app


def _skip_reason(app: dict, s: dict, firm_counts: dict) -> str:
    if not app.get("in_egypt", True):
        return "not in Egypt"
    if app.get("level") in ("mid", "senior"):
        return f"{app['level']}-level role"
    if app["score"] < s["min_score"]:
        return f"score {app['score']} below {s['min_score']}"
    if app["tier"] == "big4" and firm_counts.get(app["company_key"], 0) >= s["big4_per_firm_per_month"]:
        return f"already {s['big4_per_firm_per_month']} applications to {app['company_key']} this month"
    return ""


def _big4_counts_this_month() -> dict:
    since = (datetime.now() - timedelta(days=30)).isoformat(timespec="seconds")
    counts: dict = {}
    for a in tracker.all_apps().values():
        if a.get("tier") == "big4" and a.get("status") in _COUNTS_AS_APPLIED \
                and a.get("found_at", "") >= since:
            counts[a["company_key"]] = counts.get(a["company_key"], 0) + 1
    return counts


def _record(app: dict, status: str, note: str) -> None:
    if app.get("id") and app["id"] in tracker.all_apps():
        tracker.update(app["id"], status, note, **{k: v for k, v in app.items()
                                                    if k not in ("id", "events", "status")})
    else:
        app["status"] = status
        app["events"] = [{"at": datetime.now().isoformat(timespec="seconds"),
                          "status": status, "note": note}]
        tracker.add(app)


# ── Review and approve ───────────────────────────────────────────────────────

def ready_batch() -> list[dict]:
    """The batch as Mo reviews it: Big 4 first, then top companies, best fit first."""
    return sorted(tracker.with_status("ready"),
                  key=lambda a: (companies.TIER_RANK[a.get("tier", "")], -a.get("score", 0)))


def review_url() -> str:
    from core.dashboard import _SETTINGS_PATH, _read_json
    port = _read_json(_SETTINGS_PATH, {}).get("dashboard_port", 8765)
    return f"http://127.0.0.1:{port}/jobs"


def review_text(limit: int = 15) -> str:
    batch = ready_batch()
    if not batch:
        return "No applications waiting for review."
    lines = [f"{len(batch)} applications ready (showing {min(limit, len(batch))}). "
             f"Full list with the drafts: {review_url()}"]
    for a in batch[:limit]:
        tier = {"big4": " [Big 4]", "top": " [top]"}.get(a.get("tier", ""), "")
        lines.append(f"- {a['id']}: {a['title']} -- {a.get('company') or '?'}{tier}, "
                     f"score {a['score']}, via {a['channel']}")
    missing = profile.missing_answers()
    if missing:
        lines.append("Answers forms will ask for that you haven't given: " + ", ".join(missing))
    return "\n".join(lines)


def approve(skip: "list[str] | None" = None, only: "list[str] | None" = None) -> str:
    """Approve the ready batch. `only` approves just those ids; everything
    else in the batch -- and anything in `skip` -- is skipped."""
    skip = set(skip or [])
    only = set(only) if only else None
    approved = skipped = 0
    for a in tracker.with_status("ready"):
        if a["id"] in skip or (only is not None and a["id"] not in only):
            tracker.update(a["id"], "skipped", "Mo unticked it")
            skipped += 1
        else:
            tracker.update(a["id"], "approved", "approved in review")
            approved += 1
    started = start_in_background(run_approved)
    tail = " Sending now in the background." if started else " A run is already going; they're queued."
    return f"Approved {approved}, skipped {skipped}.{tail if approved else ''}"


# ── Send ─────────────────────────────────────────────────────────────────────

def run_approved(pause: bool = True) -> str:
    s = store.settings()
    prof = profile.load()
    live = s["live"] and profile.has_cv()
    midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    linkedin_today = sum(1 for a in tracker.reached_status_since("applied", midnight)
                         if a.get("channel") == "linkedin")

    counts: dict = {}
    todo = sorted(tracker.with_status("approved"),
                  key=lambda a: companies.TIER_RANK[a.get("tier", "")])
    for app in todo:
        if not live:
            tracker.update(app["id"], "practice", f"practice mode: would apply via {app['channel']}")
            counts["practice"] = counts.get("practice", 0) + 1
            continue
        if app["channel"] == "linkedin":
            if linkedin_today >= s["linkedin_daily_cap"]:
                continue              # stays approved; goes tomorrow
            linkedin_today += 1
        status, note = appliers.apply(app, prof)
        tracker.update(app["id"], status, note, applied_at=datetime.now().isoformat(timespec="seconds"))
        counts[status] = counts.get(status, 0) + 1
        if pause and app["channel"] in appliers.BROWSER_CHANNELS:
            time.sleep(random.uniform(*_BROWSER_PAUSE))

    summary = _counts_text(counts) or "Nothing approved to send."
    if counts:
        _notify("Job applications: " + summary)
    return summary


def _counts_text(counts: dict) -> str:
    words = {"applied": "sent", "practice": "practice runs (not sent)",
             "needs_you": "waiting for you in Comet", "failed": "failed"}
    return ", ".join(f"{n} {words.get(k, k)}" for k, n in counts.items())


def start_in_background(fn) -> bool:
    """Run fn on a daemon thread unless a pipeline run is already going."""
    if not _busy.acquire(blocking=False):
        return False

    def go():
        try:
            fn()
        finally:
            _busy.release()

    threading.Thread(target=go, daemon=True, name="career-pipeline").start()
    return True


# ── Replies ──────────────────────────────────────────────────────────────────

_INTERVIEW_RE = re.compile(r"interview|assessment|shortlist|next step|invitation|schedule a call",
                           re.IGNORECASE)
_REJECTED_RE = re.compile(r"unfortunately|regret|not been selected|other candidates|"
                          r"not moving forward|not to proceed", re.IGNORECASE)


def check_replies() -> str:
    """Read the last two weeks of inbox for answers from companies Mo applied to."""
    from tools import gmail_tool
    service = gmail_tool.get_gmail_service() if gmail_tool.GMAIL_AVAILABLE else None
    if service is None:
        return "Gmail isn't set up, so replies can't be checked."
    sent = tracker.with_status("applied", "needs_you", "replied", "interview")
    if not sent:
        return "No sent applications to check replies for."

    listing = service.users().messages().list(
        userId="me", q="in:inbox newer_than:14d -from:me", maxResults=50).execute()
    found = []
    for ref in listing.get("messages", []):
        if any(ref["id"] in a.get("reply_ids", []) for a in tracker.all_apps().values()):
            continue
        msg = service.users().messages().get(
            userId="me", id=ref["id"], format="metadata",
            metadataHeaders=["From", "Subject"]).execute()
        headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
        text = f"{headers.get('From', '')} {headers.get('Subject', '')} {msg.get('snippet', '')}"
        app = _app_for(text, sent)
        if app is None:
            continue
        status = ("interview" if _INTERVIEW_RE.search(text)
                  else "rejected" if _REJECTED_RE.search(text) else "replied")
        if status == "replied" and app["status"] == "interview":
            status = "interview"      # a scheduling email doesn't undo the interview
        tracker.update(app["id"], status, headers.get("Subject", "")[:120],
                       reply_ids=app.get("reply_ids", []) + [ref["id"]])
        found.append((status, app))

    if not found:
        return "No new replies from companies you applied to."
    lines = [f"{s.upper()}: {a['title']} at {a.get('company')}" for s, a in found]
    interviews = [a for s, a in found if s == "interview"]
    if interviews:
        _notify("Interview news: " + "; ".join(f"{a['title']} at {a.get('company')}"
                                               for a in interviews))
    return "\n".join(lines)


def _app_for(text: str, apps: list[dict]) -> "dict | None":
    low = text.lower()
    for a in apps:
        for name in {a.get("company", ""), a.get("company_key", "")}:
            if len(name) >= 3 and re.search(rf"(?<!\w){re.escape(name.lower())}(?!\w)", low):
                return a
    return None


# ── Status ───────────────────────────────────────────────────────────────────

def status_text() -> str:
    s = store.settings()
    apps = list(tracker.all_apps().values())
    by: dict = {}
    for a in apps:
        by[a.get("status")] = by.get(a.get("status"), 0) + 1
    week_ago = datetime.now() - timedelta(days=7)
    sent_week = len(tracker.reached_status_since("applied", week_ago))
    follow = [a for a in tracker.with_status("applied")
              if a.get("channel") == "email"
              and a.get("applied_at", "9") < (datetime.now() - timedelta(days=10)).isoformat()]

    mode = "LIVE" if s["live"] and profile.has_cv() else "PRACTICE (nothing is sent)"
    lines = [f"Mode: {mode}. Daily target {s['daily_target']}, minimum score {s['min_score']}."]
    if not profile.has_cv():
        lines.append("No CV imported yet -- say 'import my CV from <path>'.")
    order = ["ready", "approved", "applied", "needs_you", "interview", "replied", "rejected",
             "practice", "waiting", "skipped", "failed"]
    lines.append("Applications: " + ", ".join(f"{by[k]} {k}" for k in order if by.get(k)))
    lines.append(f"Sent in the last 7 days: {sent_week}.")
    if follow:
        lines.append(f"{len(follow)} emailed 10+ days ago with no reply -- worth a follow-up: "
                     + "; ".join(f"{a['title']} at {a.get('company')}" for a in follow[:5]))
    missing = profile.missing_answers()
    if missing:
        lines.append("Answers still missing: " + ", ".join(missing))
    return "\n".join(lines)


def _notify(text: str) -> None:
    try:
        from core.notifier import get_notifier
        get_notifier().send(text)
    except Exception:
        pass
