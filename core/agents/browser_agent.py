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
        from core.telemetry import instrument_client
        instrument_client(client, "browser_agent")
        vault = Vault()
        history: list[str] = []

        with sync_playwright() as p:
            from tools.comet_tool import CometUnavailable, automation_context
            try:
                browser, context, owned = automation_context(p, headless=False)
            except CometUnavailable as e:
                return str(e)
            page = context.new_page()
            page.set_viewport_size({"width": 1280, "height": 800})

            def close_up():
                # In Mo's own Comet (`owned` False) the tab stays: it holds what
                # he asked for — he found his video and then watched it close.
                # Leaving the with-block only disconnects from his browser.
                if not owned:
                    return
                for obj in (page, browser):
                    try:
                        obj.close()
                    except Exception:
                        pass

            if start_url:
                page.goto(start_url, wait_until="domcontentloaded")

            injected_creds: dict | None = None
            for _ in range(self.MAX_STEPS):
                screenshot_b64 = self._capture(page)
                result = self._get_action(
                    client, task, screenshot_b64, page.url, history,
                    injected_creds=injected_creds,
                )
                injected_creds = None
                history.append(result.get("message", ""))

                if result["status"] == "done":
                    close_up()
                    return result.get("message", "Task complete.")

                if result["status"] == "need_login":
                    service = result.get("message", "unknown").lower().split()[0]
                    creds = vault.get(service)
                    if not creds:
                        close_up()
                        return (
                            f"Login required for {service} -- "
                            f"add credentials first: vault set {service}"
                        )
                    history.append(f"Using saved credentials for {service}")
                    injected_creds = {
                        "service": service,
                        "username": creds.get("username", ""),
                        "password": creds.get("password", ""),
                    }
                    continue

                self._execute(page, result.get("action", {}))
                time.sleep(self.STEP_DELAY)

            close_up()
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
        injected_creds: dict | None = None,
    ) -> dict:
        history_text = (
            "\n".join(f"Step {i + 1}: {h}" for i, h in enumerate(history))
            if history
            else "None yet."
        )
        creds_hint = (
            f"\nCredentials available: username={injected_creds['username']} "
            f"password={injected_creds['password']} -- fill them into the login form now."
            if injected_creds
            else ""
        )
        response = client.messages.create(
            model="claude-sonnet-5",
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
                                f"What is the next action?{creds_hint}"
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
