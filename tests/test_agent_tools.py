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
