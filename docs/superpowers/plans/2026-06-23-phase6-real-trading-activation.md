# Phase 6: Real Trading Activation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire a voice-triggered double-confirmation flow that switches El Fager from paper to live Alpaca trading once the gate criteria are met.

**Architecture:** Two new router intents (`confirm_live`, `cancel_live`) feed a stateful handler in Brain that enforces: first-confirm → caution warning; second-confirm within 60 s → gate check → write `mode: live` to `data/trading_config.json`; any cancel → clear state. All state lives on the Brain instance (`_live_pending`, `_live_pending_ts`). A module-level constant `_LIVE_CONFIG_PATH` makes the config path monkeypatchable in tests.

**Tech Stack:** Python 3.14, pytest, existing `core/agents/router.py`, `core/brain.py`, `core/paper_metrics.py`

## Global Constraints

- cp1252 safety: NO U+2192 (→), NO emojis, NO Arabic in any string returned by `_try_agent_dispatch` or spoken by TTS. Em-dash `—` is safe.
- No new pip installs.
- TDD: write failing test first, then implement.
- YAGNI: no features beyond the spec (no Slack alerts, no email, no GUI changes).
- All existing 221 tests must continue to pass after each commit.
- `classify_intent` docstring must list `confirm_live` and `cancel_live` as possible return values after Task 1.

---

### Task 1: Router — `confirm_live` and `cancel_live` intents

**Files:**
- Modify: `core/agents/router.py`
- Modify: `tests/agents/test_router.py`

**Interfaces:**
- Produces: `classify_intent("confirm real trading") == "confirm_live"`, `classify_intent("cancel live trading") == "cancel_live"` — used by Task 2.

- [ ] **Step 1: Write the failing tests**

Append this class to `tests/agents/test_router.py`:

```python
class TestConfirmLiveRouting:
    def test_confirm_real_trading_routes_to_confirm_live(self):
        from core.agents.router import classify_intent
        assert classify_intent("confirm real trading") == "confirm_live"

    def test_confirm_live_trading_routes_to_confirm_live(self):
        from core.agents.router import classify_intent
        assert classify_intent("confirm live trading") == "confirm_live"

    def test_cancel_live_trading_routes_to_cancel_live(self):
        from core.agents.router import classify_intent
        assert classify_intent("cancel live trading") == "cancel_live"

    def test_cancel_real_trading_routes_to_cancel_live(self):
        from core.agents.router import classify_intent
        assert classify_intent("cancel real trading") == "cancel_live"

    def test_gate_check_still_routes_correctly(self):
        from core.agents.router import classify_intent
        assert classify_intent("am I ready for real trading?") == "gate_check"

    def test_activate_live_routes_to_confirm_live(self):
        from core.agents.router import classify_intent
        assert classify_intent("activate live trading") == "confirm_live"
```

- [ ] **Step 2: Run to verify they fail**

```
python -m pytest tests/agents/test_router.py::TestConfirmLiveRouting -v
```

Expected: 6 failures — `AssertionError` (returns `"instant"` or `"stocks"`)

- [ ] **Step 3: Add keyword lists and update `_LABEL_KEYWORDS` in `core/agents/router.py`**

Add these two keyword lists immediately after `_GATE_CHECK_KEYWORDS` (which ends around line 60):

```python
_CONFIRM_LIVE_KEYWORDS = [
    "confirm real trading",
    "confirm live trading",
    "activate real trading",
    "activate live trading",
    "go live with trading",
    "switch to real trading",
    "switch to live trading",
]

_CANCEL_LIVE_KEYWORDS = [
    "cancel live trading",
    "cancel real trading",
    "abort live trading",
    "stop live trading activation",
]
```

Update `_LABEL_KEYWORDS` to insert both before `gate_check`:

```python
_LABEL_KEYWORDS = [
    ("screen", _SCREEN_KEYWORDS),
    ("browser", _BROWSER_KEYWORDS),
    ("stocks_agent", _STOCKS_AGENT_KEYWORDS),  # checked before "stocks"
    ("confirm_live", _CONFIRM_LIVE_KEYWORDS),  # checked before gate_check and stocks
    ("cancel_live", _CANCEL_LIVE_KEYWORDS),    # checked before gate_check and stocks
    ("gate_check", _GATE_CHECK_KEYWORDS),      # checked before generic "stocks"
    ("stocks", _STOCKS_KEYWORDS),
    ("research", _RESEARCH_KEYWORDS),
    ("file", _FILE_KEYWORDS),
]
```

Also update the docstring of `classify_intent` to add `confirm_live` and `cancel_live` to the return value list:

```python
def classify_intent(message: str) -> str:
    """Return the agent label that should handle this message.

    Returns one of: 'screen', 'browser', 'stocks_agent', 'confirm_live',
    'cancel_live', 'gate_check', 'stocks', 'research', 'file', 'instant'.
    Uses keyword matching. First match wins.
    """
```

- [ ] **Step 4: Run tests to verify they pass**

```
python -m pytest tests/agents/test_router.py -v
```

Expected: All router tests pass (currently 31 + 6 new = 37 total).

- [ ] **Step 5: Run full suite to check no regressions**

```
python -m pytest --tb=short -q
```

Expected: 227 passed (221 + 6 new), 0 failures.

- [ ] **Step 6: Commit**

```
git add core/agents/router.py tests/agents/test_router.py
git commit -m "feat: add confirm_live and cancel_live intents to router"
```

---

### Task 2: Brain — double-confirmation state machine + live activation

**Files:**
- Modify: `core/brain.py` (module-level constant + helper function + `__init__` instance vars + `_try_agent_dispatch` handlers)
- Create: `tests/test_live_activation.py`

**Interfaces:**
- Consumes: `classify_intent` returning `"confirm_live"` or `"cancel_live"` (Task 1), `PaperMetrics().compute()["gate_pass"]` (Phase 5), `PaperMetrics().gate_summary()` (Phase 5)
- Produces: `Brain._try_agent_dispatch("confirm live trading")` — first call returns caution string; second call within 60 s returns activation or gate-summary string; `Brain._live_pending: bool`, `Brain._live_pending_ts: float`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_live_activation.py`:

```python
import json
import time
import pytest
from unittest.mock import MagicMock


@pytest.fixture
def brain(monkeypatch):
    monkeypatch.setattr("anthropic.Anthropic", MagicMock)
    from core.brain import Brain
    return Brain({})


class TestLiveActivationDispatch:
    def test_first_confirm_returns_caution_message(self, brain, monkeypatch, tmp_path):
        monkeypatch.setattr("core.brain._LIVE_CONFIG_PATH", str(tmp_path / "cfg.json"))
        result = brain._try_agent_dispatch("confirm live trading")
        assert "CAUTION" in result
        assert "again" in result.lower() or "confirm" in result.lower()

    def test_first_confirm_sets_pending_true(self, brain, monkeypatch, tmp_path):
        monkeypatch.setattr("core.brain._LIVE_CONFIG_PATH", str(tmp_path / "cfg.json"))
        brain._try_agent_dispatch("confirm live trading")
        assert brain._live_pending is True

    def test_cancel_clears_pending_state(self, brain, monkeypatch, tmp_path):
        monkeypatch.setattr("core.brain._LIVE_CONFIG_PATH", str(tmp_path / "cfg.json"))
        brain._try_agent_dispatch("confirm live trading")
        result = brain._try_agent_dispatch("cancel live trading")
        assert brain._live_pending is False
        assert "cancel" in result.lower()

    def test_cancel_when_not_pending_returns_safely(self, brain, monkeypatch, tmp_path):
        monkeypatch.setattr("core.brain._LIVE_CONFIG_PATH", str(tmp_path / "cfg.json"))
        result = brain._try_agent_dispatch("cancel live trading")
        assert isinstance(result, str)
        assert brain._live_pending is False

    def test_second_confirm_timeout_returns_timeout_message(self, brain, monkeypatch, tmp_path):
        monkeypatch.setattr("core.brain._LIVE_CONFIG_PATH", str(tmp_path / "cfg.json"))
        brain._try_agent_dispatch("confirm live trading")
        brain._live_pending_ts = time.monotonic() - 65.0  # backdate 65 s → timed out
        result = brain._try_agent_dispatch("confirm live trading")
        assert brain._live_pending is False
        assert "timed out" in result.lower() or "start over" in result.lower()

    def test_second_confirm_gate_not_passed_returns_gate_summary(self, brain, monkeypatch, tmp_path):
        monkeypatch.setattr("core.brain._LIVE_CONFIG_PATH", str(tmp_path / "cfg.json"))
        monkeypatch.setattr(
            "core.paper_metrics.PaperMetrics.compute",
            lambda self: {
                "total_completed": 5, "win_rate": 40.0, "sharpe": 0.2,
                "max_drawdown": 25.0, "profit_factor": 0.7, "gate_pass": False,
            },
        )
        monkeypatch.setattr("core.paper_metrics._TRADES_PATH", tmp_path / "none.json")
        brain._try_agent_dispatch("confirm live trading")
        result = brain._try_agent_dispatch("confirm live trading")
        assert "NOT YET" in result or "Paper trading gate check" in result
        assert brain._live_pending is False

    def test_second_confirm_gate_passes_writes_live_mode_to_config(self, brain, monkeypatch, tmp_path):
        cfg_path = tmp_path / "trading_config.json"
        monkeypatch.setattr("core.brain._LIVE_CONFIG_PATH", str(cfg_path))
        monkeypatch.setattr(
            "core.paper_metrics.PaperMetrics.compute",
            lambda self: {
                "total_completed": 35, "win_rate": 60.0, "sharpe": 1.5,
                "max_drawdown": 10.0, "profit_factor": 1.8, "gate_pass": True,
            },
        )
        brain._try_agent_dispatch("confirm live trading")
        brain._try_agent_dispatch("confirm live trading")
        written = json.loads(cfg_path.read_text())
        assert written["mode"] == "live"

    def test_second_confirm_gate_passes_returns_activation_message(self, brain, monkeypatch, tmp_path):
        cfg_path = tmp_path / "trading_config.json"
        monkeypatch.setattr("core.brain._LIVE_CONFIG_PATH", str(cfg_path))
        monkeypatch.setattr(
            "core.paper_metrics.PaperMetrics.compute",
            lambda self: {
                "total_completed": 35, "win_rate": 60.0, "sharpe": 1.5,
                "max_drawdown": 10.0, "profit_factor": 1.8, "gate_pass": True,
            },
        )
        brain._try_agent_dispatch("confirm live trading")
        result = brain._try_agent_dispatch("confirm live trading")
        assert "LIVE TRADING ACTIVATED" in result
        assert brain._live_pending is False

    def test_activation_message_is_cp1252_safe(self, brain, monkeypatch, tmp_path):
        cfg_path = tmp_path / "trading_config.json"
        monkeypatch.setattr("core.brain._LIVE_CONFIG_PATH", str(cfg_path))
        monkeypatch.setattr(
            "core.paper_metrics.PaperMetrics.compute",
            lambda self: {
                "total_completed": 35, "win_rate": 60.0, "sharpe": 1.5,
                "max_drawdown": 10.0, "profit_factor": 1.8, "gate_pass": True,
            },
        )
        brain._try_agent_dispatch("confirm live trading")
        result = brain._try_agent_dispatch("confirm live trading")
        for ch in result:
            assert ord(ch) < 0x2000 or 0x2013 <= ord(ch) <= 0x2014, \
                f"Non-cp1252 char U+{ord(ch):04X} in activation message"
```

- [ ] **Step 2: Run to verify they fail**

```
python -m pytest tests/test_live_activation.py -v
```

Expected: All 9 tests fail — `AttributeError: 'Brain' object has no attribute '_live_pending'` or similar.

- [ ] **Step 3: Add module-level constant and helper to `core/brain.py`**

Find the line `class Brain:` (currently L4599). Insert the following **immediately before** that line (i.e., after the blank line at L4598):

```python
_LIVE_CONFIG_PATH = "data/trading_config.json"


def _write_live_config(config_path: str) -> str:
    """Write mode: live to trading_config.json. Returns cp1252-safe confirmation."""
    import json
    from pathlib import Path
    p = Path(config_path)
    cfg: dict = {}
    if p.exists():
        try:
            cfg = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    cfg["mode"] = "live"
    p.parent.mkdir(exist_ok=True)
    p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    return (
        "LIVE TRADING ACTIVATED. El Fager will now trade with real money. "
        "Say 'pause trading' at any time to halt all autonomous trading."
    )


```

- [ ] **Step 4: Add instance variables to `Brain.__init__`**

In `Brain.__init__` (L4600), after the line `self._logger = None` (inside the `except Exception:` block), add:

```python
        self._live_pending: bool = False
        self._live_pending_ts: float = 0.0
```

The `__init__` block should look like this after the edit:

```python
    def __init__(self, profile: dict, memory=None):
        self.client = anthropic.Anthropic()
        self.profile = profile
        self.memory = memory
        self.conversation_history: list[dict] = []
        self._offline_mode = False
        try:
            _sf = "data/settings.json"
            _s = json.loads(open(_sf, encoding="utf-8").read()) if os.path.exists(_sf) else {}
            self._model: str = _s.get("model", "claude-sonnet-4-6")
        except Exception:
            self._model = "claude-sonnet-4-6"
        try:
            from core.conversation_log import ConversationLogger
            self._logger = ConversationLogger()
        except Exception:
            self._logger = None
        self._live_pending: bool = False
        self._live_pending_ts: float = 0.0
```

- [ ] **Step 5: Add `confirm_live` and `cancel_live` handlers in `_try_agent_dispatch`**

In `_try_agent_dispatch` (L5953), find the existing `gate_check` handler followed by `return None`. Add the two new handlers immediately after the `gate_check` block, before `return None`:

```python
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
```

The full `_try_agent_dispatch` after the edit should be:

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

- [ ] **Step 6: Run the new tests**

```
python -m pytest tests/test_live_activation.py -v
```

Expected: All 9 tests pass.

- [ ] **Step 7: Run full suite to check no regressions**

```
python -m pytest --tb=short -q
```

Expected: 236 passed (221 + 6 from Task 1 + 9 new), 0 failures.

- [ ] **Step 8: Commit**

```
git add core/brain.py tests/test_live_activation.py
git commit -m "feat: add double-confirmation live trading activation to Brain"
```

---

## Self-Review

**Spec coverage:**
- First confirm → caution warning: Task 2, step 5 ✓
- Second confirm within 60 s → gate check: Task 2, step 5 ✓
- Gate not passed → returns gate summary: Task 2, step 5 ✓
- Gate passed → writes `mode: live` to `trading_config.json`: Task 2, steps 3 + 5 ✓
- Timeout → message + state cleared: Task 2, step 5 ✓
- "cancel live trading" → clears state: Task 2, step 5 ✓
- cp1252 safety of all returned strings: Task 2, test `test_activation_message_is_cp1252_safe` ✓
- Router: `confirm_live` and `cancel_live` intents: Task 1 ✓
- `classify_intent` docstring updated: Task 1, step 3 ✓

**Placeholder scan:** No TBDs, no "handle edge cases", all code blocks complete. ✓

**Type consistency:** `_LIVE_CONFIG_PATH` is `str` throughout — `_write_live_config` accepts `str`, `monkeypatch.setattr` patches `str`, `Path(config_path)` accepts `str`. ✓
