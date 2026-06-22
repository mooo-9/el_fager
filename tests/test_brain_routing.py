from unittest.mock import MagicMock, patch


def _make_brain():
    from core.brain import Brain
    return Brain(profile={})


def test_screen_task_routes_to_screen_agent():
    brain = _make_brain()
    with patch("core.agents.router.classify_intent", return_value="screen"), \
         patch("core.agents.screen_agent.ScreenAgent.run", return_value="Clicked the button."):
        result = brain.chat("click the submit button")
    assert result == "Clicked the button."


def test_browser_task_routes_to_browser_agent():
    brain = _make_brain()
    with patch("core.agents.router.classify_intent", return_value="browser"), \
         patch("core.agents.browser_agent.BrowserAgent.run", return_value="Booked the table."):
        result = brain.chat("book a table at Cairo Kitchen")
    assert result == "Booked the table."


def test_instant_task_bypasses_agents():
    brain = _make_brain()
    mock_block = MagicMock()
    mock_block.text = "Sunny in Cairo."
    mock_block.type = "text"
    mock_response = MagicMock()
    mock_response.stop_reason = "end_turn"
    mock_response.content = [mock_block]

    with patch("core.agents.router.classify_intent", return_value="instant"), \
         patch.object(brain.client.messages, "create", return_value=mock_response):
        result = brain.chat("what is the weather?")

    assert result == "Sunny in Cairo."


def test_unimplemented_agent_falls_through_to_instant():
    brain = _make_brain()
    mock_block = MagicMock()
    mock_block.text = "Research answer."
    mock_block.type = "text"
    mock_response = MagicMock()
    mock_response.stop_reason = "end_turn"
    mock_response.content = [mock_block]

    with patch("core.agents.router.classify_intent", return_value="research"), \
         patch.object(brain.client.messages, "create", return_value=mock_response):
        result = brain.chat("research everything about Egypt")

    assert result == "Research answer."
