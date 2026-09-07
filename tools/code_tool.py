"""
Code execution tool — run Python, PowerShell, Bash, or Node.js code in isolated subprocesses.

Features
--------
  run_python          — run Python code (Unicode-safe, auto temp-file for long code)
  run_powershell      — run PowerShell commands
  run_bash            — run Bash/shell via Git Bash
  run_node            — run JavaScript/Node.js
  execute_file        — run .py / .ps1 / .sh / .js file
  run_with_args       — like execute_file but with CLI arguments
  run_with_stdin      — run Python code and feed it stdin (fixes input() hangs)
  check_syntax        — instant AST syntax check, no subprocess
  benchmark           — time code execution over multiple runs
  format_python       — format code with black or autopep8
  pip_install         — install package (safe-name check)
  pip_uninstall       — uninstall package
  pip_show            — show package info
  list_packages       — list installed packages
  get_python_info     — Python version + key packages
  create_script       — save named script to data/scripts/
  get_script          — retrieve saved script code
  list_scripts        — list all saved scripts
  run_script          — run a saved script by name
  delete_script       — delete a saved script
  run_in_background   — fire-and-forget subprocess, logs to data/scripts/bg/
  list_background     — list running background jobs
  kill_background     — kill a background job by label
  open_in_editor      — open file in VS Code or system default
"""

import ast
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

_MAX_OUTPUT   = 3000
_PYTHON       = sys.executable
_UTF8_ENV     = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}

# Package name safety (PEP 508 / PyPI)
_SAFE_PKG_RE  = re.compile(r"^[A-Za-z0-9_\-\.]+(\[.*?\])?$")

# Script storage
_SCRIPTS_DIR  = Path("data/scripts")
_BG_DIR       = Path("data/scripts/bg")
_BG_FILE      = Path("data/scripts/bg/jobs.json")
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_\-]+$")
_LANG_EXT     = {"python": ".py", "powershell": ".ps1", "bash": ".sh", "javascript": ".js"}
_EXT_LANG     = {v: k for k, v in _LANG_EXT.items()}


# ──────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────────────

def _cap(text: str) -> str:
    if len(text) > _MAX_OUTPUT:
        omitted = len(text) - _MAX_OUTPUT
        return text[:_MAX_OUTPUT] + f"\n[...truncated — {omitted} more chars]"
    return text


def _format_result(stdout: str, stderr: str, returncode: int) -> str:
    parts = []
    if stdout:
        parts.append(f"Output:\n{stdout}")
    if stderr:
        label = f"Error (exit {returncode}):" if returncode != 0 else "Stderr:"
        parts.append(f"{label}\n{stderr}")
    if not parts:
        if returncode == 0:
            parts.append("(no output)")
        else:
            parts.append(f"(no output — exit {returncode})")
    return _cap("\n".join(parts))


def _write_temp(code: str, suffix: str = ".py") -> str:
    """Write code to a NamedTemporaryFile and return the path."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=suffix, encoding="utf-8", delete=False
    ) as f:
        f.write(code)
        return f.name


def _run_python_code(
    code: str,
    timeout: int,
    cwd: str | None = None,
    stdin_input: str | None = None,
) -> str:
    """
    Core Python runner. Always uses a temp file (avoids Windows CLI arg limits
    and handles multi-line code naturally). Optionally feeds stdin.
    """
    tmp = _write_temp(code, ".py")
    try:
        result = subprocess.run(
            [_PYTHON, tmp],
            input=stdin_input,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_UTF8_ENV,
            cwd=cwd,
            encoding="utf-8",
            errors="replace",
        )
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    return _format_result(result.stdout.strip(), result.stderr.strip(), result.returncode)


def _find_bash() -> str | None:
    for candidate in [
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files (x86)\Git\bin\bash.exe",
        "bash",
    ]:
        try:
            subprocess.run([candidate, "--version"], capture_output=True, timeout=5)
            return candidate
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
    return None


def _find_node() -> str | None:
    for candidate in ["node", "node.exe"]:
        try:
            r = subprocess.run(
                [candidate, "--version"], capture_output=True, timeout=5,
                encoding="utf-8", errors="replace",
            )
            if r.returncode == 0:
                return candidate
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
    return None


def _load_bg_jobs() -> dict:
    if _BG_FILE.exists():
        try:
            return json.loads(_BG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_bg_jobs(jobs: dict) -> None:
    _BG_DIR.mkdir(parents=True, exist_ok=True)
    _BG_FILE.write_text(json.dumps(jobs, indent=2, ensure_ascii=False), encoding="utf-8")


def _pid_alive(pid: int) -> bool:
    """Return True if a process with the given PID is still running."""
    try:
        import psutil
        return psutil.pid_exists(pid)
    except ImportError:
        # Fall back to tasklist
        r = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        return str(pid) in r.stdout
    except Exception:
        return False


# ──────────────────────────────────────────────────────────────────────────────
# Core execution
# ──────────────────────────────────────────────────────────────────────────────

def run_python(code: str, timeout: int = 30) -> str:
    """Run arbitrary Python code in an isolated subprocess. Unicode safe."""
    if not code.strip():
        return "No code provided."
    try:
        return _run_python_code(code, timeout)
    except subprocess.TimeoutExpired:
        return f"Timed out after {timeout}s."
    except Exception as e:
        return f"Error launching Python: {e}"


def run_powershell(command: str, timeout: int = 30) -> str:
    """Run a PowerShell command or script block."""
    if not command.strip():
        return "No command provided."
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-Command", command],
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
        )
        return _format_result(result.stdout.strip(), result.stderr.strip(), result.returncode)
    except FileNotFoundError:
        return "PowerShell not found. Is it installed and on PATH?"
    except subprocess.TimeoutExpired:
        return f"Timed out after {timeout}s."
    except Exception as e:
        return f"Error launching PowerShell: {e}"


def run_bash(command: str, timeout: int = 30) -> str:
    """Run a Bash command via Git Bash (Windows) or /bin/bash."""
    if not command.strip():
        return "No command provided."
    bash = _find_bash()
    if not bash:
        return (
            "Bash not found. Install Git for Windows and ensure Git Bash is on PATH. "
            "Alternatively use run_powershell."
        )
    try:
        result = subprocess.run(
            [bash, "-c", command],
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
        )
        return _format_result(result.stdout.strip(), result.stderr.strip(), result.returncode)
    except subprocess.TimeoutExpired:
        return f"Timed out after {timeout}s."
    except Exception as e:
        return f"Error launching Bash: {e}"


def run_node(code: str, timeout: int = 30) -> str:
    """Run JavaScript code with Node.js. Returns stdout and stderr."""
    if not code.strip():
        return "No code provided."
    node = _find_node()
    if not node:
        return (
            "Node.js not found. Download it from https://nodejs.org, "
            "install, and restart El Fager."
        )
    tmp = _write_temp(code, ".js")
    try:
        result = subprocess.run(
            [node, tmp],
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
        )
        return _format_result(result.stdout.strip(), result.stderr.strip(), result.returncode)
    except subprocess.TimeoutExpired:
        return f"Timed out after {timeout}s."
    except Exception as e:
        return f"Error launching Node.js: {e}"
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def run_with_stdin(code: str, stdin_input: str, timeout: int = 30) -> str:
    """
    Run Python code and feed it stdin text. Use this whenever the code calls input().
    stdin_input lines are separated by newlines, e.g. "Alice\\n25".
    """
    if not code.strip():
        return "No code provided."
    try:
        return _run_python_code(code, timeout, stdin_input=stdin_input)
    except subprocess.TimeoutExpired:
        return f"Timed out after {timeout}s. (If code uses input() make sure stdin_input covers all prompts.)"
    except Exception as e:
        return f"Error: {e}"


def execute_file(path: str, timeout: int = 60) -> str:
    """Run a .py, .ps1, .sh, or .js script file."""
    p = Path(path).expanduser()
    if not p.exists():
        return f"File not found: {path}"
    ext = p.suffix.lower()

    if ext == ".py":
        try:
            result = subprocess.run(
                [_PYTHON, str(p.resolve())],
                capture_output=True, text=True, timeout=timeout,
                env=_UTF8_ENV, cwd=str(p.parent), encoding="utf-8", errors="replace",
            )
            return _format_result(result.stdout.strip(), result.stderr.strip(), result.returncode)
        except subprocess.TimeoutExpired:
            return f"Timed out after {timeout}s."
        except Exception as e:
            return f"Error running file: {e}"

    elif ext == ".ps1":
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive",
                 "-ExecutionPolicy", "Bypass", "-File", str(p.resolve())],
                capture_output=True, text=True, timeout=timeout,
                cwd=str(p.parent), encoding="utf-8", errors="replace",
            )
            return _format_result(result.stdout.strip(), result.stderr.strip(), result.returncode)
        except subprocess.TimeoutExpired:
            return f"Timed out after {timeout}s."
        except Exception as e:
            return f"Error running PowerShell file: {e}"

    elif ext == ".sh":
        bash = _find_bash()
        if not bash:
            return "Bash not found — can't run .sh file. Install Git for Windows."
        try:
            result = subprocess.run(
                [bash, str(p.resolve())],
                capture_output=True, text=True, timeout=timeout,
                cwd=str(p.parent), encoding="utf-8", errors="replace",
            )
            return _format_result(result.stdout.strip(), result.stderr.strip(), result.returncode)
        except subprocess.TimeoutExpired:
            return f"Timed out after {timeout}s."
        except Exception as e:
            return f"Error running .sh file: {e}"

    elif ext == ".js":
        node = _find_node()
        if not node:
            return "Node.js not found — can't run .js file."
        try:
            result = subprocess.run(
                [node, str(p.resolve())],
                capture_output=True, text=True, timeout=timeout,
                cwd=str(p.parent), encoding="utf-8", errors="replace",
            )
            return _format_result(result.stdout.strip(), result.stderr.strip(), result.returncode)
        except subprocess.TimeoutExpired:
            return f"Timed out after {timeout}s."
        except Exception as e:
            return f"Error running .js file: {e}"

    else:
        return f"Unsupported file type '{ext}'. Supported: .py, .ps1, .sh, .js"


def run_with_args(path: str, args: str = "", timeout: int = 60) -> str:
    """
    Run a .py or .ps1 script with command-line arguments.
    args is a space-separated string, e.g. "Alice 25 --verbose".
    """
    import shlex
    p = Path(path).expanduser()
    if not p.exists():
        return f"File not found: {path}"
    ext = p.suffix.lower()
    args_list = shlex.split(args) if args.strip() else []

    if ext == ".py":
        cmd = [_PYTHON, str(p.resolve())] + args_list
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout,
                env=_UTF8_ENV, cwd=str(p.parent), encoding="utf-8", errors="replace",
            )
            return _format_result(result.stdout.strip(), result.stderr.strip(), result.returncode)
        except subprocess.TimeoutExpired:
            return f"Timed out after {timeout}s."
        except Exception as e:
            return f"Error: {e}"

    elif ext == ".ps1":
        # PowerShell -File passes positional args automatically
        cmd = ["powershell", "-NoProfile", "-NonInteractive",
               "-ExecutionPolicy", "Bypass", "-File", str(p.resolve())] + args_list
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout,
                cwd=str(p.parent), encoding="utf-8", errors="replace",
            )
            return _format_result(result.stdout.strip(), result.stderr.strip(), result.returncode)
        except subprocess.TimeoutExpired:
            return f"Timed out after {timeout}s."
        except Exception as e:
            return f"Error: {e}"

    else:
        return f"run_with_args supports .py and .ps1 files (got '{ext}')."


# ──────────────────────────────────────────────────────────────────────────────
# Analysis
# ──────────────────────────────────────────────────────────────────────────────

def check_syntax(code: str) -> str:
    """
    Instantly check Python syntax using the AST parser — no subprocess needed.
    Returns 'Syntax OK' or the specific error with line number.
    """
    if not code.strip():
        return "No code provided."
    try:
        ast.parse(code)
        lines = code.splitlines()
        return f"Syntax OK ({len(lines)} line{'s' if len(lines) != 1 else ''})"
    except SyntaxError as e:
        snippet = (e.text or "").rstrip()
        marker  = " " * (e.offset - 1) + "^" if e.offset else ""
        return f"SyntaxError at line {e.lineno}: {e.msg}\n  {snippet}\n  {marker}"
    except Exception as e:
        return f"Parse error: {e}"


def benchmark(code: str, runs: int = 5, timeout: int = 60) -> str:
    """
    Run Python code N times and report Min/Avg/Max timing.
    Also shows the last-run output (if any).
    """
    if not code.strip():
        return "No code provided."
    if runs < 1 or runs > 100:
        return "runs must be between 1 and 100."

    wrapper = f"""
import time, statistics, io, contextlib

_code = compile({code!r}, '<benchmarked>', 'exec')
_times = []
_last_out = ""
for _i in range({runs}):
    _buf = io.StringIO()
    with contextlib.redirect_stdout(_buf):
        _t0 = time.perf_counter()
        exec(_code, {{}})
        _t1 = time.perf_counter()
    _times.append(_t1 - _t0)
    _last_out = _buf.getvalue()

_ms = [_t * 1000 for _t in _times]
if _last_out:
    print("Output (last run):")
    print(_last_out.rstrip())
    print()
print(f"Benchmark ({runs} run(s)):")
print(f"  Min:   {{min(_ms):.4f}} ms")
print(f"  Avg:   {{statistics.mean(_ms):.4f}} ms")
print(f"  Max:   {{max(_ms):.4f}} ms")
print(f"  Total: {{sum(_ms):.4f}} ms")
"""
    try:
        return _run_python_code(wrapper, timeout)
    except subprocess.TimeoutExpired:
        return f"Benchmark timed out after {timeout}s."
    except Exception as e:
        return f"Benchmark error: {e}"


def format_python(code: str) -> str:
    """
    Format Python code using black (preferred) or autopep8.
    Returns the formatted code. If neither is installed, suggests installing black.
    """
    if not code.strip():
        return "No code provided."

    tmp = _write_temp(code, ".py")
    try:
        # Try black first
        r = subprocess.run(
            [_PYTHON, "-m", "black", "--quiet", "--line-length", "88", tmp],
            capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace",
        )
        if r.returncode == 0:
            formatted = Path(tmp).read_text(encoding="utf-8")
            return f"Formatted with black:\n{formatted}"
        if "No module named black" not in r.stderr and "No module named 'black'" not in r.stderr:
            # black found but returned an error (e.g. syntax error)
            return f"black error:\n{r.stderr.strip()}"

        # Try autopep8
        r2 = subprocess.run(
            [_PYTHON, "-m", "autopep8", "--in-place", tmp],
            capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace",
        )
        if r2.returncode == 0 and "No module named" not in r2.stderr:
            formatted = Path(tmp).read_text(encoding="utf-8")
            return f"Formatted with autopep8:\n{formatted}"

        return (
            "black not installed, autopep8 not installed.\n"
            "Install a formatter: pip install black\n\n"
            f"Original code:\n{code}"
        )
    except Exception as e:
        return f"Error formatting: {e}"
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


# ──────────────────────────────────────────────────────────────────────────────
# Package management
# ──────────────────────────────────────────────────────────────────────────────

def pip_install(package: str, upgrade: bool = False) -> str:
    """Install a Python package via pip. Only safe package names are accepted."""
    pkg = package.strip()
    if not pkg:
        return "No package name provided."
    if not _SAFE_PKG_RE.match(pkg):
        return (
            f"Unsafe package name: {pkg!r}. "
            "Only alphanumeric names with hyphens/underscores/dots are allowed."
        )
    cmd = [_PYTHON, "-m", "pip", "install", pkg]
    if upgrade:
        cmd.append("--upgrade")
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120,
            encoding="utf-8", errors="replace",
        )
        lines   = result.stdout.strip().splitlines()
        summary = "\n".join(lines[-6:]) if len(lines) > 6 else result.stdout.strip()
        return _format_result(summary, result.stderr.strip(), result.returncode)
    except subprocess.TimeoutExpired:
        return "pip install timed out after 120s."
    except Exception as e:
        return f"Error running pip: {e}"


def pip_uninstall(package: str) -> str:
    """Uninstall a Python package via pip."""
    pkg = package.strip()
    if not pkg:
        return "No package name provided."
    if not _SAFE_PKG_RE.match(pkg):
        return f"Unsafe package name: {pkg!r}."
    try:
        result = subprocess.run(
            [_PYTHON, "-m", "pip", "uninstall", "-y", pkg],
            capture_output=True, text=True, timeout=60,
            encoding="utf-8", errors="replace",
        )
        out = result.stdout.strip() or result.stderr.strip()
        if result.returncode == 0:
            return f"Uninstalled {pkg}.\n{out}"
        return f"Failed to uninstall {pkg}:\n{out}"
    except subprocess.TimeoutExpired:
        return "pip uninstall timed out."
    except Exception as e:
        return f"Error: {e}"


def pip_show(package: str) -> str:
    """Show detailed info about an installed package (version, location, dependencies)."""
    pkg = package.strip()
    if not pkg:
        return "No package name provided."
    try:
        result = subprocess.run(
            [_PYTHON, "-m", "pip", "show", pkg],
            capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace",
        )
        if result.returncode != 0:
            return f"Package '{pkg}' not found. Is it installed?"
        return result.stdout.strip()
    except Exception as e:
        return f"Error: {e}"


def list_packages(filter_str: str = "") -> str:
    """List installed Python packages, optionally filtered by name."""
    try:
        result = subprocess.run(
            [_PYTHON, "-m", "pip", "list", "--format", "columns"],
            capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace",
        )
        if result.returncode != 0:
            return f"pip list failed:\n{result.stderr.strip()}"
        lines = result.stdout.strip().splitlines()
        if filter_str:
            pattern = filter_str.lower()
            filtered = [l for l in lines[2:] if pattern in l.lower()]
            if not filtered:
                return f"No packages matching '{filter_str}'."
            lines = lines[:2] + filtered
        return _cap("\n".join(lines))
    except subprocess.TimeoutExpired:
        return "Timed out listing packages."
    except Exception as e:
        return f"Error: {e}"


def get_python_info() -> str:
    """Show Python version, executable, and whether key packages are installed."""
    code = """
import sys, platform, importlib
print('Python:', sys.version)
print('Executable:', sys.executable)
print('Platform:', platform.platform())
print()
print('Key packages:')
for pkg in ['anthropic','PyQt6','requests','httpx','numpy','pandas','matplotlib',
            'openai','black','flask','django','fastapi','scipy','sklearn']:
    try:
        m = importlib.import_module(pkg)
        v = getattr(m, '__version__', '?')
        print(f'  {pkg}: {v}')
    except ImportError:
        print(f'  {pkg}: not installed')
"""
    try:
        return _run_python_code(code, timeout=15)
    except subprocess.TimeoutExpired:
        return "Timed out."
    except Exception as e:
        return f"Error: {e}"


# ──────────────────────────────────────────────────────────────────────────────
# Named script storage  (data/scripts/)
# ──────────────────────────────────────────────────────────────────────────────

def create_script(name: str, code: str, language: str = "python") -> str:
    """
    Save code as a named script in data/scripts/. Language choices: python,
    powershell, bash, javascript. Overwrites any existing script with the same name.
    """
    if not _SAFE_NAME_RE.match(name):
        return (
            f"Invalid script name: {name!r}. "
            "Use only letters, numbers, hyphens, or underscores."
        )
    if not code.strip():
        return "No code provided."
    lang = language.lower()
    ext  = _LANG_EXT.get(lang)
    if not ext:
        return f"Unknown language '{language}'. Choose: python, powershell, bash, javascript."

    _SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    path = _SCRIPTS_DIR / f"{name}{ext}"
    path.write_text(code, encoding="utf-8")
    lines = len(code.splitlines())
    return f"Script '{name}' saved ({lines} line{'s' if lines != 1 else ''}, {lang}) -> {path}"


def get_script(name: str) -> str:
    """Show the source code of a saved script."""
    _SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    for ext in _LANG_EXT.values():
        p = _SCRIPTS_DIR / f"{name}{ext}"
        if p.exists():
            lang  = _EXT_LANG.get(ext, "unknown")
            code  = p.read_text(encoding="utf-8")
            lines = len(code.splitlines())
            return f"Script '{name}' ({lang}, {lines} lines):\n{_cap(code)}"
    return f"No script named '{name}'. Use list_scripts to see what's saved."


def list_scripts() -> str:
    """List all saved scripts with name, language, line count, and last-modified time."""
    _SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    scripts = []
    for ext, lang in _EXT_LANG.items():
        for p in sorted(_SCRIPTS_DIR.glob(f"*{ext}")):
            if p.name.startswith("."):
                continue
            stat   = p.stat()
            lines  = len(p.read_text(encoding="utf-8", errors="replace").splitlines())
            mtime  = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
            scripts.append((p.stem, lang, lines, mtime))

    if not scripts:
        return "No saved scripts. Use create_script to save one."
    lines = [f"{len(scripts)} saved script(s) in data/scripts/:"]
    for stem, lang, n_lines, mtime in sorted(scripts):
        lines.append(f"  • {stem} ({lang}, {n_lines} lines) — {mtime}")
    return "\n".join(lines)


def run_script(name: str, args: str = "", timeout: int = 60) -> str:
    """Run a saved script by name. Pass args as a space-separated string."""
    _SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    for ext in _LANG_EXT.values():
        p = _SCRIPTS_DIR / f"{name}{ext}"
        if p.exists():
            if args.strip():
                return run_with_args(str(p), args, timeout)
            return execute_file(str(p), timeout)
    return f"No script named '{name}'. Use list_scripts to see what's saved."


def delete_script(name: str) -> str:
    """Delete a saved script."""
    _SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    for ext in _LANG_EXT.values():
        p = _SCRIPTS_DIR / f"{name}{ext}"
        if p.exists():
            lang = _EXT_LANG.get(ext, "unknown")
            p.unlink()
            return f"Script '{name}' ({lang}) deleted."
    return f"No script named '{name}'."


# ──────────────────────────────────────────────────────────────────────────────
# Background process management
# ──────────────────────────────────────────────────────────────────────────────

def run_in_background(command: str, label: str, language: str = "python") -> str:
    """
    Fire-and-forget: run a command in the background without waiting for it.
    stdout/stderr are logged to data/scripts/bg/{label}.log.
    language: python | powershell | bash | node
    """
    if not command.strip():
        return "No command provided."
    if not _SAFE_NAME_RE.match(label):
        return f"Invalid label: {label!r}. Use letters, numbers, hyphens, underscores."

    _BG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = _BG_DIR / f"{label}.log"

    lang = language.lower()
    if lang == "python":
        cmd = [_PYTHON, "-c", command]
    elif lang == "powershell":
        cmd = ["powershell", "-NoProfile", "-NonInteractive",
               "-ExecutionPolicy", "Bypass", "-Command", command]
    elif lang == "bash":
        bash = _find_bash()
        if not bash:
            return "Bash not found — cannot run background bash job."
        cmd = [bash, "-c", command]
    elif lang in ("node", "javascript"):
        node = _find_node()
        if not node:
            return "Node.js not found — cannot run background node job."
        tmp = _write_temp(command, ".js")
        cmd = [node, tmp]
    else:
        return f"Unknown language '{language}'. Choose: python, powershell, bash, node."

    try:
        log_fh = open(log_file, "w", encoding="utf-8")
        proc = subprocess.Popen(
            cmd,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            env=_UTF8_ENV if lang == "python" else None,
            creationflags=(
                subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
                if sys.platform == "win32" else 0
            ),
        )
        jobs = _load_bg_jobs()
        jobs[label] = {
            "pid":        proc.pid,
            "command":    command[:200],
            "language":   lang,
            "log":        str(log_file),
            "started_at": datetime.now().isoformat(),
        }
        _save_bg_jobs(jobs)
        return (
            f"Background job '{label}' started (PID {proc.pid}).\n"
            f"Output logged to: {log_file}\n"
            "Use list_background to check status, kill_background to stop."
        )
    except Exception as e:
        return f"Error starting background job: {e}"


def list_background() -> str:
    """List all background jobs and whether each PID is still running."""
    jobs = _load_bg_jobs()
    if not jobs:
        return "No background jobs recorded."
    lines = [f"{len(jobs)} background job(s):"]
    for label, info in sorted(jobs.items()):
        pid     = info.get("pid", "?")
        alive   = _pid_alive(pid) if isinstance(pid, int) else False
        status  = "RUNNING" if alive else "DONE/STOPPED"
        started = info.get("started_at", "?")[:16]
        lang    = info.get("language", "?")
        lines.append(f"  • {label} [{status}] PID={pid} ({lang}, started {started})")
        lines.append(f"    Log: {info.get('log', '?')}")
    return "\n".join(lines)


def kill_background(label: str) -> str:
    """Kill a running background job by its label."""
    jobs = _load_bg_jobs()
    if label not in jobs:
        return f"No background job named '{label}'."
    info = jobs[label]
    pid  = info.get("pid")
    if not isinstance(pid, int):
        return f"No valid PID recorded for '{label}'."
    if not _pid_alive(pid):
        del jobs[label]
        _save_bg_jobs(jobs)
        return f"Job '{label}' (PID {pid}) is already stopped."
    try:
        if sys.platform == "win32":
            r = subprocess.run(
                ["taskkill", "/PID", str(pid), "/F", "/T"],
                capture_output=True, text=True, encoding="utf-8",
            )
            killed = r.returncode == 0
        else:
            import signal
            os.kill(pid, signal.SIGTERM)
            killed = True
        if killed:
            del jobs[label]
            _save_bg_jobs(jobs)
            return f"Job '{label}' (PID {pid}) killed."
        return f"Failed to kill PID {pid}."
    except Exception as e:
        return f"Error killing job: {e}"


# ──────────────────────────────────────────────────────────────────────────────
# Utilities
# ──────────────────────────────────────────────────────────────────────────────

def open_in_editor(path: str) -> str:
    """
    Open a file in VS Code (if installed) or the system default editor.
    Creates the file's parent directory if needed.
    """
    p = Path(path).expanduser()
    if not p.exists():
        return f"File not found: {path}"

    # Try VS Code
    try:
        subprocess.Popen(["code", str(p.resolve())])
        return f"Opened in VS Code: {p}"
    except FileNotFoundError:
        pass

    # Try Notepad++ (common on Windows)
    try:
        subprocess.Popen([r"C:\Program Files\Notepad++\notepad++.exe", str(p.resolve())])
        return f"Opened in Notepad++: {p}"
    except FileNotFoundError:
        pass

    # Fall back to Windows default association
    try:
        os.startfile(str(p.resolve()))
        return f"Opened in default editor: {p}"
    except Exception as e:
        return f"Could not open file: {e}"
