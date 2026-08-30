"""Suite-wide guards.

The agent ledger is written by every supervised dispatch, including ones made
deep inside brain tests. Redirect it per-test so a test run never appends to
the real data/agent_runs.jsonl.
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
