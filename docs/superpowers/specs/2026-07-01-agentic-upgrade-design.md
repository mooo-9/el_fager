# El Fager Agentic Upgrade — Agents-as-Tools

**Date:** 2026-07-01
**Status:** Approved, pending implementation

## Problem

`Brain.chat()` (core/brain.py) has two execution paths:

1. **Instant lane** — a proper multi-turn Claude tool-use loop (`while True` at brain.py:6184) with 355+ tools. Already genuinely agentic within its own domain.
2. **Agent lane** — `_try_agent_dispatch()` (brain.py:6099) runs *before* the tool loop. It calls `classify_intent()` (core/agents/router.py, keyword-based, first-match-wins) and, if the message matches a specialist agent's keywords, routes to exactly one of `ScreenAgent`, `BrowserAgent`, `StocksAgent`, `ResearchAgent`, `FileAgent`, or `HealthAgent`. That agent runs once, returns plain text, and `chat()` returns immediately.

The agent lane is a hard fork: once a message matches, e.g., the `screen` keywords, `ScreenAgent.run()` executes and its result is the final answer — the instant lane's 355 tools and the other 5 specialist agents are unreachable for the rest of that turn. Multi-domain requests ("check the screen error, search the web for a fix, email it to me") dead-end at the first matched agent.

Each specialist agent already does proper internal iteration where its domain calls for it (`ScreenAgent` runs up to 10 perceive-act steps via Claude Vision) — the gap is purely **cross-domain composition**, not internal agent capability.

## Solution: Agents-as-Tools

Fold the 6 specialist agents into the existing instant-lane tool loop as callable tools, instead of intercepting before it. Claude's own reasoning decides when to invoke a specialist agent, receives its result as a normal `tool_result`, and can continue — call another tool, call a different agent, retry, or finish.

### What stays a pre-loop intercept

`_try_agent_dispatch()` keeps exactly 3 branches: `gate_check`, `confirm_live`, `cancel_live`. These govern activating real-money trading — a deterministic state machine with a 60-second confirmation window and exact-phrase matching. This is a financial safety control, not a routing decision, and must not be left to LLM tool-use judgment. It stays exactly as implemented today.

### What moves into the tool loop

`screen`, `browser`, `stocks_agent`, `research`, `file`, `health` — the 6 specialist-agent branches — are removed from `_try_agent_dispatch()`. Each becomes a tool:

| Tool name | Wraps | Input schema |
|---|---|---|
| `screen_agent` | `ScreenAgent` | `{"task": {"type": "string"}}`, required `["task"]` |
| `browser_agent` | `BrowserAgent` | same |
| `stocks_agent` | `StocksAgent` | same |
| `research_agent` | `ResearchAgent` | same |
| `file_agent` | `FileAgent` | same |
| `health_agent` | `HealthAgent` | same |

Each tool's `description` field embeds the corresponding keyword examples currently living in `router.py` (e.g. `_SCREEN_KEYWORDS`, `_RESEARCH_KEYWORDS`) as natural-language guidance, so there is one source of truth for "when does this agent apply" — `router.py`'s keyword lists — referenced both by `classify_intent()` (still fully tested, used for the 3 remaining intercepts) and by the new tool descriptions (written by hand, not generated, to keep the schema simple).

All 6 tools are added to `_CORE_NAMES` (always included in every request, unlike the 355 instant tools which are keyword-filtered per-message by `_select_tools()` for token budget). Six small tool schemas is cheap; Claude needs visibility into all of them to route correctly across domains.

`_dispatch_tool()` (brain.py:4749) gets 6 new `elif` branches following the existing pattern:

```python
elif name == "screen_agent":
    from core.agents.screen_agent import ScreenAgent
    return ScreenAgent().run(tool_input["task"])
```

(and equivalently for the other 5).

### Safety addition: tool-loop iteration cap

`chat()`'s `while True` loop currently has no iteration limit. This is low-risk today because instant tools are fast and self-limiting in practice. Once agent tools are reachable from inside the loop — `ScreenAgent` alone can take up to 10 internal steps, each a vision API call — an LLM stuck in a confused call→retry→call chain could run long and expensive before naturally terminating via `end_turn`.

Add `_MAX_TOOL_ITERATIONS = 15` as a module constant. The loop tracks an iteration counter; on reaching the cap, `chat()` returns the last assistant text seen so far (if any) appended with a one-line note ("stopped after 15 steps — let me know if you want me to continue"), and logs a warning via the existing logger. This does not change behavior for any normal turn — single-domain requests finish in 1-3 iterations today.

### Out of scope

- `chat_with_screenshot()` (brain.py:6260) has its own separate tool loop and never called `_try_agent_dispatch()` — untouched by this change.
- No changes to any specialist agent's internals (`ScreenAgent.run()`, `BrowserAgent.run()`, etc.) — their existing confirmation/safety patterns for sensitive actions (password entry, form submission, financial trades) are unchanged.
- `router.py`'s keyword lists and `classify_intent()` function are not deleted or restructured — only how `_try_agent_dispatch()` uses the result changes.
- The Phase 7b autonomous task queue (`core/autonomous_tasks.py`) calls `brain.chat()` per task today and continues to do so unchanged — it benefits from this change automatically (a queued task can now span multiple agents/tools in one `chat()` call) without any code change to the task queue itself.

## Testing

- `tests/agents/test_router.py` — unaffected, no changes. `classify_intent()` is untouched.
- `tests/test_brain_routing.py` — 3 of 4 tests (`test_screen_task_routes_to_screen_agent`, `test_browser_task_routes_to_browser_agent`, `test_research_task_routes_to_research_agent`) assert the old pre-loop dispatch behavior and must be rewritten: mock `client.messages.create` to return a `tool_use` block naming the relevant agent tool, patch the agent's `.run()` method, assert the tool dispatches correctly and the final `end_turn` response surfaces the agent's result. `test_instant_task_bypasses_agents` needs no change.
- New test: cross-domain chaining — mock two sequential `tool_use` rounds (one agent tool call, one instant tool call) in a single `chat()` invocation, assert both fire and the final text reflects both steps.
- New test: iteration cap — mock `client.messages.create` to always return `stop_reason="tool_use"`, assert the loop terminates at 15 iterations with the graceful fallback message rather than looping forever.
- No changes needed to any specialist agent's own test file (`test_screen_agent.py`, `test_browser_agent.py`, etc.) — their `run()` signatures are unchanged.
