"""Saying "yes, send it" has to send what is staged.

History keeps only the assistant's final text, not its tool calls, so on the
confirm turn the model could not see that a draft was already armed. It
called send_email again, the draft asked for a yes again, and the email never
went (Mo's log, 2026-09-15 02:47 — four yeses, no send). Typed turns reset the
conversation after every turn, so there the email tools were not even offered.

What holds the line: the model is told what is staged on every turn, and a
confirm and a cancel for it are always on offer.
"""
import pytest

from core import staging
from core.brain import Brain, _select_tools


@pytest.fixture(autouse=True)
def clean_registry():
    staging.reset()
    yield
    staging.reset()


def _stage_email(confirm=lambda: "Sent", cancel=None):
    return staging.stage(
        medium="gmail", target="omar@example.com", body="thanks",
        subject="Lecture", confirm=confirm, cancel=cancel,
    )


class TestTheModelSeesWhatIsStaged:
    def test_a_staged_email_is_named_in_the_prompt(self):
        blocks = Brain(profile={})._build_system(staged=_stage_email())
        dynamic = blocks[-1]
        assert "cache_control" not in dynamic
        assert "omar@example.com" in dynamic["text"]
        assert "confirm_staged_action" in dynamic["text"]
        assert "cancel_staged_action" in dynamic["text"]

    def test_nothing_staged_adds_nothing(self):
        text = " ".join(b["text"] for b in Brain(profile={})._build_system())
        assert "STAGED" not in text


class TestConfirmAndCancelAreAlwaysOffered:
    def test_a_bare_yes_with_no_history_still_offers_them(self):
        names = {t["name"] for t in _select_tools("yes send it")}
        assert {"confirm_staged_action", "cancel_staged_action"} <= names


class TestDispatch:
    def test_confirm_runs_the_staged_confirm(self):
        sent = []
        _stage_email(confirm=lambda: sent.append(1) or "Sent to omar")
        out = Brain(profile={})._dispatch_tool_once("confirm_staged_action", {})
        assert sent == [1]
        assert "Sent to omar" in out

    def test_cancel_disarms_without_sending(self):
        sent, cancelled = [], []
        _stage_email(confirm=lambda: sent.append(1) or "Sent",
                     cancel=lambda: cancelled.append(1))
        Brain(profile={})._dispatch_tool_once("cancel_staged_action", {})
        assert staging.current() is None
        assert cancelled == [1]
        assert sent == []


def _tool_use(name):
    from unittest.mock import MagicMock
    block = MagicMock(type="tool_use", id="t1", input={})
    block.name = name
    return MagicMock(stop_reason="tool_use", content=[block])


def _end(text="ok"):
    from unittest.mock import MagicMock
    return MagicMock(stop_reason="end_turn",
                     content=[MagicMock(type="text", text=text)])


def _run_turn(brain, message, responses, history=None):
    """One chat turn with the model scripted; returns what each tool said."""
    results, prompts = [], []

    def fake_create(_source, **kwargs):
        prompts.append(kwargs["system"])
        for m in kwargs["messages"]:
            if isinstance(m["content"], list):
                results.extend(c["content"] for c in m["content"]
                               if isinstance(c, dict) and c.get("type") == "tool_result")
        return responses.pop(0)

    brain._create_message = fake_create
    brain._logger = None
    brain.chat(message, history=history)
    return results, prompts


class TestOnlyADraftMoHasSeenCanBeConfirmed:
    """The model once re-staged an expired email and confirmed it in the same
    turn — a send Mo never saw. A confirm is honoured only when something was
    already staged as the turn began, and never from a background turn."""

    def test_a_draft_on_screen_is_sent(self):
        sent = []
        _stage_email(confirm=lambda: sent.append(1) or "Sent")
        _run_turn(Brain(profile={}), "yes send it",
                  [_tool_use("confirm_staged_action"), _end()])
        assert sent == [1]

    @pytest.mark.parametrize("tool", [
        "confirm_staged_action", "confirm_send_email", "confirm_reply_email",
        "confirm_whatsapp_send", "confirm_calendar_delete"])
    def test_staging_and_confirming_in_one_turn_is_refused(self, tool):
        sent = []
        brain = Brain(profile={})
        real = brain._dispatch_tool_once

        def dispatch(name, tool_input):
            if name == "send_email":       # the model stages a fresh draft...
                _stage_email(confirm=lambda: sent.append(1) or "Sent")
                return "Ready to send"
            return real(name, tool_input)

        brain._dispatch_tool_once = dispatch
        results, _ = _run_turn(brain, "yes send it",
                               [_tool_use("send_email"), _tool_use(tool), _end()])
        assert sent == []                 # ...and cannot send it unseen
        assert staging.current() is not None
        assert "NOT SENT" in results[-1]

    def test_a_background_turn_cannot_confirm_what_mo_has_staged(self):
        sent = []
        _stage_email(confirm=lambda: sent.append(1) or "Sent")
        results, prompts = _run_turn(Brain(profile={}), "check NVDA",
                                     [_tool_use("confirm_staged_action"), _end()],
                                     history=[])
        assert sent == []
        assert all("omar@example.com" not in str(p) for p in prompts)

    def test_an_edit_and_a_yes_can_restage_then_send(self):
        sent = []
        _stage_email(confirm=lambda: sent.append("old") or "Sent")
        brain = Brain(profile={})
        real = brain._dispatch_tool_once

        def dispatch(name, tool_input):
            if name == "send_email":
                _stage_email(confirm=lambda: sent.append("new") or "Sent")
                return "Ready to send"
            return real(name, tool_input)

        brain._dispatch_tool_once = dispatch
        _run_turn(brain, "make it lowercase and yes send it",
                  [_tool_use("send_email"), _tool_use("confirm_staged_action"), _end()])
        assert sent == ["new"]


class TestAStagedTurnGetsTheFullModel:
    def test_never_mind_goes_to_the_full_model_while_something_is_staged(self):
        brain = Brain(profile={})
        brain._fast_path_enabled = True
        assert brain._select_model("never mind") == brain._fast_model
        _stage_email()
        assert brain._select_model("never mind") == brain._model
