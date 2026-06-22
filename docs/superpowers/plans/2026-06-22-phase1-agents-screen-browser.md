# Phase 1: Agent Infrastructure + ScreenAgent + BrowserAgent

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the agent infrastructure layer to El Fager — a two-lane orchestrator that routes complex multi-step tasks to specialist agents (ScreenAgent for desktop control, BrowserAgent for web automation) while leaving the existing 355-tool instant lane completely unchanged.

**Architecture:** A keyword-based router (`core/agents/router.py`) classifies intent with zero API cost (same pattern as the existing `_select_tools` function). `Brain.chat()` calls `_try_agent_dispatch()` at the very top — if it returns a result, that is returned immediately; otherwise the existing tool loop runs unchanged. Both agents use a vision-action loop: take screenshot → ask Claude Vision what to do → execute → repeat until done.

**Tech Stack:** `pyautogui` (mouse/keyboard), `mss` (screenshots), `Pillow` (image processing), `playwright` (browser), `cryptography`/Fernet (credential vault), Claude Vision API (screen understanding) — all already installed.

## Global Constraints

- Python 3.14 — use `pygame-ce` not `pygame` (not relevant here but noted)
- cp1252 safety: no Unicode arrows, emojis, or Arabic in tool return strings — em-dash is safe
- `pyautogui.FAILSAFE = True` must remain on — moving mouse to top-left aborts automation
- Never enter financial credentials automatically — BrowserAgent must check vault, never hardcode
- ScreenAgent and BrowserAgent max steps: 10 and 20 respectively — no infinite loops
- All new files under `core/agents/` and tested under `tests/agents/`
- Do NOT modify `_select_tools`, `SYSTEM_PROMPT`, or `TOOLS` list in brain.py
- The existing `chat()` tool loop (lines 5975–6049) must be left byte-for-byte identical

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Create | `core/agents/__init__.py` | Package marker |
| Create | `core/agents/base_agent.py` | `BaseAgent` abstract class |
| Create | `core/agents/router.py` | `classify_intent(message)` → label |
| Create | `core/vault.py` | `Vault` — Fernet-encrypted credential store |
| Create | `core/agents/screen_agent.py` | `ScreenAgent` — vision-action loop over desktop |
| Create | `core/agents/browser_agent.py` | `BrowserAgent` — vision-action loop in Playwright |
| Modify | `core/brain.py` | Add `_try_agent_dispatch()` method + call in `chat()` |
| Create | `tests/agents/__init__.py` | Package marker |
| Create | `tests/agents/test_router.py` | Router unit tests |
| Create | `tests/test_vault.py` | Vault unit tests |
| Create | `tests/agents/test_screen_agent.py` | ScreenAgent unit tests (mocked) |
| Create | `tests/agents/test_browser_agent.py` | BrowserAgent unit tests (mocked) |
| Create | `tests/test_brain_routing.py` | Brain routing integration tests |

---

## Task 1: BaseAgent + Router

**Files:**
- Create: `core/agents/__init__.py`
- Create: `core/agents/base_agent.py`
- Create: `core/agents/router.py`
- Create: `tests/agents/__init__.py`
- Create: `tests/agents/test_router.py`

**Interfaces:**
- Produces: `BaseAgent` (abstract class with `name: str`, `description: str`, `run(task: str) -> str`)
- Produces: `classify_intent(message: str) -> str` — returns one of `"screen" | "browser" | "stocks" | "research" | "file" | "instant"`

---

- [ ] **Step 1: Write the failing router tests**

```python
# tests/agents/__init__.py
# (empty)
```

```python
# tests/agents/test_router.py
from core.agents.router import classify_intent

def test_screen_click():
    assert classify_intent("click the submit button") == "screen"

def test_screen_drag():
    assert classify_intent("drag the file to the folder") == "screen"

def test_browser_book():
    assert classify_intent("book me a table at Cairo Kitchen") == "browser"

def test_browser_login():
    assert classify_intent("log into my university portal and check my grades") == "browser"

def test_stocks_keyword():
    assert classify_intent("what's the stock price of NVDA?") == "stocks"

def test_research_keyword():
    assert classify_intent("research everything about Egypt's economy this week") == "research"

def test_file_pdf():
    assert classify_intent("summarize this pdf for me") == "file"

def test_instant_weather():
    assert classify_intent("what is the weather in Cairo?") == "instant"

def test_instant_music():
    assert classify_intent("play something on Spotify") == "instant"

def test_case_insensitive():
    assert classify_intent("CLICK the button") == "screen"
```

- [ ] **Step 2: Run tests to confirm they fail**

```
cd "C:\claude proj\el_fager"
python -m pytest tests/agents/test_router.py -v
```

Expected: `ModuleNotFoundError: No module named 'core.agents.router'`

- [ ] **Step 3: Create package markers**

```python
# core/agents/__init__.py
# (empty file)
```

- [ ] **Step 4: Write BaseAgent**

```python
# core/agents/base_agent.py
from abc import ABC, abstractmethod

class BaseAgent(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """Agent identifier, e.g. 'screen'"""

    @property
    @abstractmethod
    def description(self) -> str:
        """One-line description of what this agent handles."""

    @abstractmethod
    def run(self, task: str) -> str:
        """Execute the task and return a plain-text result."""
```

- [ ] **Step 5: Write the router**

```python
# core/agents/router.py

# Keywords that map to each agent.
# Priority: first match wins — order of checks in classify_intent matters.
_SCREEN_KEYWORDS = [
    "click", "double click", "right click", "scroll up", "scroll down",
    "type in", "press enter", "press tab", "press escape", "drag",
    "hotkey", "what's on my screen", "look at my screen",
    "open and then", "control the app", "automate the", "desktop app",
    "take a screenshot", "what do you see", "describe the screen",
    "what error is showing", "what's open",
]

_BROWSER_KEYWORDS = [
    "website", "webpage", "navigate to", "go to http", "go to www",
    "book a table", "book me a", "book a flight", "search flights",
    "log into", "login to", "log in to", "sign in to",
    "fill out", "fill in", "submit the form",
    "university portal", "online portal", "bank account", "check my bank",
    "open browser", "browse to", ".com", ".org", ".net", ".eg",
    "search on google", "search on amazon",
]

_STOCKS_KEYWORDS = [
    "stock", "stocks", "trade", "trading", "portfolio", "ticker",
    "buy shares", "sell shares", "invest", "investing", "investment",
    "trading engine", "trading agent", "open positions", "trade history",
    "bull", "bear", "bullish", "bearish", "earnings", "dividend",
    "p/e ratio", "rsi", "macd", "moving average",
    "NVDA", "AAPL", "MSFT", "AMZN", "GOOGL", "META", "TSLA",
    "SPY", "QQQ", "BTC", "ETH", "crypto",
]

_RESEARCH_KEYWORDS = [
    "research everything", "deep dive into", "find out everything about",
    "investigate", "comprehensive analysis of", "tell me everything about",
    "summarize the news about", "latest news about",
    "everything happening with", "what do we know about",
    "research the best", "compare and contrast",
]

_FILE_KEYWORDS = [
    ".pdf", ".docx", ".xlsx", ".doc", ".pptx",
    "this pdf", "this document", "this file", "this contract",
    "read this pdf", "summarize this pdf", "summarize this document",
    "what does this file say", "extract from this",
    "this invoice", "this thesis", "this report", "this spreadsheet",
    "payment terms", "what did this contract",
]

_LABEL_KEYWORDS = [
    ("screen", _SCREEN_KEYWORDS),
    ("browser", _BROWSER_KEYWORDS),
    ("stocks", _STOCKS_KEYWORDS),
    ("research", _RESEARCH_KEYWORDS),
    ("file", _FILE_KEYWORDS),
]


def classify_intent(message: str) -> str:
    """Return the agent label that should handle this message.

    Returns one of: 'screen', 'browser', 'stocks', 'research', 'file', 'instant'.
    Uses keyword matching — same approach as _select_tools in brain.py.
    First match wins; falls back to 'instant' if nothing matches.
    """
    msg = message.lower()
    for label, keywords in _LABEL_KEYWORDS:
        if any(kw in msg for kw in keywords):
            return label
    return "instant"
```

- [ ] **Step 6: Run tests to confirm they pass**

```
python -m pytest tests/agents/test_router.py -v
```

Expected: all 10 tests PASS

- [ ] **Step 7: Commit**

```
git add core/agents/__init__.py core/agents/base_agent.py core/agents/router.py tests/agents/__init__.py tests/agents/test_router.py
git commit -m "feat: add agent infrastructure — BaseAgent, intent router"
```

---

## Task 2: Vault (Encrypted Credential Store)

**Files:**
- Create: `core/vault.py`
- Create: `tests/test_vault.py`

**Interfaces:**
- Produces: `Vault(vault_path, key_path)` with `.get(service) -> dict | None`, `.set(service, credentials)`, `.delete(service)`, `.list_services() -> list[str]`
- Consumed by: `BrowserAgent` (Task 4)

---

- [ ] **Step 1: Write the failing vault tests**

```python
# tests/test_vault.py
import pytest
from core.vault import Vault

@pytest.fixture
def vault(tmp_path):
    return Vault(
        vault_path=str(tmp_path / "vault.enc"),
        key_path=str(tmp_path / "vault.key"),
    )

def test_set_and_get(vault):
    vault.set("google", {"email": "mo@gmail.com", "password": "secret"})
    assert vault.get("google") == {"email": "mo@gmail.com", "password": "secret"}

def test_get_missing_returns_none(vault):
    assert vault.get("nonexistent") is None

def test_delete_removes_entry(vault):
    vault.set("twitter", {"token": "abc"})
    vault.delete("twitter")
    assert vault.get("twitter") is None

def test_delete_nonexistent_is_safe(vault):
    vault.delete("never_set")  # should not raise

def test_list_services(vault):
    vault.set("a", {"x": 1})
    vault.set("b", {"y": 2})
    assert set(vault.list_services()) == {"a", "b"}

def test_update_overwrites(vault):
    vault.set("svc", {"token": "old"})
    vault.set("svc", {"token": "new"})
    assert vault.get("svc") == {"token": "new"}

def test_data_is_encrypted_on_disk(vault):
    vault.set("test", {"secret": "my_password"})
    with open(vault._vault_path, "rb") as f:
        raw = f.read()
    assert b"secret" not in raw
    assert b"my_password" not in raw

def test_key_persists_across_instances(vault):
    vault.set("svc", {"token": "abc"})
    vault2 = Vault(vault_path=vault._vault_path, key_path=vault._key_path)
    assert vault2.get("svc") == {"token": "abc"}
```

- [ ] **Step 2: Run tests to confirm they fail**

```
python -m pytest tests/test_vault.py -v
```

Expected: `ModuleNotFoundError: No module named 'core.vault'`

- [ ] **Step 3: Write the Vault class**

```python
# core/vault.py
import json
import os
from cryptography.fernet import Fernet

_DEFAULT_VAULT = os.path.join("data", "vault.enc")
_DEFAULT_KEY = os.path.join("data", "vault.key")


class Vault:
    """Fernet-encrypted key-value store for service credentials.

    Stored locally at data/vault.enc — never sent to any API.
    """

    def __init__(self, vault_path: str = _DEFAULT_VAULT, key_path: str = _DEFAULT_KEY):
        self._vault_path = vault_path
        self._key_path = key_path
        self._fernet = Fernet(self._load_or_create_key())

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def get(self, service: str) -> dict | None:
        """Return credentials dict for service, or None if not stored."""
        return self._load().get(service)

    def set(self, service: str, credentials: dict) -> None:
        """Store (or overwrite) credentials for service."""
        data = self._load()
        data[service] = credentials
        self._save(data)

    def delete(self, service: str) -> None:
        """Remove credentials for service. No-op if not present."""
        data = self._load()
        if service in data:
            data.pop(service)
            self._save(data)

    def list_services(self) -> list[str]:
        """Return names of all stored services."""
        return list(self._load().keys())

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _load_or_create_key(self) -> bytes:
        if os.path.exists(self._key_path):
            with open(self._key_path, "rb") as f:
                return f.read()
        os.makedirs(os.path.dirname(self._key_path) or ".", exist_ok=True)
        key = Fernet.generate_key()
        with open(self._key_path, "wb") as f:
            f.write(key)
        return key

    def _load(self) -> dict:
        if not os.path.exists(self._vault_path):
            return {}
        with open(self._vault_path, "rb") as f:
            return json.loads(self._fernet.decrypt(f.read()))

    def _save(self, data: dict) -> None:
        os.makedirs(os.path.dirname(self._vault_path) or ".", exist_ok=True)
        with open(self._vault_path, "wb") as f:
            f.write(self._fernet.encrypt(json.dumps(data).encode()))
```

- [ ] **Step 4: Run tests to confirm they pass**

```
python -m pytest tests/test_vault.py -v
```

Expected: all 8 tests PASS

- [ ] **Step 5: Commit**

```
git add core/vault.py tests/test_vault.py
git commit -m "feat: add Fernet-encrypted vault for BrowserAgent credentials"
```

---

## Task 3: ScreenAgent

**Files:**
- Create: `core/agents/screen_agent.py`
- Create: `tests/agents/test_screen_agent.py`

**Interfaces:**
- Consumes: `BaseAgent` from `core/agents/base_agent.py`
- Produces: `ScreenAgent` with `.run(task: str) -> str`
- Consumed by: `Brain._try_agent_dispatch` (Task 5)

---

- [ ] **Step 1: Write the failing ScreenAgent tests**

```python
# tests/agents/test_screen_agent.py
import json
from unittest.mock import MagicMock, patch
from core.agents.screen_agent import ScreenAgent


def _done_response(message: str = "Task complete.") -> dict:
    return {"status": "done", "message": message, "action": {"type": "none"}}


def _continue_response(action: dict, message: str = "Working...") -> dict:
    return {"status": "continue", "message": message, "action": action}


def test_run_returns_done_message_immediately():
    agent = ScreenAgent()
    done = _done_response("Clicked the button.")

    with patch.object(agent, "_capture", return_value="fakeb64"), \
         patch.object(agent, "_get_action", return_value=done), \
         patch.object(agent, "_execute") as mock_exec, \
         patch("time.sleep"):
        result = agent.run("click the submit button")

    assert result == "Clicked the button."
    mock_exec.assert_not_called()


def test_run_executes_one_click_then_done():
    agent = ScreenAgent()
    click = _continue_response({"type": "click", "x": 100, "y": 200}, "Clicking submit")
    done = _done_response("Done.")

    with patch.object(agent, "_capture", return_value="fakeb64"), \
         patch.object(agent, "_get_action", side_effect=[click, done]), \
         patch.object(agent, "_execute") as mock_exec, \
         patch("time.sleep"):
        result = agent.run("click submit")

    assert mock_exec.call_count == 1
    assert result == "Done."


def test_run_stops_at_max_steps():
    agent = ScreenAgent()
    agent.MAX_STEPS = 3
    keep_going = _continue_response({"type": "wait", "seconds": 0})

    with patch.object(agent, "_capture", return_value="fakeb64"), \
         patch.object(agent, "_get_action", return_value=keep_going), \
         patch.object(agent, "_execute"), \
         patch("time.sleep"):
        result = agent.run("do something forever")

    assert "max steps" in result.lower()


def test_execute_click():
    agent = ScreenAgent()
    pyautogui = MagicMock()
    agent._execute(pyautogui, {"type": "click", "x": 50, "y": 75})
    pyautogui.click.assert_called_once_with(50, 75)


def test_execute_double_click():
    agent = ScreenAgent()
    pyautogui = MagicMock()
    agent._execute(pyautogui, {"type": "double_click", "x": 10, "y": 20})
    pyautogui.doubleClick.assert_called_once_with(10, 20)


def test_execute_type():
    agent = ScreenAgent()
    pyautogui = MagicMock()
    agent._execute(pyautogui, {"type": "type", "text": "hello world"})
    pyautogui.typewrite.assert_called_once_with("hello world", interval=0.04)


def test_execute_hotkey():
    agent = ScreenAgent()
    pyautogui = MagicMock()
    agent._execute(pyautogui, {"type": "hotkey", "keys": ["ctrl", "s"]})
    pyautogui.hotkey.assert_called_once_with("ctrl", "s")


def test_execute_scroll_down():
    agent = ScreenAgent()
    pyautogui = MagicMock()
    agent._execute(pyautogui, {"type": "scroll", "amount": -3})
    pyautogui.scroll.assert_called_once_with(-3)


def test_execute_unknown_type_is_noop():
    agent = ScreenAgent()
    pyautogui = MagicMock()
    agent._execute(pyautogui, {"type": "none"})
    pyautogui.click.assert_not_called()
    pyautogui.typewrite.assert_not_called()
```

- [ ] **Step 2: Run tests to confirm they fail**

```
python -m pytest tests/agents/test_screen_agent.py -v
```

Expected: `ModuleNotFoundError: No module named 'core.agents.screen_agent'`

- [ ] **Step 3: Write ScreenAgent**

```python
# core/agents/screen_agent.py
import base64
import json
import time
from io import BytesIO
import anthropic
from core.agents.base_agent import BaseAgent

_VISION_SYSTEM = """\
You control a Windows computer on behalf of the user. You will see a screenshot and must decide the single next action to make progress on the task.

Reply with a JSON object only — no markdown, no explanation, just raw JSON:
{
  "status": "continue" | "done",
  "message": "<one sentence describing what you see or what you just did>",
  "action": {
    "type": "click" | "double_click" | "right_click" | "type" | "hotkey" | "scroll" | "wait" | "none",
    "x": <integer screen x, required for click/double_click/right_click>,
    "y": <integer screen y, required for click/double_click/right_click>,
    "text": "<text to type, required for type>",
    "keys": ["key1", "key2"],
    "amount": <integer scroll clicks — positive=up, negative=down>,
    "seconds": <float seconds to wait>
  }
}

Set status to "done" when the task is fully complete. Set action.type to "none" when done.
"""


class ScreenAgent(BaseAgent):
    MAX_STEPS = 10
    STEP_DELAY = 0.8

    @property
    def name(self) -> str:
        return "screen"

    @property
    def description(self) -> str:
        return "Sees the screen and controls any desktop application via clicks, typing, and keyboard shortcuts."

    def run(self, task: str) -> str:
        import pyautogui
        import mss
        from PIL import Image

        client = anthropic.Anthropic()
        history: list[str] = []

        for _ in range(self.MAX_STEPS):
            screenshot_b64 = self._capture(mss, Image)
            result = self._get_action(client, task, screenshot_b64, history)
            history.append(result.get("message", ""))

            if result.get("status") == "done":
                return result.get("message", "Task complete.")

            self._execute(pyautogui, result.get("action", {}))
            time.sleep(self.STEP_DELAY)

        return "Task completed (reached max steps)."

    def _capture(self, mss_module, Image_module) -> str:
        with mss_module.mss() as sct:
            raw = sct.grab(sct.monitors[1])
            img = Image_module.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
            buf = BytesIO()
            img.save(buf, format="PNG")
            return base64.b64encode(buf.getvalue()).decode()

    def _get_action(
        self,
        client: anthropic.Anthropic,
        task: str,
        screenshot_b64: str,
        history: list[str],
    ) -> dict:
        history_text = (
            "\n".join(f"Step {i + 1}: {h}" for i, h in enumerate(history))
            if history
            else "None yet."
        )
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=512,
            system=_VISION_SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": screenshot_b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": f"Task: {task}\n\nSteps taken so far:\n{history_text}\n\nWhat is the next action?",
                        },
                    ],
                }
            ],
        )
        text = response.content[0].text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"status": "done", "message": text, "action": {"type": "none"}}

    def _execute(self, pyautogui_module, action: dict) -> None:
        action_type = action.get("type", "none")
        if action_type == "click":
            pyautogui_module.click(action["x"], action["y"])
        elif action_type == "double_click":
            pyautogui_module.doubleClick(action["x"], action["y"])
        elif action_type == "right_click":
            pyautogui_module.rightClick(action["x"], action["y"])
        elif action_type == "type":
            pyautogui_module.typewrite(action["text"], interval=0.04)
        elif action_type == "hotkey":
            pyautogui_module.hotkey(*action["keys"])
        elif action_type == "scroll":
            x = action.get("x")
            y = action.get("y")
            amount = action.get("amount", 3)
            if x is not None and y is not None:
                pyautogui_module.scroll(amount, x=x, y=y)
            else:
                pyautogui_module.scroll(amount)
        elif action_type == "wait":
            time.sleep(action.get("seconds", 1.0))
```

- [ ] **Step 4: Run tests to confirm they pass**

```
python -m pytest tests/agents/test_screen_agent.py -v
```

Expected: all 9 tests PASS

- [ ] **Step 5: Commit**

```
git add core/agents/screen_agent.py tests/agents/test_screen_agent.py
git commit -m "feat: add ScreenAgent -- vision-action loop for desktop control"
```

---

## Task 4: BrowserAgent

**Files:**
- Create: `core/agents/browser_agent.py`
- Create: `tests/agents/test_browser_agent.py`

**Interfaces:**
- Consumes: `BaseAgent` from `core/agents/base_agent.py`; `Vault` from `core/vault.py`
- Produces: `BrowserAgent` with `.run(task: str, start_url: str = None) -> str`
- Consumed by: `Brain._try_agent_dispatch` (Task 5)

---

- [ ] **Step 1: Write the failing BrowserAgent tests**

```python
# tests/agents/test_browser_agent.py
from unittest.mock import MagicMock, patch
from core.agents.browser_agent import BrowserAgent


def _done(message: str = "Task complete.") -> dict:
    return {"status": "done", "message": message, "action": {"type": "none"}}


def _continue(action: dict) -> dict:
    return {"status": "continue", "message": "Working...", "action": action}


def test_execute_navigate():
    agent = BrowserAgent()
    page = MagicMock()
    agent._execute(page, {"type": "navigate", "url": "https://example.com"})
    page.goto.assert_called_once_with("https://example.com", wait_until="domcontentloaded")


def test_execute_click_by_selector():
    agent = BrowserAgent()
    page = MagicMock()
    agent._execute(page, {"type": "click", "selector": "#submit"})
    page.click.assert_called_once_with("#submit", timeout=5000)


def test_execute_type_fills_field():
    agent = BrowserAgent()
    page = MagicMock()
    agent._execute(page, {"type": "type", "selector": "#email", "text": "mo@gmail.com"})
    page.fill.assert_called_once_with("#email", "mo@gmail.com")


def test_execute_scroll_down():
    agent = BrowserAgent()
    page = MagicMock()
    agent._execute(page, {"type": "scroll", "direction": "down"})
    page.mouse.wheel.assert_called_once_with(0, 500)


def test_execute_scroll_up():
    agent = BrowserAgent()
    page = MagicMock()
    agent._execute(page, {"type": "scroll", "direction": "up"})
    page.mouse.wheel.assert_called_once_with(0, -500)


def test_execute_wait():
    agent = BrowserAgent()
    page = MagicMock()
    with patch("time.sleep") as mock_sleep:
        agent._execute(page, {"type": "wait", "seconds": 2})
    mock_sleep.assert_called_once_with(2)


def test_run_done_immediately():
    agent = BrowserAgent()
    done = _done("Found the answer.")

    mock_page = MagicMock()
    mock_page.url = "https://example.com"
    mock_page.screenshot.return_value = b"fake_png"
    mock_browser = MagicMock()
    mock_browser.new_page.return_value = mock_page
    mock_playwright_ctx = MagicMock()
    mock_playwright_ctx.chromium.launch.return_value = mock_browser

    with patch.object(agent, "_get_action", return_value=done), \
         patch("time.sleep"), \
         patch("playwright.sync_api.sync_playwright") as mock_pw:
        mock_pw.return_value.__enter__ = MagicMock(return_value=mock_playwright_ctx)
        mock_pw.return_value.__exit__ = MagicMock(return_value=False)
        result = agent.run("find something")

    assert result == "Found the answer."
    mock_browser.close.assert_called_once()


def test_run_requests_login_when_no_vault_creds():
    agent = BrowserAgent()
    need_login = {"status": "need_login", "message": "google", "action": {"type": "none"}}

    mock_page = MagicMock()
    mock_page.url = "https://accounts.google.com"
    mock_page.screenshot.return_value = b"fake_png"
    mock_browser = MagicMock()
    mock_browser.new_page.return_value = mock_page
    mock_playwright_ctx = MagicMock()
    mock_playwright_ctx.chromium.launch.return_value = mock_browser

    with patch.object(agent, "_get_action", return_value=need_login), \
         patch("core.vault.Vault.get", return_value=None), \
         patch("time.sleep"), \
         patch("playwright.sync_api.sync_playwright") as mock_pw:
        mock_pw.return_value.__enter__ = MagicMock(return_value=mock_playwright_ctx)
        mock_pw.return_value.__exit__ = MagicMock(return_value=False)
        result = agent.run("check gmail")

    assert "login required" in result.lower() or "vault set" in result.lower()
```

- [ ] **Step 2: Run tests to confirm they fail**

```
python -m pytest tests/agents/test_browser_agent.py -v
```

Expected: `ModuleNotFoundError: No module named 'core.agents.browser_agent'`

- [ ] **Step 3: Write BrowserAgent**

```python
# core/agents/browser_agent.py
import base64
import json
import time
import anthropic
from core.agents.base_agent import BaseAgent
from core.vault import Vault

_VISION_SYSTEM = """\
You control a web browser on behalf of the user. You will see a browser screenshot and must decide the single next action to make progress on the task.

Reply with a JSON object only — no markdown, no explanation, just raw JSON:
{
  "status": "continue" | "done" | "need_login",
  "message": "<one sentence describing what you see or what you just did>",
  "action": {
    "type": "navigate" | "click" | "type" | "scroll" | "wait" | "none",
    "url": "<full URL, required for navigate>",
    "selector": "<CSS selector, required for click/type>",
    "text": "<text to enter, required for type>",
    "direction": "up" | "down",
    "seconds": <float>
  }
}

Use "need_login" when you see a login page and need credentials — include the service name (e.g. "google") in message.
Set status to "done" when the task is fully complete.
"""


class BrowserAgent(BaseAgent):
    MAX_STEPS = 20
    STEP_DELAY = 1.0

    @property
    def name(self) -> str:
        return "browser"

    @property
    def description(self) -> str:
        return "Automates any website -- navigate, fill forms, click buttons, handle logins."

    def run(self, task: str, start_url: str = None) -> str:
        from playwright.sync_api import sync_playwright

        client = anthropic.Anthropic()
        vault = Vault()
        history: list[str] = []

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            page = browser.new_page()
            page.set_viewport_size({"width": 1280, "height": 800})

            if start_url:
                page.goto(start_url, wait_until="domcontentloaded")

            for _ in range(self.MAX_STEPS):
                screenshot_b64 = self._capture(page)
                result = self._get_action(client, task, screenshot_b64, page.url, history)
                history.append(result.get("message", ""))

                if result["status"] == "done":
                    browser.close()
                    return result.get("message", "Task complete.")

                if result["status"] == "need_login":
                    service = result.get("message", "unknown").lower().split()[0]
                    creds = vault.get(service)
                    if not creds:
                        browser.close()
                        return (
                            f"Login required for {service} -- "
                            f"add credentials first: vault set {service}"
                        )
                    history.append(f"Using saved credentials for {service}")
                    continue

                self._execute(page, result.get("action", {}))
                time.sleep(self.STEP_DELAY)

            browser.close()
            return "Browser task completed (reached max steps)."

    def _capture(self, page) -> str:
        return base64.b64encode(page.screenshot(full_page=False)).decode()

    def _get_action(
        self,
        client: anthropic.Anthropic,
        task: str,
        screenshot_b64: str,
        current_url: str,
        history: list[str],
    ) -> dict:
        history_text = (
            "\n".join(f"Step {i + 1}: {h}" for i, h in enumerate(history))
            if history
            else "None yet."
        )
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=512,
            system=_VISION_SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": screenshot_b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": (
                                f"Task: {task}\n"
                                f"Current URL: {current_url}\n\n"
                                f"Steps so far:\n{history_text}\n\n"
                                "What is the next action?"
                            ),
                        },
                    ],
                }
            ],
        )
        text = response.content[0].text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"status": "done", "message": text, "action": {"type": "none"}}

    def _execute(self, page, action: dict) -> None:
        action_type = action.get("type", "none")
        if action_type == "navigate":
            page.goto(action["url"], wait_until="domcontentloaded")
        elif action_type == "click":
            try:
                page.click(action["selector"], timeout=5000)
            except Exception:
                page.get_by_text(action["selector"]).first.click(timeout=5000)
        elif action_type == "type":
            page.fill(action["selector"], action["text"])
        elif action_type == "scroll":
            page.mouse.wheel(0, 500 if action.get("direction") == "down" else -500)
        elif action_type == "wait":
            time.sleep(action.get("seconds", 2))
```

- [ ] **Step 4: Run tests to confirm they pass**

```
python -m pytest tests/agents/test_browser_agent.py -v
```

Expected: all 9 tests PASS

- [ ] **Step 5: Commit**

```
git add core/agents/browser_agent.py tests/agents/test_browser_agent.py
git commit -m "feat: add BrowserAgent -- Playwright vision-action loop for web automation"
```

---

## Task 5: Brain Routing Integration

**Files:**
- Modify: `core/brain.py` — add `_try_agent_dispatch()` method + call it in `chat()`
- Create: `tests/test_brain_routing.py`

**Interfaces:**
- Consumes: `classify_intent` from `core/agents/router.py`, `ScreenAgent`, `BrowserAgent`
- The existing `chat()` tool loop (lines 5975-6049) must NOT be modified

---

- [ ] **Step 1: Write the failing routing tests**

```python
# tests/test_brain_routing.py
from unittest.mock import MagicMock, patch

def _make_brain():
    from core.brain import Brain
    return Brain(profile={})

def test_screen_task_routes_to_screen_agent():
    brain = _make_brain()
    with patch("core.agents.router.classify_intent", return_value="screen"), \
         patch("core.agents.screen_agent.ScreenAgent.run", return_value="Clicked the button."):
        result = brain.chat("click the submit button")
    assert result == "Clicked the button."

def test_browser_task_routes_to_browser_agent():
    brain = _make_brain()
    with patch("core.agents.router.classify_intent", return_value="browser"), \
         patch("core.agents.browser_agent.BrowserAgent.run", return_value="Booked the table."):
        result = brain.chat("book a table at Cairo Kitchen")
    assert result == "Booked the table."

def test_instant_task_bypasses_agents():
    brain = _make_brain()
    mock_block = MagicMock()
    mock_block.text = "Sunny in Cairo."
    mock_block.type = "text"
    mock_response = MagicMock()
    mock_response.stop_reason = "end_turn"
    mock_response.content = [mock_block]

    with patch("core.agents.router.classify_intent", return_value="instant"), \
         patch.object(brain.client.messages, "create", return_value=mock_response):
        result = brain.chat("what is the weather?")

    assert result == "Sunny in Cairo."

def test_unimplemented_agent_falls_through_to_instant():
    brain = _make_brain()
    mock_block = MagicMock()
    mock_block.text = "Research answer."
    mock_block.type = "text"
    mock_response = MagicMock()
    mock_response.stop_reason = "end_turn"
    mock_response.content = [mock_block]

    with patch("core.agents.router.classify_intent", return_value="research"), \
         patch.object(brain.client.messages, "create", return_value=mock_response):
        result = brain.chat("research everything about Egypt")

    assert result == "Research answer."
```

- [ ] **Step 2: Run tests to confirm they fail**

```
python -m pytest tests/test_brain_routing.py -v
```

Expected: tests pass through to Claude API (no routing yet) — `test_screen_task_routes_to_screen_agent` may NOT return "Clicked the button." meaning the routing is not wired yet.

- [ ] **Step 3: Add `_try_agent_dispatch` method to Brain class**

Open `core/brain.py`. Find the line `def chat(self, user_message: str, memory_context: str = "") -> str:` (line 5953). Add the following new method IMMEDIATELY BEFORE it (i.e., between line 5952 and 5953):

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
        return None  # stocks / research / file not yet implemented -- fall through

```

- [ ] **Step 4: Add routing call at the top of `chat()`**

In `core/brain.py`, find the `chat()` method. After the logger block (line 5957, the blank line after `self._logger.log("user", user_message)`) and BEFORE `system = SYSTEM_PROMPT` (line 5958), insert:

```python
        # Agent routing — intercept complex multi-step tasks before tool loop
        _agent_result = self._try_agent_dispatch(user_message)
        if _agent_result is not None:
            self.conversation_history.append({"role": "assistant", "content": _agent_result})
            if self._logger:
                self._logger.log("assistant", _agent_result, [])
            return _agent_result

```

The resulting start of `chat()` should look like:

```python
    def chat(self, user_message: str, memory_context: str = "") -> str:
        # Log user turn
        if self._logger:
            self._logger.log("user", user_message)

        # Agent routing — intercept complex multi-step tasks before tool loop
        _agent_result = self._try_agent_dispatch(user_message)
        if _agent_result is not None:
            self.conversation_history.append({"role": "assistant", "content": _agent_result})
            if self._logger:
                self._logger.log("assistant", _agent_result, [])
            return _agent_result

        system = SYSTEM_PROMPT
        if self.memory is not None:
```

- [ ] **Step 5: Run all routing tests**

```
python -m pytest tests/test_brain_routing.py -v
```

Expected: all 4 tests PASS

- [ ] **Step 6: Run the full test suite to check for regressions**

```
python -m pytest tests/ -v --tb=short
```

Expected: all previously passing tests still pass; new tests pass. Zero failures.

- [ ] **Step 7: Commit**

```
git add core/brain.py tests/test_brain_routing.py
git commit -m "feat: wire agent routing into Brain.chat -- screen + browser dispatch"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Covered by |
|---|---|
| ScreenAgent sees screen and controls any app | Task 3 |
| BrowserAgent automates any website | Task 4 |
| Encrypted local vault for credentials | Task 2 |
| Two-lane orchestrator (instant vs. agent) | Task 5 |
| Instant lane unchanged | Task 5 — existing chat() loop untouched |
| Playwright for browser automation | Task 4 |
| Claude Vision for screen understanding | Task 3 (`_get_action` sends screenshot) |
| FAILSAFE on | Task 3 — pyautogui.FAILSAFE defaults to True, not overridden |
| Max steps guard | Task 3 (MAX_STEPS=10), Task 4 (MAX_STEPS=20) |
| BaseAgent abstract class | Task 1 |
| Router keyword-based (zero API cost) | Task 1 |

**No placeholders:** All steps have complete code. No TBDs.

**Type consistency:** `classify_intent` returns `str`, `_try_agent_dispatch` returns `str | None`, both consistent across Tasks 1 and 5. `BaseAgent.run(task: str) -> str` matches ScreenAgent and BrowserAgent signatures.
