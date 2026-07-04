# SkillForge implementation plan

Spec: `docs/superpowers/specs/2026-07-05-skillforge-design.md`

## Task 1 — SkillStore + seed packs
- `core/skills/__init__.py`, `core/skills/store.py`
- `data/skill_seeds.json` (committed; ~9 skills across 4 packs)
- SkillStore: load/save `data/skills.json`, `add`, `get` (by name or trigger
  phrase, case-insensitive), `delete`, `mark_run`, `set_schedule`, `list_all`,
  `install_seeds` (idempotent, runs on first load)
- learn_skill safety: reject live-trading confirmation instructions
- Tests: `tests/skills/test_skill_store.py`

## Task 2 — HabitMiner
- `core/skills/miner.py`: `normalize(text)`, `fingerprint(text)`,
  `mine(days=14, min_days=3)` -> new pending proposals in
  `data/skill_proposals.json`; skips fingerprints covered by existing skills
  or existing proposals (any status)
- Tests: `tests/skills/test_habit_miner.py`

## Task 3 — skill_tool + brain wiring
- `tools/skill_tool.py`: learn_skill, list_skills, run_skill, delete_skill,
  schedule_skill, unschedule_skill, skill_proposals, dismiss_skill_proposal
- brain.py: 8 tool schemas, dispatch branches in `_dispatch_tool_once`,
  system-prompt section (teach/run/propose-confirm behavior), tool group + triggers
- Tests: `tests/skills/test_skill_tool.py`, routing test in tests/test_agent_tools.py style

## Task 4 — Proactive proposal delivery
- `core/proactive.py`: `_check_skill_proposals()` in morning window (7-11),
  20h cooldown, delivers at most ONE pending proposal per day
- Tests: extend `tests/test_proactive_engine.py`

## Task 5 — Docs + memory
- Commit spec/plan; update project_el_fager.md with phase status + gotchas

Each task: failing tests first, implement, FULL suite green, commit.
