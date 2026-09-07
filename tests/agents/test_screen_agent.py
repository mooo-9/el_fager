import json
from unittest.mock import MagicMock, patch
from core.agents.screen_agent import ScreenAgent
from tests._optional import requires


def _done_response(message: str = "Task complete.") -> dict:
    return {"status": "done", "message": message, "action": {"type": "none"}}


def _continue_response(action: dict, message: str = "Working...") -> dict:
    return {"status": "continue", "message": message, "action": action}


@requires("pyautogui")
@requires("mss")
@requires("PIL")
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


@requires("pyautogui")
@requires("mss")
@requires("PIL")
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


@requires("pyautogui")
@requires("mss")
@requires("PIL")
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
