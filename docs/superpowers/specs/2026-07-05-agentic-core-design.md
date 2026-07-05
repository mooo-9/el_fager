# Agentic Core — missions, telemetry, cost metering

**Date:** 2026-07-05
**Status:** Approved by Mo ("DO IT" on the agentic core track: multi-step
planning, observability, cost metering).

## Why

El Fager executes single requests well (tool loop, skills, agents) but has no
way to carry a MULTI-STEP goal across time and restarts ("research X, then
compare with Y, then write a summary, then schedule the digest"), and Mo has
zero visibility into what the assistant costs or how it performs.

## Part 1 — Missions (multi-step planning layer)

A **mission** is a goal decomposed into ordered steps, persisted in
`data/missions.json`, executed ONE STEP PER PROACTIVE CYCLE (60s) via
`brain.chat()`. This design gives:

- decomposition: the model plans steps up front (`start_mission`)
- recovery: each step retries once on failure, then the mission is `blocked`
  and Mo is told exactly which step failed and why
- durability: state is on disk — a crash/restart resumes at the same step
  (watchdog restarts El Fager; ProactiveEngine picks the mission back up)
- context carry-over: each step's prompt includes the goal + results of all
  completed steps (truncated)

`core/missions.py` — MissionManager: create/get_active/advance bookkeeping.
`tools/mission_tool.py` — start_mission, mission_status, cancel_mission.
`core/proactive.py` — `_check_missions()`: executes at most one step per
cycle; announces completion or blockage; runs in all waking hours.
Brain: 3 tool schemas + dispatch + system-prompt section ("for multi-part or
long-running requests, decompose into a mission").

Mission record: `{id, goal, steps: [{n, description, status:
pending|running|done|failed, result, attempts}], status:
in_progress|done|blocked|cancelled, created_at, updated_at}`.

Money safety: mission steps run through brain.chat(), so the live-trading
confirmation state machine still gates real-money actions. start_mission
rejects steps containing "confirm live trading" (same rule as skills).

## Part 2 — Telemetry + cost metering (observability)

`core/telemetry.py`:
- `record_api_usage(source, model, usage, latency_ms, tools_used)` appends a
  JSON line to `data/telemetry/YYYY-MM-DD.jsonl` with computed `cost_usd`.
- Pricing table (per 1M tokens, cached 2026-07-05 from the claude-api skill):
  fable-5 10/50, opus-4-x 5/25, sonnet-5 & sonnet-4-6 3/15, haiku 1/5.
  Cache reads bill ~0.1x input; cache writes ~1.25x input. Unknown models fall
  back to sonnet-tier pricing (safe overestimate for a default assistant).
- `summarize(days)` -> totals + per-source breakdown + avg latency.
- Never raises (observability must not break the assistant).

Brain instrumentation: both `client.messages.create` call sites (`chat` and
`chat_with_screenshot`) route through `Brain._create_message()`, which times
the call and records telemetry (source="chat"/"screenshot"). Specialist agents
create their own anthropic clients — instrumenting them is OUT OF SCOPE this
phase (noted follow-up); the brain loop is the dominant spend.

`tools/usage_tool.py` — `usage_report(days)`: spoken-friendly cost/latency
report ("what did you cost me today/this week").

Budget alert: `_check_api_budget()` in proactive (evening window, 20h
cooldown) warns when today's cost exceeds `api_daily_budget_usd` from
`data/settings.json` (default 5.0 USD; 0 disables).

## Out of scope (recorded)

- Telemetry inside the 6 specialist agents (each has its own client).
- Parallel mission steps / step dependencies (steps are strictly sequential).
- OpenTelemetry / external dashboards — JSONL + usage_report is enough for
  a single-user assistant.

## Success criteria

- "Plan a mission: research European brokers, compare fees, write me a
  summary" -> mission created, steps execute one per minute, spoken result.
- Kill El Fager mid-mission -> restart resumes the remaining steps.
- "What did you cost me this week?" -> real numbers from telemetry.
- Budget exceeded -> one evening warning.
- Full suite green.
