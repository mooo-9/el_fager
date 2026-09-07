"""The three tools that act outward on Mo's behalf.

Mail, WhatsApp and calendar are the only tools that reach anyone but Mo, they
carry the stage → preview → confirm code, and they had no tests. A silent
break here does not show up as a crash — it shows up as a message that never
went, or one that went without being confirmed.

Everything below stubs the transport, so nothing is ever actually sent. What
is under test is the promise the design makes: composing arms an action and
sends nothing; only an explicit confirm sends; expiry and cancel both disarm.
"""
from datetime import datetime, timedelta

import pytest

from core import staging


@pytest.fixture(autouse=True)
def clean_registry():
    staging.reset()
    yield
    staging.reset()


# ── Gmail ──────────────────────────────────────────────────────────────────

@pytest.fixture
def gmail(monkeypatch):
    """Gmail with its transport replaced. Returns the list of sends."""
    import tools.gmail_tool as g
    sent = []

    class FakeSend:
        def execute(self):
            sent.append(True)
            return {"id": "fake"}

    class FakeMessages:
        def send(self, userId=None, body=None):
            return FakeSend()

    class FakeUsers:
        def messages(self):
            return FakeMessages()

    class FakeService:
        def users(self):
            return FakeUsers()

    monkeypatch.setattr(g, "GMAIL_AVAILABLE", True)
    monkeypatch.setattr(g, "get_gmail_service", lambda: FakeService())
    g._pending_send.clear()
    yield g, sent
    g._pending_send.clear()


class TestGmailStages:
    def test_composing_sends_nothing(self, gmail):
        g, sent = gmail
        out = g.send_message("omar@example.com", "Draft", "the body")
        assert sent == [], "composing an email sent it"
        assert "confirm" in out.lower()

    def test_composing_arms_the_registry(self, gmail):
        g, _ = gmail
        g.send_message("omar@example.com", "Draft", "the body")
        action = staging.current()
        assert action is not None
        assert action.medium == "gmail"
        assert action.target == "omar@example.com"
        assert action.body == "the body"

    def test_only_an_explicit_confirm_sends(self, gmail):
        g, sent = gmail
        g.send_message("omar@example.com", "Draft", "the body")
        assert sent == []
        g.confirm_send_message()
        assert sent == [True]

    def test_confirming_with_nothing_staged_sends_nothing(self, gmail):
        g, sent = gmail
        assert "no email staged" in g.confirm_send_message().lower()
        assert sent == []

    def test_an_expired_draft_is_not_sent(self, gmail):
        g, sent = gmail
        g.send_message("omar@example.com", "Draft", "the body")
        g._pending_send["expires_at"] = (
            datetime.now(g.CAIRO_TZ) - timedelta(seconds=1))
        out = g.confirm_send_message()
        assert sent == [], "an expired draft was still sent"
        assert "expired" in out.lower()
        assert staging.current() is None

    def test_a_send_leaves_a_receipt_without_the_body(self, gmail):
        g, _ = gmail
        g.send_message("omar@example.com", "Draft", "secret contents")
        g.confirm_send_message()
        receipts = staging.receipts()
        assert receipts, "a confirmed send left no receipt"
        blob = " ".join(str(r) for r in receipts)
        assert "omar@example.com" in blob
        assert "secret contents" not in blob, "the body leaked into the ledger"


# ── WhatsApp ───────────────────────────────────────────────────────────────

@pytest.fixture
def whatsapp(monkeypatch):
    """WhatsApp with the actual delivery call stubbed.

    Delivery is os.startfile() on a whatsapp:// URI, so that is what has to be
    intercepted. An earlier version of this fixture patched a function that
    did not exist with raising=False, which made every "nothing was sent"
    assertion below pass vacuously.
    """
    import tools.whatsapp_tool as w
    opened = []
    monkeypatch.setattr(w.os, "startfile", lambda uri: opened.append(uri))
    monkeypatch.setattr(w, "_wait_for_whatsapp_focus", lambda timeout=8.0: False)
    monkeypatch.setattr(w.time, "sleep", lambda s: None)
    w._pending.clear()
    yield w, opened
    w._pending.clear()


class TestWhatsAppStages:
    def test_composing_arms_rather_than_sends(self, whatsapp, monkeypatch):
        w, opened = whatsapp
        monkeypatch.setattr(w, "_find_contact",
                            lambda name: ("Omar", "+201000000000"))
        w.prepare_whatsapp_message("Omar", "on my way")
        action = staging.current()
        assert action is not None and action.medium == "whatsapp"
        assert action.target == "Omar"
        assert action.body == "on my way"
        assert opened == [], "composing a WhatsApp message sent it"

    def test_confirming_with_nothing_staged_is_refused(self, whatsapp):
        w, opened = whatsapp
        assert "no pending" in w.confirm_whatsapp_send().lower()
        assert opened == [], "WhatsApp was opened with nothing staged"

    def test_a_confirm_does_reach_the_delivery_call(self, whatsapp, monkeypatch):
        # The counterpart to the assertions above: proves they are checking a
        # call that genuinely fires, rather than one that never could.
        w, opened = whatsapp
        monkeypatch.setattr(w, "_find_contact",
                            lambda name: ("Omar", "+201000000000"))
        w.prepare_whatsapp_message("Omar", "on my way")
        assert opened == []
        w.confirm_whatsapp_send()
        assert len(opened) == 1
        assert opened[0].startswith("whatsapp://send?phone=201000000000")

    def test_an_expired_message_is_refused(self, whatsapp):
        w, opened = whatsapp
        w._pending.update({
            "name": "Omar", "phone": "+201000000000", "message": "hi",
            "expires_at": datetime.now(w.CAIRO_TZ) - timedelta(seconds=1),
        })
        out = w.confirm_whatsapp_send()
        assert "expired" in out.lower()
        assert opened == [], "an expired message still opened WhatsApp"


# ── The registry itself ────────────────────────────────────────────────────

class TestOneActionAtATime:
    def test_staging_a_second_action_replaces_the_first(self):
        staging.stage(medium="gmail", target="a@example.com", body="first")
        staging.stage(medium="whatsapp", target="Omar", body="second")
        current = staging.current()
        assert current.medium == "whatsapp" and current.body == "second"

    def test_cancel_disarms(self):
        cancelled = []
        staging.stage(medium="gmail", target="a@example.com", body="x",
                      cancel=lambda: cancelled.append(True))
        staging.cancel()
        assert staging.current() is None
        assert cancelled == [True]

    def test_an_expired_action_disappears_rather_than_lingering(self):
        # current() clears an expired action on read, so no surface can offer
        # a confirm button for something that can no longer be sent.
        staging.stage(medium="gmail", target="a@example.com", body="x",
                      expires_at=datetime.now() - timedelta(seconds=1))
        assert staging.current() is None

    def test_a_live_action_survives_the_same_read(self):
        staging.stage(medium="gmail", target="a@example.com", body="x",
                      expires_at=datetime.now() + timedelta(minutes=5))
        assert staging.current() is not None

    def test_a_surface_that_raises_does_not_break_a_send(self):
        # Surfaces subscribe to redraw; one throwing must not stop the action.
        staging.subscribe(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        staging.stage(medium="gmail", target="a@example.com", body="x")
        assert staging.current() is not None
