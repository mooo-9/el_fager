"""Tests for the transient-error retry layer around Brain._dispatch_tool."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import MagicMock, patch

import httpx

import core.brain as brain_mod
from core.brain import Brain, _is_transient_error


def _make_brain():
    return Brain(profile={})


class TestIsTransientError:
    def test_httpx_timeout_is_transient(self):
        assert _is_transient_error(httpx.ConnectTimeout("slow")) is True

    def test_rate_limit_message_is_transient(self):
        assert _is_transient_error(RuntimeError("Rate limit exceeded")) is True

    def test_http_503_message_is_transient(self):
        assert _is_transient_error(RuntimeError("upstream returned HTTP 503")) is True

    def test_value_error_is_not_transient(self):
        assert _is_transient_error(ValueError("bad symbol XYZ")) is False

    def test_dollar_amount_not_mistaken_for_status_code(self):
        assert _is_transient_error(RuntimeError("cannot buy $500 of NVDA")) is False


class TestDispatchRetry:
    def test_success_needs_no_retry(self):
        b = _make_brain()
        with patch.object(b, "_dispatch_tool_once", return_value="ok") as once:
            assert b._dispatch_tool("web_search", {"query": "x"}) == "ok"
        assert once.call_count == 1

    def test_transient_failure_then_success(self):
        b = _make_brain()
        once = MagicMock(side_effect=[httpx.ConnectTimeout("net blip"), "ok"])
        with patch.object(b, "_dispatch_tool_once", once), \
             patch.object(brain_mod.time, "sleep") as sleep:
            assert b._dispatch_tool("web_search", {"query": "x"}) == "ok"
        assert once.call_count == 2
        sleep.assert_called_once_with(1.0)

    def test_exhausted_retries_return_error_string(self):
        b = _make_brain()
        once = MagicMock(side_effect=httpx.ConnectTimeout("still down"))
        with patch.object(b, "_dispatch_tool_once", once), \
             patch.object(brain_mod.time, "sleep") as sleep:
            result = b._dispatch_tool("web_search", {"query": "x"})
        assert once.call_count == 3
        assert sleep.call_count == 2
        assert "Tool error (web_search)" in result
        assert "3 attempts" in result

    def test_non_transient_error_not_retried(self):
        # _dispatch_tool_once converts non-transient exceptions to an error
        # string itself, so the wrapper sees a normal return — no retry.
        b = _make_brain()
        with patch("tools.web_tool.web_search", side_effect=ValueError("bad input")), \
             patch.object(brain_mod.time, "sleep") as sleep:
            result = b._dispatch_tool("web_search", {"query": "x"})
        assert result.startswith("Tool error (web_search)")
        assert "bad input" in result
        sleep.assert_not_called()

    def test_transient_error_from_real_tool_is_retried(self):
        b = _make_brain()
        with patch("tools.web_tool.web_search",
                   side_effect=[httpx.ConnectTimeout("blip"), "search results"]), \
             patch.object(brain_mod.time, "sleep"):
            result = b._dispatch_tool("web_search", {"query": "x"})
        assert result == "search results"
