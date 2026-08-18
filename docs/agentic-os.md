# El Fager as an agentic OS — the backbone loop

El Fager's foundation is one lifecycle. Every feature either feeds it or
consumes it:

```
 observe ──► mine ──► skills ──► automation ──► measure ──► prune/promote
 (usage,     (Habit-  (Skill-    (schedule_     (run_count,  (delete unused,
  calendar,   Miner,   Store)     skill →        telemetry,   schedule the
  gym, ...)   Routine-            autonomous     weekly       repeated)
              Importer)           tasks)         health check)
```

## The pieces and where they live

| Stage | Module | Entry points |
|---|---|---|
| Observe | `core/conversation_log.py`, calendar, gym program | every turn is logged (test sessions diverted by `EL_FAGER_TEST_MODE`) |
| Mine | `core/skills/miner.py` (repeated asks), `core/skills/importer.py` (calendar + gym) | morning proposal check; "import my routines" |
| Skills | `core/skills/store.py` — skills are **data** (instruction templates), not code | "learn this as a skill", `run_skill` |
| Automation | `tools/skill_tool.py::schedule_skill` → `core/autonomous_tasks.py` → ProactiveEngine executes via `brain.chat` | auto-proposed after 3 manual runs |
| Measure | `core/telemetry.py`, `scripts/usage_audit.py` | Run on demand; transcription-quality alert |

## Voice is the primary interface

- Wake word ("hey fager") or Ctrl+Space opens a **conversation**, not a
  one-shot: context persists across turns, the mic reopens for 6 s after each
  reply, and the conversation ends on silence, an end phrase, or 10 turns
  (`core/pipeline.py`).
- Transcription only accepts ar/en/fr and drops no-speech segments
  (`core/voice_in.py`) — noise cannot reach the brain.

## Claude Code is a second frontend, same backbone

- `.claude/skills/fager/` — bridge: any Claude Code session can send commands
  to the running El Fager over the authenticated channel (port 8765) and read
  results back.
- `sync_skills_to_claude` exports every skill as `.claude/skills/fager-<slug>/`
  so the same routines run from either frontend. One skill store, two mouths.

## Rules the backbone keeps

1. **Propose, never impose** — mining and run-count hints only ever *offer*
   automation; Mo confirms.
2. **Skills are data** — no skill contains code; the brain executes
   instructions with the tools it already has, so every skill inherits every
   safety gate.
3. **Test traffic never touches production data** (`EL_FAGER_TEST_MODE`,
   enforced suite-wide in `tests/conftest.py`).
