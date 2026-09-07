from core.agents.base_agent import BaseAgent
from core.agents.registry import ROSTER, format_roster, load, resolve, tool_names, tool_schemas


def test_every_spec_points_at_a_real_base_agent_subclass():
    from importlib import import_module
    for spec in ROSTER.values():
        cls = getattr(import_module(spec.module), spec.cls)
        assert issubclass(cls, BaseAgent), spec.callsign


def test_schemas_match_the_six_tool_definitions_in_brain():
    """The registry is the source of these schemas -- this pins them to what
    the brain actually exposes, so a registry edit cannot silently change the
    tool surface the model sees."""
    from core.brain import TOOLS
    by_name = {t["name"]: t for t in TOOLS}
    for schema in tool_schemas():
        assert by_name[schema["name"]] == schema


def test_tool_names_cover_the_whole_roster():
    assert tool_names() == {
        "screen_agent", "browser_agent", "stocks_agent",
        "research_agent", "file_agent", "health_agent",
        "comms_agent", "scheduler_agent", "finance_agent", "dev_agent",
    }


def test_gated_agents_declare_tools_they_actually_have():
    """A confirm_before naming a tool the agent does not own would be a gate
    that protects nothing."""
    for spec in ROSTER.values():
        if not spec.confirm_before:
            continue
        agent = load(spec.tool_name, allow_side_effects=True)
        _, dispatch = agent._toolset()
        assert set(spec.confirm_before) <= set(dispatch), spec.callsign


def test_callsigns_are_unique_and_resolve_case_insensitively():
    callsigns = [s.callsign for s in ROSTER.values()]
    assert len(set(callsigns)) == len(callsigns)
    assert resolve("sage").tool_name == "research_agent"
    assert resolve("SAGE").tool_name == "research_agent"
    assert resolve("research_agent").callsign == "Sage"


def test_resolve_returns_none_for_unknown_names():
    assert resolve("Gandalf") is None
    assert resolve("") is None
    assert resolve(None) is None


def test_format_roster_lists_every_callsign_and_the_inspector():
    text = format_roster()
    for spec in ROSTER.values():
        assert spec.callsign in text
    assert "Warden" in text
