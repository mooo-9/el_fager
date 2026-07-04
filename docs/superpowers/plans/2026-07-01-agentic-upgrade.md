# Agentic Upgrade (Agents-as-Tools) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fold El Fager's 6 specialist agents (ScreenAgent, BrowserAgent, StocksAgent, ResearchAgent, FileAgent, HealthAgent) into the existing `Brain.chat()` tool-use loop as callable tools, so a single turn can chain a specialist agent with instant-lane tools or with another specialist agent — instead of the current hard pre-loop keyword fork that dead-ends at the first matched agent.

**Architecture:** Add 6 new tool schemas to `TOOLS` in `core/brain.py`, wire them into `_dispatch_tool()`, shrink `_try_agent_dispatch()` down to the 3 financial-safety branches (`gate_check`/`confirm_live`/`cancel_live`) that must stay deterministic, and add a 15-iteration safety cap to the `chat()` tool loop now that agent tool calls can be slow/multi-step.

**Tech Stack:** Python 3.14, `anthropic` SDK (Claude tool use), `pytest` + `unittest.mock`.

## Global Constraints

- All 6 specialist agents already implement `BaseAgent.run(self, task: str) -> str` (core/agents/base_agent.py) — no agent internals change in this plan.
- `_try_agent_dispatch()`'s `gate_check`/`confirm_live`/`cancel_live` branches (financial-safety state machine, 60s confirmation window) must remain pre-loop, deterministic, untouched in behavior.
- `router.py`'s `classify_intent()` and its keyword lists are not deleted or restructured — `tests/agents/test_router.py` must stay green with zero changes.
- No changes to `chat_with_screenshot()` (separate method, never called `_try_agent_dispatch()`).
- Reference spec: `docs/superpowers/specs/2026-07-01-agentic-upgrade-design.md`.

---

## Task 1: Add the 6 specialist-agent tool schemas

**Files:**
- Modify: `core/brain.py:4368` (end of `TOOLS` list) and `core/brain.py:4393-4403` (`_CORE_NAMES`)
- Test: `tests/test_agent_tools.py` (new file)

**Interfaces:**
- Produces: 6 tool names always present in `_SLIM_TOOLS` and `_CORE_NAMES`: `screen_agent`, `browser_agent`, `stocks_agent`, `research_agent`, `file_agent`, `health_agent`. Each tool's input schema is `{"task": <string, required>}`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_agent_tools.py`:

```python
from core.brain import _SLIM_TOOLS, _CORE_NAMES

_AGENT_TOOL_NAMES = {
    "screen_agent", "browser_agent", "stocks_agent",
    "research_agent", "file_agent", "health_agent",
}


def test_all_six_specialist_agent_tools_are_defined():
    names = {t["name"] for t in _SLIM_TOOLS}
    assert _AGENT_TOOL_NAMES.issubset(names)


def test_all_six_specialist_agent_tools_are_always_core():
    assert _AGENT_TOOL_NAMES.issubset(_CORE_NAMES)


def test_agent_tool_schemas_require_task_string():
    by_name = {t["name"]: t for t in _SLIM_TOOLS}
    for name in _AGENT_TOOL_NAMES:
        schema = by_name[name]["input_schema"]
        assert schema["required"] == ["task"]
        assert schema["properties"]["task"]["type"] == "string"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "C:\claude proj\el_fager" && python -m pytest tests/test_agent_tools.py -v`
Expected: 3 FAILED — `AssertionError` (tool names not present in `_SLIM_TOOLS`/`_CORE_NAMES`).

- [ ] **Step 3: Add the 6 tool schemas to `TOOLS`**

In `core/brain.py`, find the end of the `TOOLS` list — the last entry is `notification_status` immediately followed by the closing `]` (around line 4368):

```python
    {
        "name": "notification_status",
        "description": "Check if phone notifications are configured and working. Returns setup instructions if not configured.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
]
```

Insert 6 new entries before the closing `]`, so it reads:

```python
    {
        "name": "notification_status",
        "description": "Check if phone notifications are configured and working. Returns setup instructions if not configured.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "screen_agent",
        "description": (
            "Multi-step desktop control agent -- sees the screen and performs a sequence of "
            "clicks, typing, and keyboard shortcuts to complete a task (up to 10 internal steps). "
            "Use for: clicking buttons/links, dragging files, scrolling, multi-step UI automation "
            "('open and then...', 'automate the...', 'control the app'). Do NOT use for a single "
            "one-shot description of the screen -- use analyze_screen for that."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "The user's desktop-control request, verbatim or lightly cleaned up."
                }
            },
            "required": ["task"]
        }
    },
    {
        "name": "browser_agent",
        "description": (
            "Multi-step browser automation agent -- navigates websites, fills forms, logs in, and "
            "completes multi-step web tasks. Use for: 'book a table/flight', 'log into', "
            "'fill out the form', 'search on amazon/google', or any task naming a specific website "
            "or '.com/.org/.net'. Do NOT use for one-off single actions when a simpler browser_* "
            "instant tool suffices."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "The user's web-automation request, verbatim or lightly cleaned up."
                }
            },
            "required": ["task"]
        }
    },
    {
        "name": "stocks_agent",
        "description": (
            "Deep market analysis and conviction-gated autonomous trading agent. Use for: "
            "'analyze NVDA', 'should I buy/sell X', 'your thesis/opinion/view on X', "
            "'conviction on X', 'scan my watchlist', 'why did you buy/sell X', 'my trading stats', "
            "'pause/resume trading', 'set auto-trade threshold to N'. Do NOT use for simple price "
            "lookups -- those are instant-lane tools."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "The user's stock-analysis or trading-control request."
                }
            },
            "required": ["task"]
        }
    },
    {
        "name": "research_agent",
        "description": (
            "Deep multi-source web research agent -- searches, reads multiple pages, and "
            "synthesizes a single coherent answer. Use for: 'research everything about X', "
            "'tell me everything about X', 'investigate X', 'comprehensive analysis of X', "
            "'compare and contrast X and Y', 'summarize the news about X'. Do NOT use for quick "
            "factual lookups -- use wikipedia_lookup or web_search for those."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "The research question or topic, verbatim or lightly cleaned up."
                }
            },
            "required": ["task"]
        }
    },
    {
        "name": "file_agent",
        "description": (
            "Document intelligence agent -- reads and answers questions about PDFs, Word docs, "
            "spreadsheets, and images. Use for: 'summarize this pdf/document/contract/invoice/"
            "thesis/report', 'what does this file say', 'extract from this', 'what were the "
            "payment terms'. Pass the file reference and the question together in the task string."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "The file reference and question together, e.g. 'summarize my_contract.pdf'."
                }
            },
            "required": ["task"]
        }
    },
    {
        "name": "health_agent",
        "description": (
            "Nutrition and gym tracking agent -- logs meals, calculates macros/TDEE, generates "
            "workout programs and recipes. Use for: 'I just ate X', 'log my meal', 'calories "
            "today', 'my macros', 'recipe for X', 'chest day', 'finished my workout', 'generate a "
            "training program', 'what should I do today at the gym'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "The user's nutrition or workout request, verbatim or lightly cleaned up."
                }
            },
            "required": ["task"]
        }
    },
]
```

- [ ] **Step 4: Add the 6 tool names to `_CORE_NAMES`**

In `core/brain.py`, find `_CORE_NAMES` (around line 4393):

```python
_CORE_NAMES: frozenset[str] = frozenset({
    "web_search", "fetch_page", "translate_text", "wikipedia_lookup",
    "convert_currency", "get_exchange_rates", "resolve_doi",
    "get_weather", "get_weather_forecast", "get_hourly_weather",
    "get_news", "get_all_headlines", "search_news", "read_news_article",
    "get_prayer_times",
    "remember_fact", "forget_topic", "what_do_you_know", "list_facts",
    "set_reminder", "list_reminders", "cancel_reminder",
    "get_battery_status", "get_clipboard_history",
    "analyze_screen", "ocr_screenshot",
})
```

Replace with:

```python
_CORE_NAMES: frozenset[str] = frozenset({
    "web_search", "fetch_page", "translate_text", "wikipedia_lookup",
    "convert_currency", "get_exchange_rates", "resolve_doi",
    "get_weather", "get_weather_forecast", "get_hourly_weather",
    "get_news", "get_all_headlines", "search_news", "read_news_article",
    "get_prayer_times",
    "remember_fact", "forget_topic", "what_do_you_know", "list_facts",
    "set_reminder", "list_reminders", "cancel_reminder",
    "get_battery_status", "get_clipboard_history",
    "analyze_screen", "ocr_screenshot",
    "screen_agent", "browser_agent", "stocks_agent",
    "research_agent", "file_agent", "health_agent",
})
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd "C:\claude proj\el_fager" && python -m pytest tests/test_agent_tools.py -v`
Expected: 3 PASSED

- [ ] **Step 6: Commit**

```bash
cd "C:\claude proj\el_fager"
git add core/brain.py tests/test_agent_tools.py
git commit -m "feat: add 6 specialist-agent tool schemas to chat() tool loop"
```

---

## Task 2: Wire the 6 new tools into `_dispatch_tool`

**Files:**
- Modify: `core/brain.py:6094-6097` (`_dispatch_tool` tail)
- Test: `tests/test_agent_tools.py` (append)

**Interfaces:**
- Consumes: tool names from Task 1 (`screen_agent`, `browser_agent`, `stocks_agent`, `research_agent`, `file_agent`, `health_agent`); `BaseAgent.run(self, task: str) -> str` from each of `core.agents.screen_agent.ScreenAgent`, `core.agents.browser_agent.BrowserAgent`, `core.agents.stocks_agent.StocksAgent`, `core.agents.research_agent.ResearchAgent`, `core.agents.file_agent.FileAgent`, `core.agents.health_agent.HealthAgent`.
- Produces: `Brain._dispatch_tool(name: str, tool_input: dict) -> str` now handles all 6 agent tool names.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_agent_tools.py`:

```python
from unittest.mock import patch
from core.brain import Brain


def _make_brain():
    return Brain(profile={})


def test_dispatch_routes_to_screen_agent():
    brain = _make_brain()
    with patch("core.agents.screen_agent.ScreenAgent.run", return_value="ok"):
        assert brain._dispatch_tool("screen_agent", {"task": "click x"}) == "ok"


def test_dispatch_routes_to_browser_agent():
    brain = _make_brain()
    with patch("core.agents.browser_agent.BrowserAgent.run", return_value="ok"):
        assert brain._dispatch_tool("browser_agent", {"task": "book x"}) == "ok"


def test_dispatch_routes_to_stocks_agent():
    brain = _make_brain()
    with patch("core.agents.stocks_agent.StocksAgent.run", return_value="ok"):
        assert brain._dispatch_tool("stocks_agent", {"task": "analyze NVDA"}) == "ok"


def test_dispatch_routes_to_research_agent():
    brain = _make_brain()
    with patch("core.agents.research_agent.ResearchAgent.run", return_value="ok"):
        assert brain._dispatch_tool("research_agent", {"task": "research x"}) == "ok"


def test_dispatch_routes_to_file_agent():
    brain = _make_brain()
    with patch("core.agents.file_agent.FileAgent.run", return_value="ok"):
        assert brain._dispatch_tool("file_agent", {"task": "summarize x.pdf"}) == "ok"


def test_dispatch_routes_to_health_agent():
    brain = _make_brain()
    with patch("core.agents.health_agent.HealthAgent.run", return_value="ok"):
        assert brain._dispatch_tool("health_agent", {"task": "I ate rice"}) == "ok"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "C:\claude proj\el_fager" && python -m pytest tests/test_agent_tools.py -v -k dispatch`
Expected: 6 FAILED — `_dispatch_tool` currently returns `"Unknown tool: screen_agent"` etc. (no exception, just an `AssertionError` on the equality check).

- [ ] **Step 3: Add the 6 dispatch branches**

In `core/brain.py`, find the tail of `_dispatch_tool` (around line 6094):

```python
            else:
                return f"Unknown tool: {name}"
        except Exception as e:
            return f"Tool error ({name}): {e}"
```

Replace with:

```python
            elif name == "screen_agent":
                from core.agents.screen_agent import ScreenAgent
                return ScreenAgent().run(tool_input["task"])
            elif name == "browser_agent":
                from core.agents.browser_agent import BrowserAgent
                return BrowserAgent().run(tool_input["task"])
            elif name == "stocks_agent":
                from core.agents.stocks_agent import StocksAgent
                return StocksAgent().run(tool_input["task"])
            elif name == "research_agent":
                from core.agents.research_agent import ResearchAgent
                return ResearchAgent().run(tool_input["task"])
            elif name == "file_agent":
                from core.agents.file_agent import FileAgent
                return FileAgent().run(tool_input["task"])
            elif name == "health_agent":
                from core.agents.health_agent import HealthAgent
                return HealthAgent().run(tool_input["task"])
            else:
                return f"Unknown tool: {name}"
        except Exception as e:
            return f"Tool error ({name}): {e}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "C:\claude proj\el_fager" && python -m pytest tests/test_agent_tools.py -v`
Expected: 9 PASSED (3 from Task 1 + 6 from this task)

- [ ] **Step 5: Commit**

```bash
cd "C:\claude proj\el_fager"
git add core/brain.py tests/test_agent_tools.py
git commit -m "feat: wire 6 specialist-agent tools into _dispatch_tool"
```

---

## Task 3: Shrink `_try_agent_dispatch` to the 3 financial-safety branches

**Files:**
- Modify: `core/brain.py:6099-6152` (`_try_agent_dispatch`)
- Modify: `tests/test_brain_routing.py` (rewrite 3 existing tests, add 2 new ones)

**Interfaces:**
- Consumes: tool names and `_dispatch_tool` routing from Tasks 1-2.
- Produces: `Brain._try_agent_dispatch(task: str) -> str | None` now returns `None` for any message that isn't `gate_check`/`confirm_live`/`cancel_live` intent (including all 6 former specialist-agent intents), letting `chat()` proceed into the tool loop where the new agent tools are reachable.

- [ ] **Step 1: Write the failing/rewritten tests**

Replace the full contents of `tests/test_brain_routing.py` with:

```python
from unittest.mock import MagicMock, patch


def _make_brain():
    from core.brain import Brain
    return Brain(profile={})


def _tool_use_response(tool_name: str, tool_input: dict, tool_id: str = "tool_1"):
    block = MagicMock()
    block.type = "tool_use"
    block.name = tool_name
    block.input = tool_input
    block.id = tool_id
    response = MagicMock()
    response.stop_reason = "tool_use"
    response.content = [block]
    return response


def _end_turn_response(text: str):
    block = MagicMock()
    block.type = "text"
    block.text = text
    response = MagicMock()
    response.stop_reason = "end_turn"
    response.content = [block]
    return response


def test_screen_task_routes_to_screen_agent():
    brain = _make_brain()
    responses = [
        _tool_use_response("screen_agent", {"task": "click the submit button"}),
        _end_turn_response("Clicked the button."),
    ]
    with patch.object(brain.client.messages, "create", side_effect=responses), \
         patch("core.agents.screen_agent.ScreenAgent.run", return_value="Button clicked."):
        result = brain.chat("click the submit button")
    assert result == "Clicked the button."


def test_browser_task_routes_to_browser_agent():
    brain = _make_brain()
    responses = [
        _tool_use_response("browser_agent", {"task": "book a table at Cairo Kitchen"}),
        _end_turn_response("Booked the table."),
    ]
    with patch.object(brain.client.messages, "create", side_effect=responses), \
         patch("core.agents.browser_agent.BrowserAgent.run", return_value="Table booked."):
        result = brain.chat("book a table at Cairo Kitchen")
    assert result == "Booked the table."


def test_research_task_routes_to_research_agent():
    brain = _make_brain()
    responses = [
        _tool_use_response("research_agent", {"task": "research everything about Egypt"}),
        _end_turn_response("Research answer."),
    ]
    with patch.object(brain.client.messages, "create", side_effect=responses), \
         patch("core.agents.research_agent.ResearchAgent.run", return_value="Egypt research data."):
        result = brain.chat("research everything about Egypt")
    assert result == "Research answer."


def test_instant_task_bypasses_agents():
    brain = _make_brain()
    with patch.object(brain.client.messages, "create", return_value=_end_turn_response("Sunny in Cairo.")):
        result = brain.chat("what is the weather?")
    assert result == "Sunny in Cairo."


def test_specialist_keywords_no_longer_intercepted_before_tool_loop():
    brain = _make_brain()
    with patch("core.agents.screen_agent.ScreenAgent.run", return_value="x"), \
         patch("core.agents.browser_agent.BrowserAgent.run", return_value="x"), \
         patch("core.agents.stocks_agent.StocksAgent.run", return_value="x"), \
         patch("core.agents.research_agent.ResearchAgent.run", return_value="x"), \
         patch("core.agents.file_agent.FileAgent.run", return_value="x"), \
         patch("core.agents.health_agent.HealthAgent.run", return_value="x"):
        assert brain._try_agent_dispatch("click the submit button") is None
        assert brain._try_agent_dispatch("book a table at Cairo Kitchen") is None
        assert brain._try_agent_dispatch("analyze NVDA for me") is None
        assert brain._try_agent_dispatch("research everything about Egypt") is None
        assert brain._try_agent_dispatch("summarize this pdf") is None
        assert brain._try_agent_dispatch("I just ate chicken and rice") is None


def test_gate_check_still_intercepted_before_tool_loop():
    brain = _make_brain()
    with patch("core.trade_tracker.TradeTracker.sync", return_value=None), \
         patch("core.paper_metrics.PaperMetrics.gate_summary", return_value="Gate status: not ready"):
        result = brain._try_agent_dispatch("am i ready to go live")
    assert result == "Gate status: not ready"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "C:\claude proj\el_fager" && python -m pytest tests/test_brain_routing.py -v`
Expected: `test_screen_task_routes_to_screen_agent`, `test_browser_task_routes_to_browser_agent`, `test_research_task_routes_to_research_agent`, and `test_specialist_keywords_no_longer_intercepted_before_tool_loop` FAIL (current `_try_agent_dispatch` still has the pre-loop branches, so `ScreenAgent.run` etc. get called directly and the mocked `client.messages.create` side_effect is never consumed — text mismatches and non-`None` returns). `test_instant_task_bypasses_agents` and `test_gate_check_still_intercepted_before_tool_loop` PASS already (unaffected by the change).

- [ ] **Step 3: Shrink `_try_agent_dispatch`**

In `core/brain.py`, replace the full body of `_try_agent_dispatch` (lines 6099-6152):

```python
    def _try_agent_dispatch(self, task: str) -> str | None:
        """Route complex tasks to a specialist agent. Returns None for instant-lane tasks."""
        from core.agents.router import classify_intent
        intent = classify_intent(task)
        if intent == "screen":
            from core.agents.screen_agent import ScreenAgent
            return ScreenAgent().run(task)
        if intent == "browser":
            from core.agents.browser_agent import BrowserAgent
            return BrowserAgent().run(task)
        if intent == "stocks_agent":
            from core.agents.stocks_agent import StocksAgent
            return StocksAgent().run(task)
        if intent == "research":
            from core.agents.research_agent import ResearchAgent
            return ResearchAgent().run(task)
        if intent == "file":
            from core.agents.file_agent import FileAgent
            return FileAgent().run(task)
        if intent == "health":
            from core.agents.health_agent import HealthAgent
            return HealthAgent().run(task)
        if intent == "gate_check":
            from core.trade_tracker import TradeTracker
            from core.paper_metrics import PaperMetrics
            TradeTracker().sync()
            return PaperMetrics().gate_summary()
        if intent == "confirm_live":
            import time as _time
            if not self._live_pending:
                self._live_pending = True
                self._live_pending_ts = _time.monotonic()
                return (
                    "CAUTION: You are about to switch to REAL money trading. "
                    "Say 'confirm live trading' again within 60 seconds to activate. "
                    "Say 'cancel live trading' to abort."
                )
            elapsed = _time.monotonic() - self._live_pending_ts
            self._live_pending = False
            self._live_pending_ts = 0.0
            if elapsed > 60.0:
                return (
                    "Live trading activation timed out. "
                    "Say 'confirm live trading' to start over."
                )
            from core.paper_metrics import PaperMetrics
            if not PaperMetrics().compute()["gate_pass"]:
                return PaperMetrics().gate_summary()
            return _write_live_config(_LIVE_CONFIG_PATH)
        if intent == "cancel_live":
            self._live_pending = False
            self._live_pending_ts = 0.0
            return "Live trading activation cancelled."
        return None
```

with:

```python
    def _try_agent_dispatch(self, task: str) -> str | None:
        """Intercept financial-safety state-machine commands before the tool loop.

        Specialist agents (screen/browser/stocks/research/file/health) are
        reachable as tools inside the main chat() loop instead -- see the
        screen_agent/browser_agent/stocks_agent/research_agent/file_agent/
        health_agent tool definitions in TOOLS. Only the live-trading
        confirmation flow stays here: it's a deterministic 60-second
        confirmation window that must not be left to LLM tool-use judgment.
        """
        from core.agents.router import classify_intent
        intent = classify_intent(task)
        if intent == "gate_check":
            from core.trade_tracker import TradeTracker
            from core.paper_metrics import PaperMetrics
            TradeTracker().sync()
            return PaperMetrics().gate_summary()
        if intent == "confirm_live":
            import time as _time
            if not self._live_pending:
                self._live_pending = True
                self._live_pending_ts = _time.monotonic()
                return (
                    "CAUTION: You are about to switch to REAL money trading. "
                    "Say 'confirm live trading' again within 60 seconds to activate. "
                    "Say 'cancel live trading' to abort."
                )
            elapsed = _time.monotonic() - self._live_pending_ts
            self._live_pending = False
            self._live_pending_ts = 0.0
            if elapsed > 60.0:
                return (
                    "Live trading activation timed out. "
                    "Say 'confirm live trading' to start over."
                )
            from core.paper_metrics import PaperMetrics
            if not PaperMetrics().compute()["gate_pass"]:
                return PaperMetrics().gate_summary()
            return _write_live_config(_LIVE_CONFIG_PATH)
        if intent == "cancel_live":
            self._live_pending = False
            self._live_pending_ts = 0.0
            return "Live trading activation cancelled."
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "C:\claude proj\el_fager" && python -m pytest tests/test_brain_routing.py -v`
Expected: 6 PASSED

- [ ] **Step 5: Commit**

```bash
cd "C:\claude proj\el_fager"
git add core/brain.py tests/test_brain_routing.py
git commit -m "refactor: shrink _try_agent_dispatch to financial-safety branches only"
```

---

## Task 4: Add the tool-loop iteration cap

**Files:**
- Modify: `core/brain.py` — add `_MAX_TOOL_ITERATIONS` constant and rewrite the `while True` loop in `chat()` (around line 6184)
- Test: `tests/test_brain_routing.py` (append)

**Interfaces:**
- Produces: module-level constant `_MAX_TOOL_ITERATIONS = 15` in `core/brain.py`. `Brain.chat()` now terminates after at most 15 `client.messages.create()` calls, returning the last seen assistant text (if any) plus a `"[stopped after 15 steps -- let me know if you want me to continue]"` suffix instead of looping forever.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_brain_routing.py`:

```python
def test_chat_loop_stops_after_max_iterations():
    brain = _make_brain()
    responses = [_tool_use_response("noop_tool", {})] * 20
    with patch.object(brain.client.messages, "create", side_effect=responses) as mock_create:
        result = brain.chat("loop forever")
    assert "stopped after" in result.lower()
    assert mock_create.call_count == 15
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "C:\claude proj\el_fager" && python -m pytest tests/test_brain_routing.py -v -k max_iterations`
Expected: FAILED — the mocked `side_effect` list has only 20 entries, the current unbounded `while True` loop consumes all 20 and then raises `StopIteration` (uncaught), failing the test with that error rather than hanging indefinitely.

- [ ] **Step 3: Add the constant and rewrite the loop**

In `core/brain.py`, add the constant directly above `class Brain:` (around line 4728):

```python
_MAX_TOOL_ITERATIONS = 15


class Brain:
```

Then in `chat()`, replace this block:

```python
        self.conversation_history.append({"role": "user", "content": user_message})
        messages = list(self.conversation_history)

        tools_used: list[str] = []

        try:
            while True:
                response = self.client.messages.create(
                    model=self._model,
                    max_tokens=1024,
                    system=system,
                    tools=_select_tools(user_message),
                    messages=messages,
                )
                self._offline_mode = False

                if response.stop_reason == "end_turn":
                    text = next(
                        (block.text for block in response.content if hasattr(block, "text")),
                        "",
                    )
                    self.conversation_history.append({"role": "assistant", "content": text})
                    if self._logger:
                        self._logger.log("assistant", text, tools_used)
                    return text

                elif response.stop_reason == "tool_use":
                    messages.append({"role": "assistant", "content": response.content})

                    tool_results = []
                    for block in response.content:
                        if block.type == "tool_use":
                            tools_used.append(block.name)
                            result_str = self._dispatch_tool(block.name, block.input)
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": result_str,
                            })

                    messages.append({"role": "user", "content": tool_results})

                else:
                    return "[Response cut off — please try again]"

        except anthropic.BadRequestError as e:
```

with:

```python
        self.conversation_history.append({"role": "user", "content": user_message})
        messages = list(self.conversation_history)

        tools_used: list[str] = []
        last_text = ""

        try:
            for _iteration in range(_MAX_TOOL_ITERATIONS):
                response = self.client.messages.create(
                    model=self._model,
                    max_tokens=1024,
                    system=system,
                    tools=_select_tools(user_message),
                    messages=messages,
                )
                self._offline_mode = False

                if response.stop_reason == "end_turn":
                    text = next(
                        (block.text for block in response.content if hasattr(block, "text")),
                        "",
                    )
                    self.conversation_history.append({"role": "assistant", "content": text})
                    if self._logger:
                        self._logger.log("assistant", text, tools_used)
                    return text

                elif response.stop_reason == "tool_use":
                    messages.append({"role": "assistant", "content": response.content})
                    last_text = next(
                        (block.text for block in response.content if hasattr(block, "text")),
                        last_text,
                    )

                    tool_results = []
                    for block in response.content:
                        if block.type == "tool_use":
                            tools_used.append(block.name)
                            result_str = self._dispatch_tool(block.name, block.input)
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": result_str,
                            })

                    messages.append({"role": "user", "content": tool_results})

                else:
                    return "[Response cut off — please try again]"

            text = (
                (last_text + " " if last_text else "")
                + f"[stopped after {_MAX_TOOL_ITERATIONS} steps -- let me know if you want me to continue]"
            )
            self.conversation_history.append({"role": "assistant", "content": text})
            if self._logger:
                self._logger.log("assistant", text, tools_used)
            return text

        except anthropic.BadRequestError as e:
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "C:\claude proj\el_fager" && python -m pytest tests/test_brain_routing.py -v`
Expected: 7 PASSED

- [ ] **Step 5: Commit**

```bash
cd "C:\claude proj\el_fager"
git add core/brain.py tests/test_brain_routing.py
git commit -m "feat: cap chat() tool loop at 15 iterations to prevent runaway agent chains"
```

---

## Task 5: Cross-domain chaining test (end-to-end validation)

**Files:**
- Modify: `tests/test_brain_routing.py` (append)

**Interfaces:**
- Consumes: everything from Tasks 1-4 — this task adds no production code, only a test proving the feature works end-to-end.

- [ ] **Step 1: Write the test**

Append to `tests/test_brain_routing.py`:

```python
def test_chat_can_chain_agent_tool_then_instant_tool():
    brain = _make_brain()
    responses = [
        _tool_use_response("screen_agent", {"task": "what error is showing"}, tool_id="tool_1"),
        _tool_use_response("web_search", {"query": "fix permission denied error"}, tool_id="tool_2"),
        _end_turn_response("Found a fix and searched the web for it."),
    ]
    with patch.object(brain.client.messages, "create", side_effect=responses), \
         patch("core.agents.screen_agent.ScreenAgent.run", return_value="Permission denied error visible."), \
         patch("tools.web_tool.web_search", return_value="Fix: run as administrator."):
        result = brain.chat("check my screen error then search the web for a fix")
    assert result == "Found a fix and searched the web for it."
```

- [ ] **Step 2: Run test to verify it passes**

Run: `cd "C:\claude proj\el_fager" && python -m pytest tests/test_brain_routing.py -v -k chain`
Expected: PASSED — this should already pass given Tasks 1-4 are complete (it's a regression/integration check, not new behavior), confirming a `screen_agent` tool call followed by an instant `web_search` tool call both fire within one `chat()` turn.

- [ ] **Step 3: Run the full test suite**

Run: `cd "C:\claude proj\el_fager" && python -m pytest --tb=short -q`
Expected: all tests pass except the 7 pre-existing unrelated failures (6 in `tests/ui/test_overlay_modes.py` from a `QtWebEngineWidgets` import-order issue in the headless test runner, 1 in `tests/test_risk_manager.py::test_calc_position_size_fractional`) — both predate this plan and are out of scope.

- [ ] **Step 4: Commit**

```bash
cd "C:\claude proj\el_fager"
git add tests/test_brain_routing.py
git commit -m "test: add cross-domain agent-then-instant-tool chaining coverage"
```
