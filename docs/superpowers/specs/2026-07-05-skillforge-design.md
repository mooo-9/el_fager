# SkillForge — daily activities become skills, skills become automations

**Date:** 2026-07-05
**Status:** Approved by Mo (brainstorm answers: learn via BOTH explicit teaching
and log mining; automation is propose-then-confirm; ship all 4 seed packs).

## Why

Mo wants El Fager to notice what he does every day (research, music, study,
briefings — anything), capture it as a reusable *skill*, and then offer to run
that skill automatically on a schedule. Today every routine lives in Mo's head
and gets re-typed; nothing compounds.

## Core idea

A **skill is a stored natural-language instruction template**, not code.
`run_skill` returns the instructions INTO the agentic tool loop, and Claude
executes them right there with the 355+ tools and 6 agents it already has.
This makes skills domain-universal (study/research/music/anything) with zero
per-domain engine code — the seed packs are just data.

## Architecture

```
core/skills/store.py   SkillStore     data/skills.json     CRUD + run counters + seed install
core/skills/miner.py   HabitMiner     data/conversations/  repetition -> proposals
                                      data/skill_proposals.json
tools/skill_tool.py    8 instant tools (learn/list/run/delete/schedule/unschedule/proposals/dismiss)
core/brain.py          tool schemas + dispatch + system-prompt section
core/proactive.py      _check_skill_proposals() — max ONE proposal per day, morning window
```

### Skill record
`{id, name, instructions, trigger_phrases, source: taught|mined|seed, created_at,
run_count, last_run_at, scheduled_task_id, automation_proposed}`

### Learning paths
1. **Taught:** "learn this as a skill: every morning check NVDA and my calendar"
   -> brain calls `learn_skill(name, instructions, trigger_phrases)`.
2. **Mined:** HabitMiner scans the last 14 days of user messages, normalizes
   (lowercase, strip digits/punctuation, drop stopwords), fingerprints by
   sorted keyword set, and proposes anything asked on >= 3 distinct days that
   no existing skill covers. Proposals persist with status
   pending/accepted/dismissed so the same habit is never re-proposed.

### Execution
`run_skill(name)` increments run_count and returns
`SKILL '<name>' — execute these steps now using your tools: <instructions>`.
No recursion into brain.chat(); the current tool loop (cap 15) does the work.

### Automation (propose -> confirm)
- After a skill's 3rd manual run, `run_skill` appends a hint telling the model
  to offer scheduling; `automation_proposed` flag prevents nagging.
- On "yes": `schedule_skill(name, every_hours, at_time)` creates a recurring
  autonomous task ("Run my skill '<name>' and report the result") via
  AutonomousTaskManager; task id stored for `unschedule_skill`.
  `at_time="HH:MM"` computes the delay to the next occurrence, recurring 24h.
- ProactiveEngine picks scheduled runs up within 60s of due time (existing path).

### Money safety (hard rule)
`learn_skill` REJECTS instructions containing live-trading confirmation phrases
("confirm live trading"). Skills can *analyze* markets; the deterministic
live-trading state machine remains the only path to real-money actions.

### Seed packs (installed once on first store load, source="seed", NEVER auto-scheduled)
- **Study:** summarize-new-lectures (OneDrive lecture folder via file_agent),
  exam-prep-quiz, study-review-reminder.
- **Research:** morning-research-digest (topics from memory/facts via research_agent).
- **Music:** focus-mode (play_music focus playlist + volume), gym-mode.
- **Daily-life:** morning-routine (briefing+calendar+prayer+portfolio),
  evening-shutdown (journal nudge + tomorrow preview), weekly-review-compile.

## Out of scope (this phase)
- Screen-watching / OS-level activity capture (privacy + heavy; later phase).
- Multi-step skill chains with per-step scheduling.
- Editing skills via UI; edits happen conversationally (delete + relearn).

## Success criteria
- Teach a skill in one sentence; run it by name or trigger phrase.
- Miner proposes a skill from 3+ repeats across days; one proposal max per day.
- Confirming schedules it; it fires via the autonomous-task path.
- All 4 seed packs present on first boot; full pytest suite green.
