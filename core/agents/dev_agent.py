"""
Forge -- El Fager's engineer.

Reads repositories, inspects diffs and history, checks GitHub, and handles the
small developer utilities. Wraps tools/git_tool.py, github_tool.py,
code_tool.py and dev_utils_tool.py.

Safety: running arbitrary code, committing, and pushing are in confirm_before.
An unattended Forge -- one working from a mission or a command typed on the
phone -- can read, diff, and lint, but cannot execute code or write history.
That is deliberate: a mission prompt is not a trusted place to source code
that then runs on Mo's laptop.
"""
from core.agents.base_agent import BaseAgent
from core.agents.tool_loop import run_tool_loop, tool

DESTRUCTIVE_TOOLS = (
    "run_python",
    "git_add",
    "git_commit",
    "git_push",
)

_SYSTEM = """\
You are Forge, El Fager's engineering agent, working for Mo.

Look before you touch: read status, log, or diff before proposing a change.
Repo paths default to the current directory when Mo does not name one.

Quote real output -- a failing line, an actual commit hash -- rather than
summarising it away.

If a tool you need is unavailable, you are working unattended: report the exact
command or change you would have made and leave it for Mo. Never claim you
committed, pushed, or ran something you did not.

Report in two or three sentences. Plain English, no markdown, no emoji."""


class DevAgent(BaseAgent):
    def __init__(self, allow_side_effects: bool = True):
        self._allow_side_effects = allow_side_effects

    @property
    def name(self) -> str:
        return "dev"

    @property
    def description(self) -> str:
        return "Git, GitHub, code inspection, and developer utilities."

    def run(self, task: str) -> str:
        tools, dispatch = self._toolset()
        return run_tool_loop("dev_agent", _SYSTEM, tools, dispatch, task)

    def _toolset(self) -> tuple[list[dict], dict]:
        from tools import code_tool as co
        from tools import dev_utils_tool as du
        from tools import git_tool as gi
        from tools import github_tool as gh

        schemas = [
            tool("git_status", "Working tree status of a repo.",
                 {"repo_path": ("string", "Repo path, default '.'.")}),
            tool("git_log", "Recent commits.",
                 {"repo_path": ("string", "Repo path, default '.'."),
                  "n": ("integer", "How many commits, default 10.")}),
            tool("git_diff", "Diff of the working tree or the staged changes.",
                 {"repo_path": ("string", "Repo path, default '.'."),
                  "staged": ("boolean", "Diff staged changes instead of unstaged.")}),
            tool("git_pull", "Pull from a remote.",
                 {"repo_path": ("string", "Repo path, default '.'."),
                  "remote": ("string", "Remote name, default origin.")}),
            tool("git_add", "Stage files for commit.",
                 {"paths": ("array", "File paths to stage."),
                  "repo_path": ("string", "Repo path, default '.'.")}, ["paths"]),
            tool("git_commit", "Commit the staged changes.",
                 {"message": ("string", "Commit message."),
                  "repo_path": ("string", "Repo path, default '.'.")}, ["message"]),
            tool("git_push", "Push to a remote.",
                 {"repo_path": ("string", "Repo path, default '.'."),
                  "remote": ("string", "Remote name, default origin."),
                  "branch": ("string", "Branch name, defaults to the current one.")}),
            tool("list_repos", "List GitHub repos.",
                 {"username": ("string", "GitHub user, defaults to Mo."),
                  "n": ("integer", "How many, default 10.")}),
            tool("list_issues", "List open issues on a GitHub repo.",
                 {"repo": ("string", "owner/repo or just the repo name."),
                  "n": ("integer", "How many, default 10.")}, ["repo"]),
            tool("list_prs", "List open pull requests on a GitHub repo.",
                 {"repo": ("string", "owner/repo or just the repo name."),
                  "n": ("integer", "How many, default 10.")}, ["repo"]),
            tool("get_repo_info", "Summary of a GitHub repo.",
                 {"repo": ("string", "owner/repo or just the repo name.")}, ["repo"]),
            tool("check_syntax", "Check Python code for syntax errors without running it.",
                 {"code": ("string", "Python source.")}, ["code"]),
            tool("format_python", "Format Python source.",
                 {"code": ("string", "Python source.")}, ["code"]),
            tool("run_python", "Execute Python code and return its output.",
                 {"code": ("string", "Python source."),
                  "timeout": ("integer", "Seconds before giving up, default 30.")}, ["code"]),
            tool("hash_text", "Hash a string.",
                 {"text": ("string", "Text to hash."),
                  "algorithm": ("string", "sha256, md5, sha1, sha512.")}, ["text"]),
            tool("encode_base64", "Base64-encode a string.",
                 {"text": ("string", "Text to encode.")}, ["text"]),
            tool("decode_base64", "Decode a base64 string.",
                 {"encoded": ("string", "Base64 text.")}, ["encoded"]),
            tool("generate_uuid", "Generate a UUID."),
        ]
        dispatch = {
            "git_status": gi.git_status,
            "git_log": gi.git_log,
            "git_diff": gi.git_diff,
            "git_pull": gi.git_pull,
            "git_add": gi.git_add,
            "git_commit": gi.git_commit,
            "git_push": gi.git_push,
            "list_repos": gh.list_repos,
            "list_issues": gh.list_issues,
            "list_prs": gh.list_prs,
            "get_repo_info": gh.get_repo_info,
            "check_syntax": co.check_syntax,
            "format_python": co.format_python,
            "run_python": co.run_python,
            "hash_text": du.hash_text,
            "encode_base64": du.encode_base64,
            "decode_base64": du.decode_base64,
            "generate_uuid": du.generate_uuid,
        }
        if not self._allow_side_effects:
            for name in DESTRUCTIVE_TOOLS:
                dispatch.pop(name, None)
            schemas = [s for s in schemas if s["name"] not in DESTRUCTIVE_TOOLS]
        return schemas, dispatch
