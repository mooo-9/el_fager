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


class TestRunCommandGuardrail:
    """safe_mode is not the model's to lift.

    It used to sit in run_command's input_schema and reach system_tool through
    run_command(**tool_input), so the model could ask for its own guardrail to
    be switched off.
    """

    def _schema(self):
        from core.brain import TOOLS
        return next(t for t in TOOLS if t["name"] == "run_command")

    def test_safe_mode_is_not_offered_to_the_model(self):
        assert "safe_mode" not in self._schema()["input_schema"]["properties"]

    def test_command_is_still_offered(self):
        schema = self._schema()["input_schema"]
        assert "command" in schema["properties"]
        assert schema["required"] == ["command"]

    def test_a_smuggled_safe_mode_is_ignored(self, monkeypatch):
        """A dropped schema field does not stop a model emitting the key."""
        from unittest.mock import MagicMock
        import core.brain as brain

        seen = {}

        def fake_run_command(command, safe_mode=True):
            seen["command"] = command
            seen["safe_mode"] = safe_mode
            return "ok"

        # _dispatch_tool imports it from tools.system_tool at call time
        import tools.system_tool as system_tool
        monkeypatch.setattr(system_tool, "run_command", fake_run_command)
        b = brain.Brain.__new__(brain.Brain)
        result = brain.Brain._dispatch_tool(
            b, "run_command", {"command": "Get-Date", "safe_mode": False})

        assert result == "ok"
        assert seen["command"] == "Get-Date"
        assert seen["safe_mode"] is True, "the guardrail must survive the request"
