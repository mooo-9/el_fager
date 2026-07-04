"""Unit tests for core/skills/miner.py — repetition mining from conversation logs."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import json
from datetime import datetime, timedelta

import pytest

from core.skills.miner import HabitMiner, fingerprint
from core.skills.store import SkillStore


def _write_day(convo_dir, days_ago: int, user_texts: list[str]):
    convo_dir.mkdir(parents=True, exist_ok=True)
    day = (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d")
    lines = []
    for text in user_texts:
        lines.append(json.dumps({"timestamp": f"{day}T09:00:00", "role": "user",
                                 "content": text, "tools_used": []}))
        lines.append(json.dumps({"timestamp": f"{day}T09:00:05", "role": "assistant",
                                 "content": "done", "tools_used": ["web_search"]}))
    (convo_dir / f"{day}.jsonl").write_text("\n".join(lines), encoding="utf-8")


@pytest.fixture
def env(tmp_path):
    convo = tmp_path / "conversations"
    store = SkillStore(path=tmp_path / "skills.json",
                       seeds_path=tmp_path / "no_seeds.json")
    miner = HabitMiner(conversations_dir=convo,
                       proposals_path=tmp_path / "proposals.json",
                       store=store)
    return convo, store, miner


class TestFingerprint:
    def test_ignores_case_punctuation_and_digits(self):
        assert fingerprint("Check NVDA's RSI!") == fingerprint("check nvda rsi 42")

    def test_word_order_does_not_matter(self):
        assert fingerprint("rsi nvda check") == fingerprint("check nvda rsi")

    def test_stopwords_dropped(self):
        assert fingerprint("can you please check the nvda rsi for me") == \
               fingerprint("check nvda rsi")

    def test_too_short_returns_empty(self):
        assert fingerprint("hi") == ""


class TestMining:
    def test_three_days_of_repetition_creates_proposal(self, env):
        convo, _, miner = env
        for d in (1, 2, 3):
            _write_day(convo, d, ["check nvda rsi please", "what's the weather"])
        proposals = miner.mine(days=14, min_days=3)
        examples = [p["example"] for p in proposals]
        assert any("nvda" in e for e in examples)
        # weather asked 3x too -> also proposed
        assert len(proposals) == 2

    def test_two_days_is_not_enough(self, env):
        convo, _, miner = env
        for d in (1, 2):
            _write_day(convo, d, ["check nvda rsi please"])
        assert miner.mine(days=14, min_days=3) == []

    def test_same_day_repeats_count_once(self, env):
        convo, _, miner = env
        _write_day(convo, 1, ["check nvda rsi"] * 5)
        assert miner.mine(days=14, min_days=3) == []

    def test_existing_skill_suppresses_proposal(self, env):
        convo, store, miner = env
        store.add("nvda check", "check it", trigger_phrases=["check nvda rsi"])
        for d in (1, 2, 3):
            _write_day(convo, d, ["check nvda rsi please"])
        assert miner.mine(days=14, min_days=3) == []

    def test_second_mine_does_not_duplicate(self, env):
        convo, _, miner = env
        for d in (1, 2, 3):
            _write_day(convo, d, ["check nvda rsi please"])
        first = miner.mine(days=14, min_days=3)
        second = miner.mine(days=14, min_days=3)
        assert len(first) == 1
        assert second == []

    def test_dismissed_proposal_not_reproposed(self, env):
        convo, _, miner = env
        for d in (1, 2, 3):
            _write_day(convo, d, ["check nvda rsi please"])
        p = miner.mine(days=14, min_days=3)[0]
        miner.set_status(p["id"], "dismissed")
        assert miner.mine(days=14, min_days=3) == []
        assert miner.pending() == []

    def test_pending_lists_only_pending(self, env):
        convo, _, miner = env
        for d in (1, 2, 3):
            _write_day(convo, d, ["check nvda rsi", "play some quran"])
        proposals = miner.mine(days=14, min_days=3)
        miner.set_status(proposals[0]["id"], "accepted")
        assert len(miner.pending()) == 1

    def test_long_messages_ignored(self, env):
        convo, _, miner = env
        essay = "summarize this " + "very long text " * 30
        for d in (1, 2, 3):
            _write_day(convo, d, [essay])
        assert miner.mine(days=14, min_days=3) == []
