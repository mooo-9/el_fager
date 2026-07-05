"""Suite-wide isolation: tests that exercise brain.chat() log conversation
turns; EL_FAGER_TEST_MODE diverts them to data/conversations_test/ so the
suite never pollutes the real usage logs HabitMiner mines."""
import pytest


@pytest.fixture(autouse=True)
def _el_fager_test_mode(monkeypatch):
    monkeypatch.setenv("EL_FAGER_TEST_MODE", "1")
