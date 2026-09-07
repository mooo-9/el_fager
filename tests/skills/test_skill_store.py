"""Unit tests for core/skills/store.py — the SkillForge skill store."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

import json

import pytest

from core.skills.store import SkillStore


@pytest.fixture
def store(tmp_path):
    return SkillStore(
        path=tmp_path / "skills.json",
        seeds_path=tmp_path / "no_seeds.json",  # missing file -> no seeds
    )


class TestAddAndGet:
    def test_add_returns_skill_with_defaults(self, store):
        s = store.add("morning nvda", "Check NVDA price and RSI, then summarize.")
        assert s["name"] == "morning nvda"
        assert s["source"] == "taught"
        assert s["run_count"] == 0
        assert s["scheduled_task_id"] is None
        assert s["automation_proposed"] is False

    def test_add_duplicate_name_rejected(self, store):
        store.add("x", "do x")
        with pytest.raises(ValueError):
            store.add("X", "do x again")  # case-insensitive dup

    def test_get_by_exact_name_case_insensitive(self, store):
        store.add("Morning NVDA", "steps")
        assert store.get("morning nvda")["name"] == "Morning NVDA"

    def test_get_by_trigger_phrase_inside_query(self, store):
        store.add("focus mode", "Play focus playlist", trigger_phrases=["focus time"])
        found = store.get("yalla focus time please")
        assert found is not None and found["name"] == "focus mode"

    def test_get_by_name_substring_in_query(self, store):
        store.add("morning routine", "steps")
        assert store.get("run my morning routine now")["name"] == "morning routine"

    def test_get_unknown_returns_none(self, store):
        assert store.get("nothing here") is None

    def test_persistence_across_instances(self, store, tmp_path):
        store.add("persisted", "steps")
        fresh = SkillStore(path=tmp_path / "skills.json",
                           seeds_path=tmp_path / "no_seeds.json")
        assert fresh.get("persisted") is not None


class TestRunTracking:
    def test_mark_run_increments_and_stamps(self, store):
        store.add("s", "steps")
        store.mark_run("s")
        store.mark_run("s")
        skill = store.get("s")
        assert skill["run_count"] == 2
        assert skill["last_run_at"] is not None

    def test_schedule_roundtrip(self, store):
        store.add("s", "steps")
        store.set_schedule("s", "task123")
        assert store.get("s")["scheduled_task_id"] == "task123"
        store.clear_schedule("s")
        assert store.get("s")["scheduled_task_id"] is None

    def test_delete(self, store):
        store.add("gone", "steps")
        assert store.delete("gone") is True
        assert store.get("gone") is None
        assert store.delete("gone") is False


class TestSeeds:
    def _seeds_file(self, tmp_path):
        seeds = [
            {"name": "morning routine", "instructions": "Do the briefing.",
             "trigger_phrases": ["good morning"], "pack": "daily-life"},
            {"name": "focus mode", "instructions": "Play focus music.",
             "trigger_phrases": ["focus time"], "pack": "music"},
        ]
        p = tmp_path / "seeds.json"
        p.write_text(json.dumps(seeds), encoding="utf-8")
        return p

    def test_seeds_installed_on_first_load(self, tmp_path):
        store = SkillStore(path=tmp_path / "skills.json",
                           seeds_path=self._seeds_file(tmp_path))
        names = {s["name"] for s in store.list_all()}
        assert {"morning routine", "focus mode"} <= names
        assert all(s["source"] == "seed" for s in store.list_all())

    def test_seed_install_is_idempotent(self, tmp_path):
        seeds = self._seeds_file(tmp_path)
        store = SkillStore(path=tmp_path / "skills.json", seeds_path=seeds)
        store.delete("focus mode")  # Mo removed a seed on purpose
        again = SkillStore(path=tmp_path / "skills.json", seeds_path=seeds)
        assert again.get("focus mode") is None  # not re-installed
        assert len(again.list_all()) == 1

    def test_real_seed_file_is_valid_and_covers_all_packs(self):
        # The committed seed file must parse and contain all 4 packs.
        repo_seeds = os.path.join(os.path.dirname(__file__), "..", "..",
                                  "core", "skills", "seeds.json")
        data = json.loads(open(repo_seeds, encoding="utf-8").read())
        packs = {s["pack"] for s in data}
        assert {"study", "research", "music", "daily-life"} <= packs
        for s in data:
            assert s["name"] and s["instructions"]
