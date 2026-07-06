"""
Weekly repo + usage health check.

Runs the test suite and the usage audit; writes a markdown report to
data/logs/health_report_YYYY-MM-DD.md; if the claude CLI is installed,
prepends a 3-conclusion summary; announces via Windows toast.

Registered as a Windows scheduled task by scripts/setup_weekly_health_check.ps1.
Run manually:  python -X utf8 scripts/weekly_health_check.py
"""
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable


def run(cmd: list[str], timeout: int = 600) -> str:
    try:
        p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        return (p.stdout + p.stderr).strip()
    except Exception as e:
        return f"FAILED TO RUN {cmd[0]}: {e}"


def main() -> None:
    today = date.today().isoformat()

    tests = run([PY, "-m", "pytest", "-q", "--tb=no"])
    tests_tail = "\n".join(tests.splitlines()[-5:])
    usage = run([PY, "-X", "utf8", str(ROOT / "scripts" / "usage_audit.py")])

    report = (
        f"# El Fager weekly health report — {today}\n\n"
        f"## Test suite\n```\n{tests_tail}\n```\n\n"
        f"## Usage audit\n```\n{usage}\n```\n"
    )

    claude = shutil.which("claude")
    if claude:
        summary = run(
            [claude, "-p",
             "You are reviewing a weekly health report for El Fager, a personal "
             "AI assistant. State the 1-3 conclusions that matter most (failing "
             "tests, rising transcription garbage rate, unused features). "
             "Be blunt and concrete, max 5 sentences.\n\n"
             + report],
            timeout=180,
        )
        if summary and not summary.startswith("FAILED TO RUN"):
            report = f"## Summary\n{summary}\n\n{report}"

    out = ROOT / "data" / "logs" / f"health_report_{today}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")

    try:
        from winotify import Notification
        first = report.splitlines()[1] if report.startswith("## Summary") else "Report ready."
        Notification(app_id="El Fager", title="Weekly health report",
                     msg=first[:200] + f"\n{out}", duration="long").show()
    except Exception:
        pass
    print(f"Report written to {out}")


if __name__ == "__main__":
    main()
