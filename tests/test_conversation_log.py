"""EL_FAGER_TEST_MODE must divert conversation logs away from real usage data."""
import os

import pytest

from core.conversation_log import ConversationLogger


@pytest.fixture
def in_tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


def test_default_writes_to_real_dir(in_tmp, monkeypatch):
    monkeypatch.delenv("EL_FAGER_TEST_MODE", raising=False)
    logger = ConversationLogger()
    logger.log("user", "hello")
    assert logger.LOG_DIR.name == "conversations"
    assert any(logger.LOG_DIR.glob("*.jsonl"))


def test_test_mode_writes_to_separate_dir(in_tmp, monkeypatch):
    monkeypatch.setenv("EL_FAGER_TEST_MODE", "1")
    logger = ConversationLogger()
    logger.log("user", "loop forever")
    assert logger.LOG_DIR.name == "conversations_test"
    assert any(logger.LOG_DIR.glob("*.jsonl"))
    assert not (logger.LOG_DIR.parent / "conversations").exists()
