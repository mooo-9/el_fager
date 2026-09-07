"""Suite-wide guards, so a test run never writes into Mo's real data.

Three things leak otherwise: the agent ledger, written by every supervised
dispatch including ones made deep inside brain tests; Warden, which would
reach the API; and brain.chat()'s conversation log, which HabitMiner later
mines for real usage.
"""
import pytest


@pytest.fixture(autouse=True)
def _ledger_off_disk(tmp_path, monkeypatch):
    monkeypatch.setattr("core.agents.ledger._LEDGER_PATH",
                        tmp_path / "agent_runs.jsonl", raising=False)


@pytest.fixture(autouse=True)
def _inspector_offline(monkeypatch):
    """Warden never reaches the API during tests.

    The real inspector is exercised directly in tests/agents/test_verifier.py,
    which imports `verify` by value and so is unaffected by this patch. Here it
    returns 'unclear' -- the same verdict a real offline run produces, which the
    supervisor treats as a pass. Tests that care about a specific verdict patch
    core.agents.verifier.verify themselves and win over this fixture.
    """
    from core.agents.verifier import Verdict
    monkeypatch.setattr(
        "core.agents.verifier.verify",
        lambda task, acceptance, result: Verdict("unclear", "offline in tests"),
        raising=False,
    )


@pytest.fixture(autouse=True)
def _el_fager_test_mode(monkeypatch):
    """Conversation turns divert to data/conversations_test/, so the suite
    never pollutes the usage logs HabitMiner mines."""
    monkeypatch.setenv("EL_FAGER_TEST_MODE", "1")
