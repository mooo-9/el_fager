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
        from core.telemetry import instrument_client
        instrument_client(client, "screen_agent")
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
