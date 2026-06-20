"""
Local git operations for El Fager.

Run git commands on any local repository using the system git CLI (v2.53 installed).
Paths default to the current working directory.
"""

import subprocess
import os


def _run_git(args: list, cwd: str):
    """Run a git command, return (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
            encoding="utf-8",
            errors="replace",
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "git command timed out after 30s"
    except FileNotFoundError:
        return -1, "", "git not found — ensure git is installed and in PATH"
    except Exception as e:
        return -1, "", str(e)


def _resolve(path: str) -> str:
    return os.path.abspath(os.path.expanduser(path))


def git_status(repo_path: str = ".") -> str:
    """Show working tree status — modified, staged, and untracked files."""
    try:
        cwd = _resolve(repo_path)
        rc, out, err = _run_git(["status", "--short", "--branch"], cwd)
        if rc != 0:
            return f"[git_status failed: {err or 'not a git repository'}]"
        return out or "Nothing to commit — working tree clean."
    except Exception as e:
        return f"[git_status failed: {e}]"


def git_log(repo_path: str = ".", n: int = 10) -> str:
    """Show the last N commits with hash, author, relative date, and message."""
    try:
        cwd = _resolve(repo_path)
        fmt = "%h  %an  %ar  %s"
        rc, out, err = _run_git(["log", f"-{n}", f"--pretty=format:{fmt}"], cwd)
        if rc != 0:
            combined = (err or out or "").lower()
            if "does not have any commits" in combined or "bad default revision" in combined:
                return "No commits yet."
            return f"[git_log failed: {err or 'not a git repository'}]"
        if not out:
            return "No commits yet."
        return f"Last {n} commits ({cwd}):\n" + out
    except Exception as e:
        return f"[git_log failed: {e}]"


def git_diff(repo_path: str = ".", staged: bool = False) -> str:
    """Show file changes — unstaged by default, staged (--cached) if staged=True."""
    try:
        cwd = _resolve(repo_path)
        stat_args = ["diff", "--stat", "--no-color"]
        full_args = ["diff", "--no-color"]
        if staged:
            stat_args.insert(1, "--staged")
            full_args.insert(1, "--staged")
        rc, stat_out, err = _run_git(stat_args, cwd)
        if rc != 0:
            return f"[git_diff failed: {err}]"
        if not stat_out:
            label = "staged" if staged else "unstaged"
            return f"No {label} changes."
        rc2, full, _ = _run_git(full_args, cwd)
        if full and len(full) > 3000:
            full = full[:3000] + "\n...[truncated]"
        return f"Diff ({cwd}):\n{stat_out}\n\n{full}" if full else f"Diff:\n{stat_out}"
    except Exception as e:
        return f"[git_diff failed: {e}]"


def git_add(paths: list, repo_path: str = ".") -> str:
    """Stage files for commit. Use ['.'] to stage all changes."""
    try:
        cwd = _resolve(repo_path)
        rc, out, err = _run_git(["add"] + paths, cwd)
        if rc != 0:
            return f"[git_add failed: {err}]"
        rc2, status, _ = _run_git(["status", "--short"], cwd)
        staged = [l for l in (status or "").splitlines() if l and not l.startswith("?")]
        return f"Staged: {', '.join(paths)}. {len(staged)} change(s) ready to commit."
    except Exception as e:
        return f"[git_add failed: {e}]"


def git_commit(message: str, repo_path: str = ".") -> str:
    """Commit staged changes with a message."""
    try:
        cwd = _resolve(repo_path)
        rc, out, err = _run_git(["commit", "-m", message], cwd)
        if rc != 0:
            combined = err or out
            if "nothing to commit" in combined.lower():
                return "Nothing to commit - stage files first with git_add."
            return f"[git_commit failed: {combined}]"
        return f"Committed: {out}" if out else f"Committed: {message}"
    except Exception as e:
        return f"[git_commit failed: {e}]"


def git_push(repo_path: str = ".", remote: str = "origin", branch: str = "") -> str:
    """Push commits to a remote repository."""
    try:
        cwd = _resolve(repo_path)
        args = ["push", remote]
        if branch:
            args.append(branch)
        rc, out, err = _run_git(args, cwd)
        combined = (out + "\n" + err).strip()
        if rc != 0:
            return f"[git_push failed: {combined}]"
        return combined or f"Pushed to {remote}."
    except Exception as e:
        return f"[git_push failed: {e}]"


def git_pull(repo_path: str = ".", remote: str = "origin") -> str:
    """Pull latest changes from a remote repository."""
    try:
        cwd = _resolve(repo_path)
        rc, out, err = _run_git(["pull", remote], cwd)
        combined = (out + "\n" + err).strip()
        if rc != 0:
            return f"[git_pull failed: {combined}]"
        return combined or f"Pulled from {remote}."
    except Exception as e:
        return f"[git_pull failed: {e}]"
