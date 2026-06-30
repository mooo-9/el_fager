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
