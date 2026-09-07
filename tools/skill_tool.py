"""
SkillForge instant-lane tools.

learn_skill / list_skills / run_skill / delete_skill /
schedule_skill / unschedule_skill / skill_proposals / dismiss_skill_proposal /
import_routines / sync_skills_to_claude

run_skill returns the skill's instructions INTO the tool loop -- Claude
executes them right there with the tools it already has. Scheduling reuses
AutonomousTaskManager (ProactiveEngine executes due tasks via brain.chat).

All return strings are cp1252-safe (spoken by TTS).
"""
import re
from datetime import datetime, timedelta
from pathlib import Path
from core import atomic

_SKILLS_PATH = Path("data/skills.json")
_SEEDS_PATH = None  # None -> SkillStore default (core/skills/seeds.json)
_PROPOSALS_PATH = Path("data/skill_proposals.json")
_CONVERSATIONS_DIR = Path("data/conversations")
_CLAUDE_SKILLS_DIR = Path(".claude/skills")

_AUTOMATION_HINT_AFTER_RUNS = 3


def _store():
    from core.skills.store import SkillStore
    return SkillStore(path=_SKILLS_PATH, seeds_path=_SEEDS_PATH)


def _miner():
    from core.skills.miner import HabitMiner
    return HabitMiner(conversations_dir=_CONVERSATIONS_DIR,
                      proposals_path=_PROPOSALS_PATH, store=_store())


def learn_skill(name: str, instructions: str, trigger_phrases: str = "") -> str:
    """Save a new skill. trigger_phrases: comma-separated optional phrases."""
    phrases = [p.strip() for p in trigger_phrases.split(",") if p.strip()]
    try:
        _store().add(name, instructions, trigger_phrases=phrases)
    except ValueError as e:
        return str(e)
    return (f"Learned skill '{name}'. Mo can run it by name"
            + (f" or by saying: {', '.join(phrases)}." if phrases else "."))


def list_skills() -> str:
    skills = _store().list_all()
    if not skills:
        return "No skills learned yet. Teach me one: 'learn this as a skill: ...'"
    lines = []
    for s in skills:
        sched = " [scheduled]" if s.get("scheduled_task_id") else ""
        lines.append(
            f"- {s['name']} ({s['source']}, run {s['run_count']}x){sched}"
        )
    return "Skills:\n" + "\n".join(lines)


def run_skill(name: str) -> str:
    """Return the skill's instructions for immediate execution in this loop."""
    store = _store()
    skill = store.get(name)
    if skill is None:
        available = ", ".join(s["name"] for s in store.list_all()) or "none"
        return f"No skill matches '{name}'. Available skills: {available}."
    store.mark_run(skill["name"])
    updated = store.get(skill["name"])
    out = (f"SKILL '{skill['name']}' -- execute these steps now using your "
           f"tools, then report the outcome to Mo:\n{skill['instructions']}")
    if (updated["run_count"] >= _AUTOMATION_HINT_AFTER_RUNS
            and not updated.get("scheduled_task_id")
            and not updated.get("automation_proposed")):
        store.set_automation_proposed(skill["name"])
        out += (f"\n\n(Note: this skill has now run {updated['run_count']} times "
                f"manually. After completing it, offer Mo to schedule it "
                f"automatically -- if he agrees, call schedule_skill.)")
    return out


def delete_skill(name: str) -> str:
    store = _store()
    skill = store.get(name)
    if skill is None:
        return f"No skill named '{name}'."
    if skill.get("scheduled_task_id"):
        unschedule_skill(skill["name"])
    store.delete(skill["name"])
    return f"Skill '{skill['name']}' deleted."


def schedule_skill(name: str, every_hours: float = 24, at_time: str = "") -> str:
    """Turn a skill into a recurring autonomous task.
    at_time='HH:MM' delays the first run to the next occurrence of that time."""
    from core.autonomous_tasks import AutonomousTaskManager
    store = _store()
    skill = store.get(name)
    if skill is None:
        return f"No skill named '{name}'."
    if skill.get("scheduled_task_id"):
        return f"'{skill['name']}' is already scheduled."

    delay_hours = 0.0
    if at_time:
        try:
            h, m = map(int, at_time.split(":"))
            now = datetime.now()
            nxt = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if nxt <= now:
                nxt += timedelta(days=1)
            delay_hours = (nxt - now).total_seconds() / 3600
        except Exception:
            return f"Invalid at_time '{at_time}' -- use HH:MM."

    task = AutonomousTaskManager().add(
        description=f"Run my skill '{skill['name']}' and report the result briefly.",
        delay_hours=delay_hours,
        recurring_hours=every_hours,
    )
    store.set_schedule(skill["name"], task["id"])
    when = f"daily at {at_time}" if at_time else f"every {every_hours:g} hours"
    return f"Done -- '{skill['name']}' is now scheduled {when}."


def unschedule_skill(name: str) -> str:
    from core.autonomous_tasks import AutonomousTaskManager
    store = _store()
    skill = store.get(name)
    if skill is None:
        return f"No skill named '{name}'."
    task_id = skill.get("scheduled_task_id")
    if not task_id:
        return f"'{skill['name']}' is not scheduled."
    AutonomousTaskManager().delete(task_id)
    store.clear_schedule(skill["name"])
    return f"'{skill['name']}' is no longer scheduled. It still runs on request."


def skill_proposals() -> str:
    """Mine conversation logs for repeated asks and list pending proposals."""
    miner = _miner()
    miner.mine()
    pending = miner.pending()
    if not pending:
        return "No new skill proposals -- no unhandled repeated asks found."
    lines = [
        f"- [{p['id']}] \"{p['example']}\" (asked {p['count']}x across "
        f"{p['days_seen']} days)"
        for p in pending[:5]
    ]
    return ("Repeated asks that could become skills:\n" + "\n".join(lines)
            + "\nSay 'make it a skill' to save one, or dismiss it.")


def accept_skill_proposal(proposal_id: str) -> str:
    """Turn a mined proposal into a real skill and stop proposing it.

    The counterpart to dismiss_skill_proposal: saying yes has to actually save
    the skill, not just retire the proposal.
    """
    miner = _miner()
    match = next((p for p in miner.pending() if p["id"] == proposal_id), None)
    if match is None:
        return f"No pending proposal with id {proposal_id}."
    example = match["example"].strip()
    name = example[:40].rstrip(" .,?!") or f"Routine {proposal_id}"
    result = learn_skill(name, example)
    miner.set_status(proposal_id, "accepted")
    return result


def dismiss_skill_proposal(proposal_id: str) -> str:
    if _miner().set_status(proposal_id, "dismissed"):
        return f"Proposal {proposal_id} dismissed. I will not suggest it again."
    return f"No proposal with id {proposal_id}."


def import_routines() -> str:
    """Scan Mo's calendar and gym program for recurring commitments; turn each
    into a skill and schedule it. Existing skill names are left untouched."""
    from core.skills.importer import RoutineImporter
    store = _store()
    candidates = RoutineImporter().find_candidates()
    if not candidates:
        return ("No recurring routines found to import -- calendar shows no "
                "repeated events in the next 2 weeks and no gym program is set.")
    created, skipped = [], []
    for c in candidates:
        if store.get(c["name"]) is not None:
            skipped.append(c["name"])
            continue
        store.add(c["name"], c["instructions"],
                  trigger_phrases=c["trigger_phrases"], source="imported")
        schedule_skill(c["name"], every_hours=c["every_hours"],
                       at_time=c["at_time"])
        cadence = "daily" if c["every_hours"] == 24 else "weekly"
        created.append(f"- {c['name']} ({cadence} at {c['at_time']}, from {c['origin']})")
    parts = []
    if created:
        parts.append(f"Imported and scheduled {len(created)} routines:\n"
                     + "\n".join(created))
    if skipped:
        parts.append("Already existed (untouched): " + ", ".join(skipped))
    parts.append("Say 'unschedule <name>' or 'delete skill <name>' to undo any of these.")
    return "\n".join(parts)


def _slug(name: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", name.lower())).strip("-")


def sync_skills_to_claude() -> str:
    """Export every skill as a Claude Code skill (.claude/skills/fager-<slug>/)
    so the same routines run from Claude Code sessions in this repo. Stale
    fager-<slug> exports for deleted skills are removed."""
    skills = _store().list_all()
    _CLAUDE_SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    wanted = {}
    for s in skills:
        slug = f"fager-{_slug(s['name'])}"
        wanted[slug] = s
    # Remove stale exports (only dirs we manage: fager-<slug>, never 'fager' itself)
    removed = 0
    for d in _CLAUDE_SKILLS_DIR.glob("fager-*"):
        if d.is_dir() and d.name not in wanted:
            skill_md = d / "SKILL.md"
            if skill_md.exists():
                skill_md.unlink()
            try:
                d.rmdir()
                removed += 1
            except OSError:
                pass
    for slug, s in wanted.items():
        d = _CLAUDE_SKILLS_DIR / slug
        d.mkdir(exist_ok=True)
        triggers = ", ".join(s.get("trigger_phrases", [])) or "the skill name"
        atomic.write(d / "SKILL.md",
            "---\n"
            f"name: {slug}\n"
            f"description: El Fager skill '{s['name']}' -- use when Mo says {triggers}.\n"
            "---\n\n"
            f"# {s['name']} (El Fager skill)\n\n"
            "Preferred: send this to the running El Fager via the `fager` bridge "
            f"skill with the command: run my skill '{s['name']}'\n\n"
            "If El Fager is not running, execute the steps yourself with your "
            "own tools where possible:\n\n"
            f"{s['instructions']}\n",
            encoding="utf-8",
        )
    return (f"Synced {len(wanted)} skills to Claude Code at {_CLAUDE_SKILLS_DIR}\\fager-*"
            + (f" (removed {removed} stale)" if removed else "")
            + ". They are available in Claude Code sessions in this repo.")
