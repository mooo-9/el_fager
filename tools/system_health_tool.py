"""
System health monitoring for El Fager.

CPU, RAM, disk, uptime, and top processes — all via psutil (no external dependencies).
"""


def system_health() -> str:
    """Full system status: CPU, RAM, disk, uptime, and top 5 CPU processes."""
    try:
        import psutil
        from datetime import datetime, timedelta

        cpu_pct = psutil.cpu_percent(interval=1)
        cpu_count = psutil.cpu_count(logical=False)
        cpu_threads = psutil.cpu_count(logical=True)

        ram = psutil.virtual_memory()
        ram_used_gb = ram.used / (1024 ** 3)
        ram_total_gb = ram.total / (1024 ** 3)

        disk = psutil.disk_usage("C:\\")
        disk_free_gb = disk.free / (1024 ** 3)
        disk_total_gb = disk.total / (1024 ** 3)

        boot_time = datetime.fromtimestamp(psutil.boot_time())
        uptime = datetime.now() - boot_time
        days = uptime.days
        hours = uptime.seconds // 3600
        uptime_str = f"{days}d {hours}h" if days else f"{hours}h {(uptime.seconds % 3600) // 60}m"

        procs = []
        for p in psutil.process_iter(["name", "cpu_percent"]):
            try:
                procs.append((p.info["cpu_percent"] or 0, p.info["name"]))
            except Exception:
                pass
        top = sorted(procs, reverse=True)[:5]
        top_str = ", ".join(f"{n} {c:.0f}%" for c, n in top if c > 0) or "idle"

        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        return (
            f"System Health — {now}\n"
            f"CPU:   {cpu_pct}% ({cpu_count} cores, {cpu_threads} threads)\n"
            f"RAM:   {ram_used_gb:.1f} GB / {ram_total_gb:.1f} GB used ({ram.percent}%)\n"
            f"Disk:  {disk_free_gb:.0f} GB / {disk_total_gb:.0f} GB free (C:\\)\n"
            f"Up:    {uptime_str}\n"
            f"Top:   {top_str}"
        )
    except Exception as e:
        return f"[system_health failed: {e}]"


def get_disk_space(path: str = "C:\\") -> str:
    """Free/used/total disk space for a drive path."""
    try:
        import psutil
        disk = psutil.disk_usage(path)
        free_gb = disk.free / (1024 ** 3)
        used_gb = disk.used / (1024 ** 3)
        total_gb = disk.total / (1024 ** 3)
        return (
            f"Disk ({path}): {free_gb:.1f} GB free of {total_gb:.1f} GB "
            f"({disk.percent}% used, {used_gb:.1f} GB used)."
        )
    except Exception as e:
        return f"[get_disk_space failed: {e}]"


def get_cpu_usage(interval: float = 1) -> str:
    """CPU usage percentage averaged over an interval (seconds)."""
    try:
        import psutil
        pct = psutil.cpu_percent(interval=interval)
        cores = psutil.cpu_count(logical=False)
        threads = psutil.cpu_count(logical=True)
        freq = psutil.cpu_freq()
        freq_str = f" @ {freq.current:.0f} MHz" if freq else ""
        return f"CPU: {pct}% ({cores} cores / {threads} threads{freq_str})."
    except Exception as e:
        return f"[get_cpu_usage failed: {e}]"


def get_ram_usage() -> str:
    """RAM total, used, available, and percentage."""
    try:
        import psutil
        ram = psutil.virtual_memory()
        used_gb = ram.used / (1024 ** 3)
        avail_gb = ram.available / (1024 ** 3)
        total_gb = ram.total / (1024 ** 3)
        return (
            f"RAM: {used_gb:.1f} GB used / {total_gb:.1f} GB total "
            f"({ram.percent}% used, {avail_gb:.1f} GB available)."
        )
    except Exception as e:
        return f"[get_ram_usage failed: {e}]"


def get_system_uptime() -> str:
    """Time elapsed since last system boot."""
    try:
        import psutil
        from datetime import datetime
        boot_time = datetime.fromtimestamp(psutil.boot_time())
        uptime = datetime.now() - boot_time
        days = uptime.days
        hours = uptime.seconds // 3600
        minutes = (uptime.seconds % 3600) // 60
        boot_str = boot_time.strftime("%Y-%m-%d %H:%M")
        if days:
            up_str = f"{days} days, {hours} hours, {minutes} minutes"
        elif hours:
            up_str = f"{hours} hours, {minutes} minutes"
        else:
            up_str = f"{minutes} minutes"
        return f"System up for {up_str} (booted at {boot_str})."
    except Exception as e:
        return f"[get_system_uptime failed: {e}]"


def get_top_processes(n: int = 5) -> str:
    """Top N processes by CPU usage."""
    try:
        import psutil
        procs = []
        for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
            try:
                procs.append(p.info)
            except Exception:
                pass
        # Sample a second time for accurate CPU reading
        import time
        time.sleep(0.5)
        for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
            try:
                info = p.info
                for existing in procs:
                    if existing["pid"] == info["pid"]:
                        existing["cpu_percent"] = info["cpu_percent"]
                        existing["memory_percent"] = info["memory_percent"]
            except Exception:
                pass

        sorted_procs = sorted(procs, key=lambda x: x.get("cpu_percent") or 0, reverse=True)[:n]
        if not sorted_procs:
            return "No processes found."
        lines = [f"Top {n} processes by CPU:"]
        for i, p in enumerate(sorted_procs, 1):
            cpu = p.get("cpu_percent") or 0
            mem = p.get("memory_percent") or 0
            lines.append(f"  {i}. {p['name'][:30]} — CPU {cpu:.1f}%, RAM {mem:.1f}%")
        return "\n".join(lines)
    except Exception as e:
        return f"[get_top_processes failed: {e}]"
