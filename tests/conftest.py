"""Suite-wide isolation: tests that exercise brain.chat() log conversation
turns; EL_FAGER_TEST_MODE diverts them to data/conversations_test/ so the
suite never pollutes the real usage logs HabitMiner mines."""
import pytest


@pytest.fixture(autouse=True)
def _el_fager_test_mode(monkeypatch):
    monkeypatch.setenv("EL_FAGER_TEST_MODE", "1")


@pytest.fixture(autouse=True)
def _isolated_trust_ledger(monkeypatch, tmp_path):
    """Any test that confirms a staged send appends to the Trust Ledger. Left
    alone, that wrote "sent gmail -> a@b.c" and "whatsapp -> Omar" into Mo's
    real data/action_ledger.jsonl on every run — an append-only record he
    reads as what El Fager did. Point it at a file of the test's own."""
    from core import ledger
    monkeypatch.setattr(ledger, "_LEDGER", tmp_path / "action_ledger.jsonl")
