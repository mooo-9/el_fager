"""Tests for the Trust Ledger.

THE LAW is the point of this file: nothing is ever edited or deleted, a
revoke appends a new entry and the original stays visible marked REVOKED,
search reads the record rather than speculating, and the file is unreadable
without the key.
"""
import json

import pytest

from core import ledger


@pytest.fixture(autouse=True)
def clean(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "_LEDGER", tmp_path / "action_ledger.jsonl")
    monkeypatch.setattr(ledger, "_KEY", tmp_path / "ledger.key")
    monkeypatch.setattr(ledger, "_fernet", None)
    yield
    monkeypatch.setattr(ledger, "_fernet", None)


class TestTheLaw:
    def test_a_revoke_appends_and_never_deletes(self):
        sent = ledger.append("sent", "whatsapp", "Omar", "whatsapp → Omar · sent")
        ledger.revoke(sent["id"], "changed my mind")

        lines = ledger._LEDGER.read_bytes().splitlines()
        assert len(lines) == 2                  # nothing was rewritten
        all_ids = [e["id"] for e in ledger.entries()]
        assert sent["id"] in all_ids            # the original is still there

    def test_the_original_reads_revoked(self):
        sent = ledger.append("sent", "whatsapp", "Omar", "sent")
        ledger.revoke(sent["id"])
        original = next(e for e in ledger.entries() if e["id"] == sent["id"])
        assert original["revoked"] is True

    def test_the_revoking_entry_is_its_own_record(self):
        sent = ledger.append("sent", "gmail", "mo@x.com", "sent")
        rev = ledger.revoke(sent["id"], "wrong recipient")
        assert rev["category"] == "revoked"
        assert rev["revokes"] == sent["id"]
        assert rev["provenance"] == "wrong recipient"

    def test_revoking_something_that_never_happened_is_a_no_op(self):
        assert ledger.revoke("nope") is None

    def test_a_recorded_revoke_never_claims_the_world_changed(self):
        # We cannot unsend a WhatsApp message; the record must not imply we did.
        sent = ledger.append("sent", "whatsapp", "Omar", "sent")
        rev = ledger.revoke(sent["id"])
        assert rev["reversal"] == "recorded"
        performed = ledger.revoke(sent["id"], performed=True)
        assert performed["reversal"] == "performed"


class TestEncryption:
    def test_the_file_is_unreadable_without_the_key(self):
        ledger.append("sent", "whatsapp", "Omar Adel", "whatsapp → Omar Adel · sent")
        raw = ledger._LEDGER.read_bytes().decode("utf-8", "ignore")
        assert "Omar Adel" not in raw
        assert "whatsapp" not in raw

    def test_it_reads_back_through_the_key(self):
        ledger.append("sent", "whatsapp", "Omar Adel", "summary here")
        entry = ledger.entries()[0]
        assert entry["target"] == "Omar Adel"
        assert entry["summary"] == "summary here"

    def test_pre_encryption_lines_are_still_readable(self):
        legacy = {"medium": "gmail", "target": "old@x.com", "summary": "legacy",
                  "at": "09:00", "ts": "2026-07-01T09:00:00"}
        ledger._LEDGER.parent.mkdir(parents=True, exist_ok=True)
        ledger._LEDGER.write_bytes((json.dumps(legacy) + "\n").encode("utf-8"))
        ledger.append("sent", "whatsapp", "Omar", "new one")
        targets = {e["target"] for e in ledger.entries()}
        assert targets == {"old@x.com", "Omar"}


class TestReadingTheRecord:
    def test_newest_first(self):
        ledger.append("sent", "gmail", "first@x.com", "a")
        ledger.append("sent", "gmail", "second@x.com", "b")
        assert ledger.entries()[0]["target"] == "second@x.com"

    def test_filtering_by_category(self):
        ledger.append("sent", "gmail", "a@x.com", "a")
        ledger.append("read", "gmail", "b@x.com", "b")
        assert [e["target"] for e in ledger.entries(category="read")] == ["b@x.com"]

    def test_every_entry_says_why_it_happened(self):
        entry = ledger.append("sent", "whatsapp", "Omar", "sent")
        assert entry["provenance"]

    def test_an_entry_past_its_window_reads_sealed(self):
        from datetime import datetime, timedelta
        ledger.append("sent", "gmail", "a@x.com", "a")     # 30s undo window
        rows = ledger.entries()
        assert rows[0]["sealed"] is False
        # walk the clock past the window by rewriting nothing — just re-read
        old = datetime.now() - timedelta(minutes=5)
        ledger.append("sent", "gmail", "b@x.com", "b", ts=old.isoformat(timespec="seconds"))
        aged = next(e for e in ledger.entries() if e["target"] == "b@x.com")
        assert aged["sealed"] is True

    def test_counters_report_total_and_still_revocable(self):
        ledger.append("sent", "whatsapp", "Omar", "a")     # 2-day window
        ledger.append("sent", "gmail", "a@x.com", "b")     # 30s window
        counts = ledger.counters()
        assert counts["total_30d"] == 2
        assert counts["revocable"] == 2


class TestSearch:
    def test_it_answers_from_the_record(self):
        ledger.append("sent", "whatsapp", "Omar", "whatsapp → Omar · sent")
        ledger.append("sent", "gmail", "hr@guc.edu.eg", "gmail → hr@guc.edu.eg · sent")
        hits = ledger.search("omar")
        assert len(hits) == 1
        assert hits[0]["target"] == "Omar"

    def test_it_returns_nothing_rather_than_speculating(self):
        ledger.append("sent", "whatsapp", "Omar", "sent")
        assert ledger.search("what did I tell my landlord") == []

    def test_an_empty_query_matches_nothing(self):
        ledger.append("sent", "whatsapp", "Omar", "sent")
        assert ledger.search("   ") == []

    def test_it_searches_provenance_too(self):
        ledger.append("sent", "whatsapp", "Omar", "sent",
                      provenance="YOU SAID “SEND OMAR A MESSAGE” · CONFIRMED BY VOICE")
        assert len(ledger.search("SEND OMAR")) == 1
