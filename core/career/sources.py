"""Where the pipeline finds jobs: every search term on every job board, the
Big 4 and Mo's other picks by name on the boards, and every target company's
own career site that can be read."""
import re
from concurrent.futures import ThreadPoolExecutor

from core.agents.job_search_agent import (
    SOURCES, JobSearchAgent, _SENIOR_RE, _dedupe, web_search_jobs,
)
from core.career import companies

_EGYPT_RE = re.compile(r"egypt|cairo|giza|alexandria", re.IGNORECASE)
_TIMEOUT = 15
# Workday answers 20 postings at a time; five pages is past any firm's Egypt list.
_WORKDAY_PAGE = 20
_WORKDAY_MAX = 100


def gather(settings: dict) -> list[dict]:
    """Every job found, below senior level, one entry per posting, each tagged
    with its target company's tier ("big4", "top" or ""). The Big 4 and Mo's
    other picks are also searched by name and on their own career sites."""
    agent = JobSearchAgent()
    calls = [(agent._from_source, (src, term))
             for term in settings["search_terms"] for src in SOURCES]
    for firm in companies.premium():
        calls += [(_board_by_name, (agent, src, firm)) for src in ("Wuzzuf", "LinkedIn")]
    for firm in companies.with_career_sites():
        calls += [(_site, (site, firm)) for site in firm.get("sites", [])]
        calls += [(_workday, (wd, firm)) for wd in firm.get("workday", [])]
        calls += [(_smartrecruiters, (sr, firm)) for sr in firm.get("smartrecruiters", [])]
        calls += [(_amazon, (aj, firm)) for aj in firm.get("amazon_jobs", [])]

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


def _get_json(url: str, params: dict) -> dict:
    import httpx
    from tools.web_tool import _BROWSER_UA
    resp = httpx.get(url, params=params, timeout=_TIMEOUT, headers={"User-Agent": _BROWSER_UA})
    resp.raise_for_status()
    return resp.json()


def _post_json(url: str, body: dict) -> dict:
    import httpx
    resp = httpx.post(url, timeout=_TIMEOUT, json=body)
    resp.raise_for_status()
    return resp.json()


def _workday(wd: dict, firm: dict) -> list[dict]:
    """Workday's public job search, the one behind the firm's careers page.
    It gives the total only on the first page."""
    url = f"https://{wd['host']}/wday/cxs/{wd['tenant']}/{wd['site']}/jobs"
    postings, total = [], None
    while len(postings) < _WORKDAY_MAX:
        page = _post_json(url, {"appliedFacets": {}, "limit": _WORKDAY_PAGE,
                                "offset": len(postings), "searchText": "Egypt"})
        found = page.get("jobPostings", [])
        postings += found
        total = page.get("total", 0) if total is None else total
        if not found or len(postings) >= total:
            break
    jobs = []
    for p in postings:
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


def _smartrecruiters(sr: dict, firm: dict) -> list[dict]:
    """SmartRecruiters' public postings for the firm, in Egypt only."""
    page = _get_json(f"https://api.smartrecruiters.com/v1/companies/{sr['company']}/postings",
                     {"country": "eg", "limit": 100})
    return [{"title": p["name"], "company": firm["name"],
             "location": p.get("location", {}).get("city", ""),
             "posted": p.get("releasedDate", "")[:10],
             "url": f"https://jobs.smartrecruiters.com/{sr['company']}/{p['id']}",
             "source": f"{firm['name']} careers"}
            for p in page.get("content", [])]


def _amazon(aj: dict, firm: dict) -> list[dict]:
    """amazon.jobs' own search, for one country."""
    page = _get_json("https://www.amazon.jobs/en/search.json",
                     {"normalized_country_code[]": aj["country"], "result_limit": 100})
    return [{"title": j["title"], "company": firm["name"], "location": j.get("city", ""),
             "posted": j.get("posted_date", ""), "url": "https://www.amazon.jobs" + j["job_path"],
             "source": f"{firm['name']} careers"}
            for j in page.get("jobs", [])]
