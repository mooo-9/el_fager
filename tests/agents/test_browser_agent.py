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


def test_run_continues_when_vault_creds_found():
    agent = BrowserAgent()
    need_login = {"status": "need_login", "message": "google", "action": {"type": "none"}}
    done = {"status": "done", "message": "Task complete.", "action": {"type": "none"}}

    mock_page = MagicMock()
    mock_page.url = "https://accounts.google.com"
    mock_page.screenshot.return_value = b"fake_png"
    mock_browser = MagicMock()
    mock_browser.new_page.return_value = mock_page
    mock_playwright_ctx = MagicMock()
    mock_playwright_ctx.chromium.launch.return_value = mock_browser

    with patch.object(agent, "_get_action", side_effect=[need_login, done]), \
         patch("core.vault.Vault.get", return_value={"username": "mo", "password": "secret"}), \
         patch("time.sleep"), \
         patch("playwright.sync_api.sync_playwright") as mock_pw:
        mock_pw.return_value.__enter__ = MagicMock(return_value=mock_playwright_ctx)
        mock_pw.return_value.__exit__ = MagicMock(return_value=False)
        result = agent.run("check gmail")

    assert result == "Task complete."
