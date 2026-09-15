"""
Mission instant-lane tools: start_mission, mission_status, cancel_mission.

Steps are executed by the ProactiveEngine (one per 60s cycle) via brain.chat.
All return strings are cp1252-safe (TTS-bound).
"""


def _mgr():
    from core.missions import MissionManager
    return MissionManager()


def start_mission(goal: str, steps: str) -> str:
    """Create a mission. steps: newline- or semicolon-separated ordered steps.
    A step starting with '&' is independent of the PREVIOUS step and runs in
    the same cycle (parallel group)."""
    raw = steps.replace(";", "\n").splitlines()
    step_list: list[str] = []
    group_list: list[int] = []
    group = 0
    for line in raw:
        s = line.strip()
        if not s:
            continue
        joins_previous = s.startswith("&")
        if joins_previous:
            s = s[1:].strip()
        s = s.strip(" -*0123456789.").strip()
        if not s:
            continue
        if not (joins_previous and group > 0):
            group += 1
        step_list.append(s)
        group_list.append(group)
    try:
        mission = _mgr().create(goal, step_list, groups=group_list)
    except ValueError as e:
        return str(e)
    return (f"Mission '{goal}' started with {len(mission['steps'])} steps. "
            f"I will work through them in the background, about one step per "
            f"minute, and tell Mo when it is done or if I get stuck.")


def mission_status() -> str:
    return _mgr().format_status()


def cancel_mission() -> str:
    mgr = _mgr()
    active = mgr.get_active()
    if active is None:
        return "No mission is running."
    mgr.cancel(active["id"])
    return f"Mission '{active['goal']}' cancelled."
