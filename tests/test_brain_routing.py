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


def test_specialist_keywords_no_longer_intercepted_before_tool_loop():
    brain = _make_brain()
    with patch("core.agents.screen_agent.ScreenAgent.run", return_value="x"), \
         patch("core.agents.browser_agent.BrowserAgent.run", return_value="x"), \
         patch("core.agents.stocks_agent.StocksAgent.run", return_value="x"), \
         patch("core.agents.research_agent.ResearchAgent.run", return_value="x"), \
         patch("core.agents.file_agent.FileAgent.run", return_value="x"), \
         patch("core.agents.health_agent.HealthAgent.run", return_value="x"):
        assert brain._try_agent_dispatch("click the submit button") is None
        assert brain._try_agent_dispatch("book a table at Cairo Kitchen") is None
        assert brain._try_agent_dispatch("analyze NVDA for me") is None
        assert brain._try_agent_dispatch("research everything about Egypt") is None
        assert brain._try_agent_dispatch("summarize this pdf") is None
        assert brain._try_agent_dispatch("I just ate chicken and rice") is None


def test_gate_check_still_intercepted_before_tool_loop():
    brain = _make_brain()
    with patch("core.trade_tracker.TradeTracker.sync", return_value=None), \
         patch("core.paper_metrics.PaperMetrics.gate_summary", return_value="Gate status: not ready"):
        result = brain._try_agent_dispatch("am i ready to go live")
    assert result == "Gate status: not ready"


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
