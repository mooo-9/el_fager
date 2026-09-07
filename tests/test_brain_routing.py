from unittest.mock import MagicMock, patch


def _make_brain():
    from core.brain import Brain
    return Brain(profile={})


def _tool_use_response(tool_name: str, tool_input: dict, tool_id: str = "tool_1"):
    block = MagicMock()
    block.type = "tool_use"
    block.name = tool_name
    block.input = tool_input
    block.id = tool_id
    response = MagicMock()
    response.stop_reason = "tool_use"
    response.content = [block]
    return response


def _end_turn_response(text: str):
    block = MagicMock()
    block.type = "text"
    block.text = text
    response = MagicMock()
    response.stop_reason = "end_turn"
    response.content = [block]
    return response


def test_screen_task_routes_to_screen_agent():
    brain = _make_brain()
    responses = [
        _tool_use_response("screen_agent", {"task": "click the submit button"}),
        _end_turn_response("Clicked the button."),
    ]
    with patch.object(brain.client.messages, "create", side_effect=responses), \
         patch("core.agents.screen_agent.ScreenAgent.run", return_value="Button clicked."):
        result = brain.chat("click the submit button")
    assert result == "Clicked the button."


def test_browser_task_routes_to_browser_agent():
    brain = _make_brain()
    responses = [
        _tool_use_response("browser_agent", {"task": "book a table at Cairo Kitchen"}),
        _end_turn_response("Booked the table."),
    ]
    with patch.object(brain.client.messages, "create", side_effect=responses), \
         patch("core.agents.browser_agent.BrowserAgent.run", return_value="Table booked."):
        result = brain.chat("book a table at Cairo Kitchen")
    assert result == "Booked the table."


def test_research_task_routes_to_research_agent():
    brain = _make_brain()
    responses = [
        _tool_use_response("research_agent", {"task": "research everything about Egypt"}),
        _end_turn_response("Research answer."),
    ]
    with patch.object(brain.client.messages, "create", side_effect=responses), \
         patch("core.agents.research_agent.ResearchAgent.run", return_value="Egypt research data."):
        result = brain.chat("research everything about Egypt")
    assert result == "Research answer."


def test_instant_task_bypasses_agents():
    brain = _make_brain()
    with patch.object(brain.client.messages, "create", return_value=_end_turn_response("Sunny in Cairo.")):
        result = brain.chat("what is the weather?")
    assert result == "Sunny in Cairo."


def test_chat_loop_stops_after_max_iterations():
    brain = _make_brain()
    responses = [_tool_use_response("noop_tool", {})] * 20
    with patch.object(brain.client.messages, "create", side_effect=responses) as mock_create:
        result = brain.chat("loop forever")
    assert "stopped after" in result.lower()
    assert mock_create.call_count == 15


def _mixed_tool_use_response(text: str, tool_name: str, tool_input: dict, tool_id: str = "tool_1"):
    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = text
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.name = tool_name
    tool_block.input = tool_input
    tool_block.id = tool_id
    response = MagicMock()
    response.stop_reason = "tool_use"
    response.content = [text_block, tool_block]
    return response


def test_chat_loop_captures_text_alongside_tool_use_block():
    brain = _make_brain()
    responses = [
        _mixed_tool_use_response("Let me check that for you.", "noop_tool", {}),
    ] + [_tool_use_response("noop_tool", {})] * 15
    with patch.object(brain.client.messages, "create", side_effect=responses) as mock_create:
        result = brain.chat("loop forever")
    assert result.startswith("Let me check that for you. [stopped after 15 steps")
    assert mock_create.call_count == 15


def test_chat_with_screenshot_captures_text_from_mixed_blocks():
    brain = _make_brain()
    non_text_block = MagicMock()
    non_text_block.type = "tool_use"
    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = "I can see your screen."
    response = MagicMock()
    response.stop_reason = "end_turn"
    response.content = [non_text_block, text_block]
    with patch.object(brain.client.messages, "create", return_value=response):
        result = brain.chat_with_screenshot("what do you see?", "aGVsbG8=")
    assert result == "I can see your screen."


def test_chat_can_chain_agent_tool_then_instant_tool():
    brain = _make_brain()
    responses = [
        _tool_use_response("screen_agent", {"task": "what error is showing"}, tool_id="tool_1"),
        _tool_use_response("web_search", {"query": "fix permission denied error"}, tool_id="tool_2"),
        _end_turn_response("Found a fix and searched the web for it."),
    ]
    with patch.object(brain.client.messages, "create", side_effect=responses), \
         patch("core.agents.screen_agent.ScreenAgent.run", return_value="Permission denied error visible."), \
         patch("tools.web_tool.web_search", return_value="Fix: run as administrator."):
        result = brain.chat("check my screen error then search the web for a fix")
    assert result == "Found a fix and searched the web for it."
