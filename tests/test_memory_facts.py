"""Tests for core/memory.py facts layer — degraded flag and growth bound.

Memory is built via __new__ to skip __init__'s ChromaDB daemon thread; the
facts layer is pure-JSON and doesn't need the vector store.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import core.memory as cm


@pytest.fixture
def mem(tmp_path, monkeypatch):
    monkeypatch.setattr(cm, "_FACTS_FILE", tmp_path / "facts.json")
    m = cm.Memory.__new__(cm.Memory)  # skip __init__ (no chroma thread)
    m._collection = None
    m._ready = False
    m._failed = False
    return m


class TestDegradedFlag:
    def test_not_degraded_while_loading(self, mem):
        assert mem.degraded is False

    def test_degraded_after_failed_init(self, mem):
        mem._failed = True
        assert mem.degraded is True


class TestFactsGrowthBound:
    def test_store_and_retrieve(self, mem):
        mem.store_fact("Mo likes coffee", "preference")
        facts = mem.get_all_facts()
        assert len(facts) == 1
        assert facts[0]["content"] == "Mo likes coffee"

    def test_cap_drops_oldest_non_deadline(self, mem, monkeypatch):
        monkeypatch.setattr(cm, "_MAX_FACTS", 5)
        mem.store_fact("exam on 2026-08-01", "deadline")
        for i in range(6):
            mem.store_fact(f"fact number {i}", "other")
        facts = mem.get_all_facts()
        assert len(facts) <= 5
        # The deadline fact survives the cap
        assert any(f["category"] == "deadline" for f in facts)
        # The oldest non-deadline facts were dropped
        contents = [f["content"] for f in facts]
        assert "fact number 0" not in contents
        assert "fact number 5" in contents
