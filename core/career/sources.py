"""Where the pipeline finds jobs: every search term on every job board, and
the Big 4 by name -- on the boards and on their own career sites."""
import re
from concurrent.futures import ThreadPoolExecutor

from core.agents.job_search_agent import (
    SOURCES, JobSearchAgent, _SENIOR_RE, _dedupe, web_search_jobs,
)
from core.career import companies

_EGYPT_RE = re.compile(r"egypt|cairo|giza|alexandria", re.IGNORECASE)
_TIMEOUT = 15


def gather(settings: dict) -> list[dict]:
    """Every job found, below senior level, one entry per posting, each tagged
    with its target company's tier ("big4", "top" or ""). The Big 4 and Mo's
    other picks are also searched by name and on their own career sites."""
    agent = JobSearchAgent()
    calls = [(agent._from_source, (src, term))
             for term in settings["search_terms"] for src in SOURCES]
    for firm in companies.premium():
        calls += [(_board_by_name, (agent, src, firm)) for src in ("Wuzzuf", "LinkedIn")]
        calls += [(_site, (site, firm)) for site in firm.get("sites", [])]
        calls += [(_workday, (wd, firm)) for wd in firm.get("workday", [])]

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda c: _safe(*c), calls))

    jobs = [j for found in results for j in found if not _SENIOR_RE.search(j["title"])]
    jobs = _dedupe(jobs)
    for j in jobs:
        target = companies.match(j["company"])
        j["tier"] = target["tier"] if target else ""
        j["company_key"] = target["name"] if target else j["company"]
    return jobs


def _safe(fn, args) -> list[dict]:
    try:
        return fn(*args) or []
    except Exception:
        return []


def _board_by_name(agent: JobSearchAgent, source: str, firm: dict) -> list[dict]:
    """The firm's name searched on a board; only postings the firm itself
    placed, not every job that mentions it."""
    found = agent._from_source(source, firm["name"]) or []
    return [j for j in found if companies.match(j["company"]) is firm]


def _site(site: dict, firm: dict) -> "list[dict] | None":
    return web_search_jobs(site["query"], re.compile(site["job_path"]),
                           f"{firm['name']} careers", company=firm["name"])


def _workday(wd: dict, firm: dict) -> list[dict]:
    """Workday's public job search, the one behind the firm's careers page."""
    import httpx
    url = f"https://{wd['host']}/wday/cxs/{wd['tenant']}/{wd['site']}/jobs"
    resp = httpx.post(url, timeout=_TIMEOUT, json={
        "appliedFacets": {}, "limit": 20, "offset": 0, "searchText": "Egypt"})
    resp.raise_for_status()
    jobs = []
    for p in resp.json().get("jobPostings", []):
        where = p.get("locationsText", "")
        if not (_EGYPT_RE.search(where) or _EGYPT_RE.search(p.get("title", ""))):
            continue
        jobs.append({
            "title": p.get("title", ""), "company": firm["name"], "location": where,
            "posted": p.get("postedOn", ""),
            "url": f"https://{wd['host']}/en-US/{wd['site']}{p.get('externalPath', '')}",
            "source": f"{firm['name']} careers",
        })
    return jobs
