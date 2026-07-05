# Agentic Core implementation plan

Spec: `docs/superpowers/specs/2026-07-05-agentic-core-design.md`

- **T1 Telemetry core** — `core/telemetry.py` (pricing table, record_api_usage,
  summarize, never-raise). Tests: `tests/test_telemetry.py`.
- **T2 Brain metering + usage tool + budget check** — `Brain._create_message()`
  wrapper at both call sites; `tools/usage_tool.py::usage_report`; brain schema
  + dispatch + prompt line; `_check_api_budget()` in proactive.
  Tests: extend telemetry tests + proactive tests + routing test.
- **T3 MissionManager** — `core/missions.py` CRUD/advance/retry/block.
  Tests: `tests/test_missions.py`.
- **T4 Mission tools + proactive executor + brain wiring** —
  `tools/mission_tool.py`; `_check_missions()`; 3 schemas + dispatch + prompt.
  Tests: `tests/test_mission_tool.py` + proactive tests.
- **T5** — docs, memory update, push.

Each task: failing tests first, implement, FULL suite green, commit.
