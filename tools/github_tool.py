"""
GitHub integration — Phase 6E.

Uses GitHub REST API via httpx. Personal Access Token optional (needed for private repos).
Setup:
  GITHUB_TOKEN=ghp_...          (github.com/settings/tokens → classic → repo, read:user)
  GITHUB_USERNAME=YourUsername
"""

import os
from datetime import datetime, timezone

import httpx
from dotenv import load_dotenv
load_dotenv()

_TOKEN    = os.getenv("GITHUB_TOKEN", "").strip()
_USERNAME = os.getenv("GITHUB_USERNAME", "").strip()
_BASE     = "https://api.github.com"
_HEADERS  = {
    "Accept": "application/vnd.github.v3+json",
    "User-Agent": "ElFager/1.0",
}
_TOKEN_SET = bool(_TOKEN and not _TOKEN.startswith("xxx") and _TOKEN != "ghp_xxx")
_USER_SET  = bool(_USERNAME and _USERNAME not in ("", "YourGitHubUsername"))
if _TOKEN_SET:
    _HEADERS["Authorization"] = f"token {_TOKEN}"

_NOT_SET_UP = (
    "[GitHub not set up — add GITHUB_TOKEN and GITHUB_USERNAME to .env. "
    "Get a token at github.com/settings/tokens (classic, repo + read:user scopes).]"
)


def _gh(path: str, params: dict = None) -> dict | list:
    resp = httpx.get(f"{_BASE}{path}", headers=_HEADERS, params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()


def _resolve_repo(repo: str) -> str:
    """Turn 'repo-name' into 'owner/repo-name' using GITHUB_USERNAME."""
    if "/" in repo:
        return repo.strip()
    if _USERNAME:
        return f"{_USERNAME}/{repo.strip()}"
    return repo.strip()


def _time_ago(iso_str: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        diff = int((datetime.now(tz=timezone.utc) - dt).total_seconds())
        if diff < 3600:
            return f"{diff // 60}m ago"
        if diff < 86400:
            return f"{diff // 3600}h ago"
        return f"{diff // 86400}d ago"
    except Exception:
        return iso_str[:10] if iso_str else ""


def list_repos(username: str = None, n: int = 10) -> str:
    """List GitHub repositories sorted by last update."""
    user = username or (_USERNAME if _USER_SET else None)
    if not user:
        return _NOT_SET_UP
    try:
        repos = _gh(f"/users/{user}/repos", params={"sort": "updated", "per_page": n})
        if not repos:
            return f"No public repositories found for {user}."
        lines = [f"GitHub repos for {user}:\n"]
        for i, r in enumerate(repos[:n], 1):
            stars = r.get("stargazers_count", 0)
            desc = r.get("description") or ""
            pushed = _time_ago(r.get("pushed_at", ""))
            star_str = f" *{stars}" if stars else ""
            desc_str = f" — {desc[:60]}" if desc else ""
            lines.append(f"{i}. {r['name']}{star_str}{desc_str}")
            if pushed:
                lines.append(f"   Last push: {pushed}")
        return "\n".join(lines)
    except Exception as e:
        return f"[GitHub error: {e}]"


def list_issues(repo: str, n: int = 10) -> str:
    """List open issues for a repository."""
    full_repo = _resolve_repo(repo)
    try:
        issues = _gh(f"/repos/{full_repo}/issues", params={"state": "open", "per_page": n})
        # Filter out pull requests (they appear in issues endpoint too)
        issues = [i for i in issues if "pull_request" not in i]
        if not issues:
            return f"No open issues in {full_repo}."
        lines = [f"Open issues in {full_repo}:\n"]
        for issue in issues[:n]:
            num = issue.get("number")
            title = issue.get("title", "")
            labels = ", ".join(l["name"] for l in issue.get("labels", []))
            ago = _time_ago(issue.get("created_at", ""))
            label_str = f" [{labels}]" if labels else ""
            lines.append(f"#{num} {title}{label_str} — {ago}")
        return "\n".join(lines)
    except Exception as e:
        return f"[GitHub error: {e}]"


def list_prs(repo: str, n: int = 10) -> str:
    """List open pull requests for a repository."""
    full_repo = _resolve_repo(repo)
    try:
        prs = _gh(f"/repos/{full_repo}/pulls", params={"state": "open", "per_page": n})
        if not prs:
            return f"No open pull requests in {full_repo}."
        lines = [f"Open PRs in {full_repo}:\n"]
        for pr in prs[:n]:
            num = pr.get("number")
            title = pr.get("title", "")
            user = pr.get("user", {}).get("login", "")
            ago = _time_ago(pr.get("created_at", ""))
            lines.append(f"#{num} {title} — by {user}, {ago}")
        return "\n".join(lines)
    except Exception as e:
        return f"[GitHub error: {e}]"


def get_repo_info(repo: str) -> str:
    """Get details about a repository."""
    full_repo = _resolve_repo(repo)
    try:
        r = _gh(f"/repos/{full_repo}")
        name = r.get("full_name", full_repo)
        desc = r.get("description") or "(no description)"
        stars = r.get("stargazers_count", 0)
        forks = r.get("forks_count", 0)
        lang = r.get("language") or "unknown"
        issues = r.get("open_issues_count", 0)
        pushed = _time_ago(r.get("pushed_at", ""))
        url = r.get("html_url", "")

        return (
            f"{name}: {desc}\n"
            f"Stars: {stars}  Forks: {forks}  Lang: {lang}\n"
            f"Last push: {pushed}  Open issues: {issues}\n"
            f"{url}"
        )
    except Exception as e:
        return f"[GitHub error: {e}]"
