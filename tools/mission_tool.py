"""
Mission instant-lane tools: start_mission, mission_status, cancel_mission.

Steps are executed by the ProactiveEngine through the agent supervisor, so
every step is inspected by Warden before it counts as done.
All return strings are cp1252-safe (TTS-bound).
"""


def _mgr():
    from core.missions import MissionManager
    return MissionManager()


def _parse_step(line: str) -> tuple[str, bool, str | None, str | None]:
    """Split one raw step line into (description, joins_previous, agent, acceptance).

    '&' prefix  -> runs in the same cycle as the previous step (parallel group)
    '@callsign' -> assign the step to that agent
    '-> ...'    -> acceptance criteria Warden judges the result against
    """
    from core.agents.registry import resolve

    s = line.strip()
    joins_previous = s.startswith("&")
    if joins_previous:
        s = s[1:].strip()

    # Split the criteria off BEFORE stripping list numbering -- otherwise a
    # criterion ending in a digit ("-> at least 3") loses it to the strip.
    acceptance = None
    if "->" in s:
        s, _, criteria = s.partition("->")
        acceptance = criteria.strip() or None

    s = s.strip(" -*0123456789.").strip()

    agent = None
    if s.startswith("@"):
        name, _, rest = s[1:].partition(" ")
        spec = resolve(name.rstrip(":,"))
        if spec is not None:
            agent = spec.callsign
            s = rest.strip()
        # An unknown @name is left in the description -- the brain will read it
        # as context rather than silently dropping what Mo asked for.

    return s, joins_previous, agent, acceptance


def start_mission(goal: str, steps: str) -> str:
    """Create a mission. steps: newline- or semicolon-separated ordered steps.
    A step starting with '&' is independent of the PREVIOUS step and runs in
    the same cycle (parallel group). '@callsign' assigns the step to an agent;
    '-> criteria' states what a finished result must contain."""
    from core.missions import ForbiddenMissionError

    raw = steps.replace(";", "\n").splitlines()
    step_list: list[str] = []
    group_list: list[int] = []
    agent_list: list[str | None] = []
    acceptance_list: list[str | None] = []
    group = 0
    for line in raw:
        if not line.strip():
            continue
        desc, joins_previous, agent, acceptance = _parse_step(line)
        if not desc:
            continue
        if not (joins_previous and group > 0):
            group += 1
        step_list.append(desc)
        group_list.append(group)
        agent_list.append(agent)
        acceptance_list.append(acceptance)
    try:
        mission = _mgr().create(goal, step_list, groups=group_list,
                                agents=agent_list, acceptance=acceptance_list)
    except ForbiddenMissionError:
        return ("I cannot start that mission -- it includes live-trading "
                "confirmation steps, which stay manual by design.")
    except ValueError as e:
        return str(e)
    assigned = sorted({a for a in agent_list if a})
    crew = f" Assigned to {', '.join(assigned)}." if assigned else ""
    return (f"Mission '{goal}' started with {len(mission['steps'])} steps.{crew} "
            f"I will work through them in the background, about one step per "
            f"minute, check each result before moving on, and tell Mo when it "
            f"is done or if I get stuck.")


def mission_status() -> str:
    return _mgr().format_status()


def cancel_mission() -> str:
    mgr = _mgr()
    active = mgr.get_active()
    if active is None:
        return "No mission is running."
    mgr.cancel(active["id"])
    return f"Mission '{active['goal']}' cancelled."
