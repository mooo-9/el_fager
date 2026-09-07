import subprocess

_APP_ALIASES: dict[str, str] = {
    "chrome": "chrome.exe",
    "google chrome": "chrome.exe",
    "firefox": "firefox.exe",
    "edge": "msedge.exe",
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "calc": "calc.exe",
    "explorer": "explorer.exe",
    "file explorer": "explorer.exe",
    "word": "winword.exe",
    "excel": "excel.exe",
    "powerpoint": "powerpnt.exe",
    "outlook": "outlook.exe",
    "vscode": "code",
    "vs code": "code",
    "cursor": "cursor",
    "terminal": "wt.exe",
    "windows terminal": "wt.exe",
    "cmd": "cmd.exe",
    "powershell": "pwsh.exe",
    "spotify": "spotify.exe",
    "vlc": "vlc.exe",
    "paint": "mspaint.exe",
    "snipping tool": "SnippingTool.exe",
    "task manager": "taskmgr.exe",
    "settings": "ms-settings:",
}

_BLOCKED_KEYWORDS = [
    "rm ", "del ", "rmdir", "rd ", "format", "shutdown", "restart",
    "reg delete", "reg add", "diskpart", "cipher /w", "sfc /scannow",
    "bcdedit", "net user", "net localgroup",
]


def open_app(app_name: str) -> str:
    """Launch a Windows application by name or alias."""
    name_lower = app_name.lower().strip()
    exe = _APP_ALIASES.get(name_lower, app_name)

    try:
        subprocess.Popen(exe, shell=True)
        return f"Launched: {app_name}"
    except Exception as e:
        return f"Failed to launch '{app_name}': {e}"


def run_command(command: str, safe_mode: bool = True) -> str:
    """
    Run a PowerShell command and return stdout/stderr.
    safe_mode=True blocks destructive commands.
    """
    if safe_mode:
        cmd_lower = command.lower()
        for blocked in _BLOCKED_KEYWORDS:
            if blocked in cmd_lower:
                return f"Blocked in safe mode: command contains '{blocked.strip()}'"

    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            text=True,
            timeout=10,
            encoding="utf-8",
            errors="replace",
        )
        output = result.stdout.strip() or result.stderr.strip()
        return (output[:2000] + "\n[truncated]") if len(output) > 2000 else (output or "(no output)")
    except subprocess.TimeoutExpired:
        return "Command timed out (10s limit)"
    except Exception as e:
        return f"Command error: {e}"
