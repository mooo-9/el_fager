# Missions v2 (parallel groups) + dashboard command channel

**Date:** 2026-07-05
**Status:** Approved by Mo ("do both").

## Part 1 — Parallel mission steps (groups)

Missions were strictly sequential: one step per 60s cycle, even when steps
are independent ("research A" / "research B" don't need each other). v2 adds
**groups**: steps in the same group are independent and execute in the SAME
proactive cycle (back-to-back, up to 3 per cycle to bound cost); groups
execute in ascending order and later groups see earlier groups' results.

Why back-to-back rather than true threading: `brain.chat()` shares
conversation state and the live-trading state machine — concurrent calls
would race. Same-cycle batching removes the 60s gaps (the actual latency
cost) with zero thread-safety risk.

**Syntax** (start_mission steps text): a line starting with `&` joins the
previous step's group; otherwise it starts a new group.

```
1. research European brokers
& research Egyptian broker restrictions
compare fees and features
write a summary
```
-> group 1: steps 1+2 (same cycle), group 2: compare, group 3: summary.

**Changes:** `core/missions.py` — per-step `group` int; `create(goal, steps,
groups=None)` (None = each step its own group, fully sequential —
back-compatible); `next_steps()` returns pending steps of the lowest
incomplete group (a blocked mission still blocks on 2nd failure of any step).
`core/proactive.py::_check_missions` — executes up to `_MAX_STEPS_PER_CYCLE=3`
of `next_steps()` per cycle. `tools/mission_tool.py` — `&` parsing; brain
prompt documents the syntax.

## Part 2 — Dashboard command channel (authenticated)

The dashboard becomes two-way: `POST /api/command` with JSON `{"text": ...}`
queues the command as an autonomous task (executed by the ProactiveEngine via
brain.chat within 60s — the same trusted path as voice, so ALL existing
gates apply, including live-trading confirmation which cannot complete over
this channel).

**Auth:** static bearer token. `start_dashboard()` generates
`dashboard_token` (secrets.token_urlsafe(24)) into data/settings.json on
first run. Every POST requires `Authorization: Bearer <token>`; wrong or
missing -> 401, no side effects. GET endpoints stay tokenless (read-only).
The HTML page gains a command box; the token is entered once on the phone
and kept in localStorage. Command text capped at 500 chars. Results are
visible in the existing tasks section of the status page (and spoken on the
laptop as usual).

**Out of scope:** HTTPS (LAN-only surface), multi-user tokens, streaming
results to the phone.

## Success criteria
- Mission with `&` steps: grouped steps run in one cycle; later groups wait;
  results flow forward. Sequential missions behave exactly as before.
- POST without/with-wrong token -> 401 and nothing queued; with token ->
  autonomous task appears and executes.
- Full suite green.
