---
name: new-tool
description: Scaffold a new El Fager tool — tools/<x>_tool.py + TOOLS schema + group/triggers + dispatch wiring + tests. Use whenever adding a capability the brain should be able to call.
---

# Add a new tool to El Fager

Adding a tool touches exactly 5 places. Follow them in order; skipping the
group/trigger step means the schema never reaches Claude (slim-tools filtering).

## 1. Tool module — `tools/<x>_tool.py`

- Module docstring saying what it does.
- Plain functions that **always return a `str`** (human-readable result or
  `"Error: ..."`). Never return dicts/None, never `print()`.
- Heavy imports (requests, PIL, google clients) go **inside** the function,
  not at module top — brain.py lazy-imports tool modules per call.
- Catch expected failures and return the error as a string. Only let
  exceptions escape when they are transient (network/429/5xx) — the dispatch
  wrapper retries those with backoff.

## 2. Schema — `TOOLS` list in `core/brain.py` (starts ~line 432)

Append under a `# ── Section Name ──…` comment (add one for a new domain):

```python
{
    "name": "my_tool_action",
    "description": "One sentence Claude uses to decide when to call this.",
    "input_schema": {
        "type": "object",
        "properties": {"arg": {"type": "string", "description": "e.g. '...'"}},
        "required": ["arg"]
    }
},
```

## 3. Group + triggers — same file

- Add the tool name(s) to a group in `_TOOL_GROUP_NAMES` (~line 4696), or
  create a new `frozenset({...})` group.
- New group ⇒ add trigger phrases to `_GROUP_TRIGGERS` (~line 4864).
- Core always-on tools go in `_CORE_NAMES` instead (rare; keep that list small).

## 4. Dispatch — `_dispatch_tool_once` in `core/brain.py` (~line 5088)

Add an `elif` branch with the import inside it, matching the existing style:

```python
elif name == "my_tool_action":
    from tools.my_tool import my_tool_action
    return my_tool_action(**tool_input)
```

Optionally mention the tool in the system-prompt tool guide (~line 364) if
Claude needs usage examples to call it correctly.

## 5. Tests — `tests/test_<x>_tool.py`

- Test the pure logic directly; mock network/OS calls.
- Add a routing/dispatch test if the tool joins an existing group
  (see `tests/test_brain_routing.py` for the pattern).
- Run: `python -m pytest tests/test_<x>_tool.py -q` then the full suite.

## Known pitfalls (bugs fixed twice before — don't reintroduce)

- When iterating response blocks use `block.type == "tool_use"` /
  `block.type == "text"` — **never** `hasattr(block, "text")`, which is true
  on tool_use blocks too.
- The chat tool loop is capped at 15 iterations; a tool that returns huge
  output every call burns the cap. Truncate long results in the tool.
- `data/` is gitignored — a tool that ships seed/static data must keep it in
  the package (see `core/skills/seeds.json` precedent), not in `data/`.
