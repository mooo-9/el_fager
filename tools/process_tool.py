"""
Process manager — Phase 6I.
List running processes and their resource usage, or kill a process by name.
Uses psutil.
"""


def get_process_info(name: str = None) -> str:
    """
    Return RAM and CPU usage for running processes.
    name — filter by process name (partial, case-insensitive). Returns top 10 by RAM if omitted.
    """
    try:
        import psutil
    except ImportError:
        return "[psutil not installed — run: pip install psutil]"

    procs = []
    for p in psutil.process_iter(["pid", "name", "memory_info", "cpu_percent", "status"]):
        try:
            info = p.info
            pname = info["name"] or ""
            if name and name.lower() not in pname.lower():
                continue
            mem_mb = (info["memory_info"].rss / 1_048_576) if info["memory_info"] else 0
            procs.append({
                "pid":   info["pid"],
                "name":  pname,
                "mem":   mem_mb,
                "cpu":   info.get("cpu_percent", 0.0) or 0.0,
                "status": info.get("status", ""),
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if not procs:
        return f"No processes found matching '{name}'." if name else "No processes found."

    # Sort by RAM descending
    procs.sort(key=lambda x: x["mem"], reverse=True)
    top = procs[:15]

    label = f"matching '{name}'" if name else "top by RAM"
    lines = [f"Processes {label} ({len(top)} shown):\n",
             f"  {'PID':>6}  {'Name':<30}  {'RAM (MB)':>9}  {'CPU%':>6}"]
    lines.append("  " + "-" * 58)
    for p in top:
        lines.append(
            f"  {p['pid']:>6}  {p['name']:<30}  {p['mem']:>9.1f}  {p['cpu']:>5.1f}%"
        )
    total = sum(p["mem"] for p in top)
    lines.append(f"\n  Total RAM shown: {total:.1f} MB")
    return "\n".join(lines)


def kill_process(name: str) -> str:
    """
    Kill all running processes matching the given name (case-insensitive).
    name — process name or partial match (e.g. 'chrome', 'notepad')
    """
    try:
        import psutil
    except ImportError:
        return "[psutil not installed — run: pip install psutil]"

    killed = []
    failed = []

    for p in psutil.process_iter(["pid", "name"]):
        try:
            pname = p.info["name"] or ""
            if name.lower() in pname.lower():
                p.kill()
                killed.append(f"{pname} (PID {p.info['pid']})")
        except psutil.NoSuchProcess:
            pass
        except psutil.AccessDenied:
            failed.append(pname)
        except Exception:
            pass

    if not killed and not failed:
        return f"No process found matching '{name}'."

    parts = []
    if killed:
        parts.append(f"Killed: {', '.join(killed)}")
    if failed:
        parts.append(f"Access denied (run as admin to kill): {', '.join(set(failed))}")
    return "\n".join(parts)
