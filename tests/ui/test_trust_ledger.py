"""Tests for the Trust Ledger surface.

The surface has to be as trustworthy as the record behind it: revoking
appends rather than edits, a sealed entry offers no action it cannot
perform, and the search strip never implies an answer the record doesn't
contain.
"""
import pytest

from core import ledger


@pytest.fixture(autouse=True)
def clean(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "_LEDGER", tmp_path / "action_ledger.jsonl")
    monkeypatch.setattr(ledger, "_KEY", tmp_path / "ledger.key")
    monkeypatch.setattr(ledger, "_fernet", None)
    yield
    monkeypatch.setattr(ledger, "_fernet", None)


def _window(qapp):
    from ui.trust_ledger import TrustLedgerWindow
    return TrustLedgerWindow()


def _rows(w):
    from ui.trust_ledger import _Row
    return [w._rows.itemAt(i).widget() for i in range(w._rows.count())
            if isinstance(w._rows.itemAt(i).widget(), _Row)]


class TestReadingTheRecord:
    def test_entries_appear_newest_first(self, qapp):
        ledger.append("sent", "whatsapp", "Omar", "first")
        ledger.append("sent", "gmail", "mo@x.com", "second")
        w = _window(qapp)
        assert _rows(w)[0]._entry["summary"] == "second"
        w.close()

    def test_the_counters_show_total_and_still_revocable(self, qapp):
        ledger.append("sent", "whatsapp", "Omar", "a")
        w = _window(qapp)
        assert "1 ENTRIES · 30 DAYS" in w._counters.text()
        assert "STILL REVOCABLE" in w._counters.text()
        w.close()

    def test_a_filter_narrows_to_one_category(self, qapp):
        ledger.append("sent", "whatsapp", "Omar", "a sent thing")
        ledger.append("read", "gmail", "mo@x.com", "a read thing")
        w = _window(qapp)
        w._set_filter("read")
        assert [r._entry["summary"] for r in _rows(w)] == ["a read thing"]
        w.close()


class TestRevoking:
    def test_revoking_appends_and_keeps_the_original(self, qapp):
        entry = ledger.append("sent", "whatsapp", "Omar", "the message")
        w = _window(qapp)
        w._revoke(entry)
        lines = ledger._LEDGER.read_bytes().splitlines()
        assert len(lines) == 2                       # appended, not rewritten
        summaries = [r._entry["summary"] for r in _rows(w)]
        assert "the message" in summaries            # original still on screen
        w.close()

    def test_the_revoked_original_is_marked_not_removed(self, qapp):
        entry = ledger.append("sent", "whatsapp", "Omar", "the message")
        w = _window(qapp)
        w._revoke(entry)
        original = next(r._entry for r in _rows(w) if r._entry["id"] == entry["id"])
        assert original["revoked"] is True
        w.close()

    def test_the_surface_never_claims_it_unsent_anything(self, qapp):
        # We cannot reach into WhatsApp; the record must say so.
        entry = ledger.append("sent", "whatsapp", "Omar", "the message")
        w = _window(qapp)
        w._revoke(entry)
        reversal = next(e for e in ledger.entries() if e.get("revokes") == entry["id"])
        assert reversal["reversal"] == "recorded"
        w.close()

    def test_the_action_names_what_it_would_actually_do(self):
        from ui.trust_ledger import _REVOKE_VERB
        assert _REVOKE_VERB["whatsapp"] == "Delete for all"
        assert _REVOKE_VERB["gmail"] == "Unsend"


class TestSearchStrip:
    def test_a_hit_is_reported_as_coming_from_the_ledger(self, qapp):
        ledger.append("sent", "whatsapp", "Omar", "whatsapp to Omar")
        w = _window(qapp)
        w._search.setText("omar")
        assert w._answer.isVisibleTo(w)
        assert "ANSWERED FROM THE LEDGER, NOT THE MODEL" in w._answer.text()
        assert "1 ENTRY MATCH" in w._answer.text()
        w.close()

    def test_a_miss_says_the_record_has_nothing_rather_than_guessing(self, qapp):
        ledger.append("sent", "whatsapp", "Omar", "whatsapp to Omar")
        w = _window(qapp)
        w._search.setText("my landlord")
        assert "NOTHING IN THE RECORD MATCHES" in w._answer.text()
        assert _rows(w) == []
        w.close()

    def test_clearing_the_search_returns_to_the_full_record(self, qapp):
        ledger.append("sent", "whatsapp", "Omar", "whatsapp to Omar")
        w = _window(qapp)
        w._search.setText("nothing matches this")
        w._search.setText("")
        assert not w._answer.isVisibleTo(w)
        assert len(_rows(w)) == 1
        w.close()


class TestTheLawIsOnScreen:
    def test_every_category_has_a_tint(self):
        from ui import tokens
        for category in ledger.CATEGORIES:
            assert category in tokens.LEDGER_TINT
