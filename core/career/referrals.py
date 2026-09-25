"""People at the target companies who could refer Mo, and what to send them.

An employee's referral gets a CV read where a cold application often
doesn't. This finds people through a web search of public LinkedIn profiles
(alumni of Mo's university first), and drafts a connection note and a
referral request for each. Mo sends them himself: LinkedIn restricts accounts
that message at machine pace, and a referral ask should come from him.

Stored in data/career/referrals.json:
  to_send -> sent -> replied / referred     (or skipped)
"""
import hashlib
import re
from datetime import datetime

from core.career import companies, profile, store, tracker

_FILE = "referrals.json"
_PROFILE_URL = re.compile(r"linkedin\.com/in/[^/?#]+")
_NOTE_LIMIT = 300              # LinkedIn's cap on a connection note

_SCHEMA = {
    "type": "object",
    "properties": {
        "note": {"type": "string"},
        "message": {"type": "string"},
    },
    "required": ["note", "message"],
    "additionalProperties": False,
}

_SYSTEM = (
    "You write short, genuine networking messages for Mohamed, a Business Informatics "
    "graduate in Cairo looking for his first job. Use only facts from his profile. "
    "'note' is a LinkedIn connection note under 280 characters: who he is, one real "
    "connection point (same university if they share it), no ask for a job yet. "
    "'message' is the follow-up after they accept, under 100 words: a specific, polite "
    "request for a referral to the named role (or advice on applying if no role is "
    "named), offering to send his CV. No flattery, no clichés, no placeholders."
)


def all_referrals() -> dict:
    return store.load(_FILE, {})


def _save(refs: dict) -> None:
    store.save(_FILE, refs)


def search_people(company: str, university: str = "", limit: int = 10) -> list[dict]:
    """Public LinkedIn profiles of people at `company` in Cairo, via web search."""
    target = companies.match(company)
    firm = target["name"] if target else company
    alias = (target["aliases"][0] if target else company)
    query = f'site:linkedin.com/in "{alias}" Cairo' + (f' "{university}"' if university else "")
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=limit * 2))
    except Exception:
        return []
    people = []
    for r in results:
        m = _PROFILE_URL.search(r.get("href", ""))
        title = r.get("title", "")
        if not m or (target and not companies.mentions(target, f"{title} {r.get('body', '')}")):
            continue
        parts = [p.strip() for p in re.split(r"\s+[-–|]\s+", title) if p.strip()]
        if not parts or parts[0].lower() == "linkedin":
            continue
        people.append({
            "name": parts[0],
            "headline": " - ".join(p for p in parts[1:] if p.lower() != "linkedin"),
            "url": "https://www." + m.group(0),
            "company": firm,
            "alumni": bool(university) and university.lower() in
                      f"{title} {r.get('body', '')}".lower(),
        })
    return people[:limit]


def draft(person: dict, role: str = "") -> "dict | None":
    from core.career import claude
    out = claude.ask(
        f"His profile:\n{profile.as_text()}\n\n"
        f"Person: {person['name']}, {person['headline'] or 'works'} at {person['company']}"
        f"{' (went to the same university)' if person.get('alumni') else ''}.\n"
        f"Role he wants to be referred for: {role or '(none named -- ask for advice)'}",
        system=_SYSTEM, schema=_SCHEMA, effort="low", max_tokens=3000)
    if out:
        out["note"] = out["note"][:_NOTE_LIMIT]
    return out


def find(company: "str | None" = None, count: int = 5) -> str:
    """Find and draft up to `count` new people to ask. Without a company, the
    targets with jobs in play come first: Big 4, then top companies."""
    uni = profile.load().get("answers", {}).get("university", "")
    targets = [company] if company else _companies_in_play()
    refs = all_referrals()
    known = {r["url"] for r in refs.values()}
    added = []
    for firm in targets:
        if len(added) >= count:
            break
        found = search_people(firm, uni) or (search_people(firm) if uni else [])
        for person in found:
            if len(added) >= count or person["url"] in known:
                continue
            role = _role_at(person["company"])
            text = draft(person, role)
            if not text:
                continue
            rid = hashlib.sha1(person["url"].encode()).hexdigest()[:8]
            refs[rid] = {**person, **text, "id": rid, "role": role, "status": "to_send",
                         "found_at": datetime.now().isoformat(timespec="seconds")}
            known.add(person["url"])
            added.append(refs[rid])
    _save(refs)
    if not added:
        return "No new people found to ask for a referral."
    return (f"{len(added)} people to ask for a referral: "
            + "; ".join(f"{r['name']} ({r['company']})" for r in added)
            + ". The notes are on the review page, ready to copy.")


def _companies_in_play() -> list[str]:
    """Target companies with an application ready, sent or waiting, Big 4 first,
    then the rest of the Big 4 and top list."""
    in_play = {a.get("company_key") for a in tracker.all_apps().values()
               if a.get("tier") and a.get("status") in
               ("ready", "approved", "applied", "needs_you", "practice")}
    ranked = sorted(companies.all_companies(),
                    key=lambda c: (c["name"] not in in_play, companies.TIER_RANK[c["tier"]]))
    return [c["name"] for c in ranked]


def _role_at(firm: str) -> str:
    for a in tracker.all_apps().values():
        if a.get("company_key") == firm and a.get("status") in ("ready", "approved", "applied", "needs_you"):
            return a["title"]
    return ""


def to_send() -> list[dict]:
    return sorted((r for r in all_referrals().values() if r["status"] == "to_send"),
                  key=lambda r: (not r.get("alumni"), r["found_at"]))


def mark(ref_id: str, status: str) -> str:
    if status not in ("sent", "replied", "referred", "skipped"):
        return "Error: status must be sent, replied, referred or skipped."
    refs = all_referrals()
    if ref_id not in refs:
        return f"Error: no referral '{ref_id}'."
    refs[ref_id]["status"] = status
    refs[ref_id][f"{status}_at"] = datetime.now().isoformat(timespec="seconds")
    _save(refs)
    return f"{refs[ref_id]['name']} ({refs[ref_id]['company']}): {status}."


def list_text() -> str:
    pending = to_send()
    refs = all_referrals().values()
    sent = sum(1 for r in refs if r["status"] == "sent")
    referred = [r for r in refs if r["status"] == "referred"]
    lines = [f"{len(pending)} referral notes to send, {sent} sent and waiting, "
             f"{len(referred)} referred."]
    for r in pending[:8]:
        lines.append(f"- {r['id']}: {r['name']}, {r['headline'] or r['company']}"
                     f"{' (alumni)' if r.get('alumni') else ''} -- {r['url']}")
    return "\n".join(lines)
