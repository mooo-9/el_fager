from unittest.mock import MagicMock, patch

import pytest

from core.agents.verifier import verify


def _mock_client(text: str):
    client = MagicMock()
    block = MagicMock()
    block.text = text
    client.messages.create.return_value = MagicMock(content=[block])
    return client


class TestHeuristic:
    """Obvious failures must cost nothing -- no API call at all."""

    @pytest.mark.parametrize("result", [
        "",
        "   ",
        "Tool error (file_search): boom",
        "Unknown tool: nope",
        "API error: overloaded",
        "No search results found for: brokers",
        "[stopped after 8 steps -- let me know if you want me to continue]",
    ])
    def test_failure_shapes_short_circuit_without_an_api_call(self, result):
        with patch("anthropic.Anthropic") as anthropic_cls:
            verdict = verify("do the thing", None, result)
        assert verdict.verdict == "fail"
        anthropic_cls.assert_not_called()

    def test_none_result_is_a_failure(self):
        assert verify("do the thing", None, None).verdict == "fail"

    def test_a_short_result_is_judged_not_auto_failed(self):
        """"Done." is a legitimate answer for an action task -- failing it on
        length alone would retry work that already happened."""
        client = MagicMock()
        block = MagicMock()
        block.text = "PASS"
        client.messages.create.return_value = MagicMock(content=[block])
        with patch("anthropic.Anthropic", return_value=client):
            assert verify("log my lunch", None, "Done.").verdict == "pass"
        client.messages.create.assert_called_once()


class TestLlmVerdict:
    def test_pass_is_parsed(self):
        with patch("anthropic.Anthropic", return_value=_mock_client("PASS")):
            assert verify("t", None, "a real result string").verdict == "pass"

    def test_fail_carries_the_reason(self):
        client = _mock_client("FAIL: the agent only described the plan")
        with patch("anthropic.Anthropic", return_value=client):
            verdict = verify("t", None, "a real result string")
        assert verdict.verdict == "fail"
        assert "described the plan" in verdict.reason

    def test_acceptance_criteria_reach_the_prompt(self):
        client = _mock_client("PASS")
        with patch("anthropic.Anthropic", return_value=client):
            verify("t", "at least 3 brokers with fees", "a real result string")
        prompt = client.messages.create.call_args.kwargs["messages"][0]["content"]
        assert "at least 3 brokers with fees" in prompt

    def test_unrecognised_answer_is_unclear_not_fail(self):
        with patch("anthropic.Anthropic", return_value=_mock_client("maybe?")):
            assert verify("t", None, "a real result string").verdict == "unclear"


class TestInspectorFailure:
    def test_api_error_yields_unclear_so_the_agent_is_not_punished(self):
        with patch("anthropic.Anthropic", side_effect=RuntimeError("no key")):
            verdict = verify("t", None, "a real result string")
        assert verdict.verdict == "unclear"
        assert "unavailable" in verdict.reason
