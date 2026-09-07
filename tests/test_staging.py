"""Tests for the staging registry — the one record of what is armed.

The rules that matter here are trust rules: nothing is marked sent unless it
actually left the machine, an expired action cannot be confirmed, and the
receipt log never stores the message body.
"""
import json

import pytest

from core import staging


@pytest.fixture(autouse=True)
def clean_registry(tmp_path, monkeypatch):
    from core import ledger
    monkeypatch.setattr(ledger, "_LEDGER", tmp_path / "action_ledger.jsonl")
    monkeypatch.setattr(ledger, "_KEY", tmp_path / "ledger.key")
    monkeypatch.setattr(ledger, "_fernet", None)
    staging.reset()
    yield
    staging.reset()


class TestStageAndConfirm:
    def test_staging_publishes_the_armed_action(self):
        staging.stage(medium="whatsapp", target="Omar", body="the meeting moved")
        action = staging.current()
        assert action.medium == "whatsapp"
        assert action.target == "Omar"
        assert action.body == "the meeting moved"

    def test_staging_again_replaces_the_previous(self):
        staging.stage(medium="whatsapp", target="Omar", body="first")
        staging.stage(medium="gmail", target="mo@x.com", body="second")
        assert staging.current().medium == "gmail"
        assert staging.current().body == "second"

    def test_confirm_runs_the_tools_own_confirm(self):
        calls = []
        staging.stage(medium="whatsapp", target="Omar", body="hi",
                      confirm=lambda: calls.append("sent") or "Sent to Omar")
        assert staging.confirm() == "Sent to Omar"
        assert calls == ["sent"]

    def test_cancel_drops_it_without_sending(self):
        sent = []
        cleared = []
        staging.stage(medium="whatsapp", target="Omar", body="hi",
                      confirm=lambda: sent.append(1), cancel=lambda: cleared.append(1))
        staging.cancel()
        assert staging.current() is None
        assert sent == []
        assert cleared == [1]

    def test_confirming_nothing_is_harmless(self):
        assert "Nothing" in staging.confirm()


class TestExpiry:
    def test_an_expired_action_is_not_current(self):
        from datetime import datetime, timedelta
        staging.stage(medium="whatsapp", target="Omar", body="hi",
                      expires_at=datetime.now() - timedelta(seconds=1))
        assert staging.current() is None

    def test_an_expired_action_cannot_be_confirmed(self):
        from datetime import datetime, timedelta
        fired = []
        staging.stage(medium="whatsapp", target="Omar", body="hi",
                      expires_at=datetime.now() - timedelta(seconds=1),
                      confirm=lambda: fired.append(1))
        result = staging.confirm()
        assert fired == []
        assert "expired" in result.lower()


class TestReceipts:
    def test_only_a_real_send_writes_a_receipt(self):
        staging.stage(medium="whatsapp", target="Omar", body="hi")
        staging.resolve("handoff")          # opened the app, Mo presses Enter
        assert staging.receipts() == []

        staging.stage(medium="whatsapp", target="Omar", body="hi")
        staging.resolve("sent", "whatsapp → Omar · sent")
        assert len(staging.receipts()) == 1
        assert staging.receipts()[0]["summary"] == "whatsapp → Omar · sent"

    def test_receipts_keep_only_the_last_three(self):
        for i in range(5):
            staging.stage(medium="gmail", target=f"p{i}@x.com", body="b")
            staging.resolve("sent")
        assert len(staging.receipts()) == 3
        assert staging.receipts()[0]["target"] == "p4@x.com"   # newest first

    def test_the_ledger_never_stores_the_message_body(self):
        from core import ledger
        secret = "the account number is 12345"
        staging.stage(medium="gmail", target="mo@x.com", body=secret)
        staging.resolve("sent")
        # not in the file (which is encrypted) and not in the decrypted record
        assert secret not in ledger._LEDGER.read_bytes().decode("utf-8", "ignore")
        entry = ledger.entries()[0]
        assert entry["target"] == "mo@x.com"
        assert secret not in json.dumps(entry, ensure_ascii=False)

    def test_a_failed_send_writes_no_receipt(self):
        staging.stage(medium="gmail", target="mo@x.com", body="b")
        staging.resolve("failed")
        assert staging.receipts() == []


class TestSubscribers:
    def test_surfaces_are_notified_on_stage_and_resolve(self):
        seen = []
        staging.subscribe(lambda: seen.append(1))
        staging.stage(medium="whatsapp", target="Omar", body="hi")
        staging.resolve("sent")
        assert len(seen) == 2

    def test_a_broken_surface_cannot_break_a_send(self):
        def explode():
            raise RuntimeError("surface is gone")
        staging.subscribe(explode)
        staging.stage(medium="whatsapp", target="Omar", body="hi")   # must not raise
        assert staging.current() is not None
